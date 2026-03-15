"""
DONE · core/export.py
──────────────────────
Export the DONE database in multiple formats.

Every export includes full provenance — every entity
traces back to its exact document, page, and character offset.

Formats:
  SQLite  — portable single file copy of the database
  JSON    — full structured export for APIs / data transfer
  CSV     — flat files for Excel / basic analytics
  Parquet — columnar format for data companies / Snowflake / BigQuery

Public API:
  export_sqlite(output_path, conn)    → copy of database
  export_json(output_path, conn)      → full JSON export
  export_csv(output_dir, conn)        → one CSV per table
  export_parquet(output_dir, conn)    → one Parquet per table

Usage:
  python core/export.py --sqlite exports/done_export.db
  python core/export.py --json   exports/done_export.json
  python core/export.py --csv    exports/csv/
  python core/export.py --parquet exports/parquet/
  python core/export.py --all    exports/
"""

import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "core"))

from schema import get_conn, DB_PATH

# Tables exported in dependency order
EXPORT_TABLES = [
    "documents",
    "entities",
    "chunks",
    "ingest_jobs",
    "triage_queue",
    "eval_questions",
    "eval_results",
    "agent_runs",
]

# Columns to exclude from exports (internal/sensitive)
EXCLUDE_COLUMNS = {
    "documents": {"raw_text"},   # large blob, exported separately if needed
    "chunks":    {"text"},       # large, available via ChromaDB
}


# ── HELPERS ───────────────────────────────────────────────────────

def _get_rows(conn, table: str) -> tuple:
    """Return (columns, rows) for a table."""
    try:
        cursor = conn.execute(f"SELECT * FROM {table}")
        columns = [d[0] for d in cursor.description]
        rows    = cursor.fetchall()
        return columns, [dict(r) for r in rows]
    except Exception as e:
        print(f"[export] Warning: could not read {table}: {e}")
        return [], []


def _filter_columns(columns: list, rows: list, table: str) -> tuple:
    """Remove excluded columns from export."""
    excluded = EXCLUDE_COLUMNS.get(table, set())
    if not excluded:
        return columns, rows

    filtered_cols = [c for c in columns if c not in excluded]
    filtered_rows = [
        {k: v for k, v in row.items() if k not in excluded}
        for row in rows
    ]
    return filtered_cols, filtered_rows


def _export_summary(conn) -> dict:
    """Build export metadata."""
    counts = {}
    for table in EXPORT_TABLES:
        try:
            row = conn.execute(
                f"SELECT COUNT(*) as c FROM {table}"
            ).fetchone()
            counts[table] = row["c"]
        except Exception:
            counts[table] = 0

    return {
        "exported_at":  time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": 2,
        "table_counts": counts,
        "total_documents": counts.get("documents", 0),
        "total_entities":  counts.get("entities", 0),
        "total_chunks":    counts.get("chunks", 0),
    }


# ── SQLITE EXPORT ─────────────────────────────────────────────────

def export_sqlite(output_path, conn=None) -> Path:
    """
    Export a clean copy of the database as a portable SQLite file.
    This is the most complete export — includes everything.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Simple file copy for SQLite
    shutil.copy2(str(DB_PATH), str(output_path))

    # Update exported_at timestamps
    if conn:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE documents SET exported_at = ?", (now,)
        )
        conn.commit()

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"[export] SQLite → {output_path}  ({size_mb:.2f} MB)")
    return output_path


# ── JSON EXPORT ───────────────────────────────────────────────────

def export_json(output_path, conn=None) -> Path:
    """
    Export full database as structured JSON.
    Suitable for APIs, web integrations, data transfers.

    Structure:
    {
      "meta": { exported_at, schema_version, table_counts },
      "documents": [...],
      "entities": [...],
      "triage_queue": [...],
      ...
    }
    """
    if conn is None:
        conn = get_conn()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    export = {"meta": _export_summary(conn)}

    for table in EXPORT_TABLES:
        columns, rows = _get_rows(conn, table)
        _, rows = _filter_columns(columns, rows, table)
        export[table] = rows
        print(f"[export] {table:<20} {len(rows):>6} rows")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False, default=str)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"[export] JSON → {output_path}  ({size_mb:.2f} MB)")
    return output_path


# ── CSV EXPORT ────────────────────────────────────────────────────

def export_csv(output_dir, conn=None) -> Path:
    """
    Export each table as a separate CSV file.
    Suitable for Excel, basic analytics, data review.

    Output:
      output_dir/
        documents.csv
        entities.csv
        triage_queue.csv
        ...
    """
    import csv

    if conn is None:
        conn = get_conn()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for table in EXPORT_TABLES:
        columns, rows = _get_rows(conn, table)
        if not columns:
            continue

        filtered_cols, filtered_rows = _filter_columns(columns, rows, table)
        output_path = output_dir / f"{table}.csv"

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=filtered_cols)
            writer.writeheader()
            writer.writerows(filtered_rows)

        print(f"[export] {table:<20} → {output_path.name}  "
              f"({len(filtered_rows)} rows)")

    print(f"[export] CSV → {output_dir}/")
    return output_dir


# ── PARQUET EXPORT ────────────────────────────────────────────────

def export_parquet(output_dir, conn=None) -> Path:
    """
    Export each table as a Parquet file.
    Suitable for data companies, Snowflake, BigQuery, Spark.

    Requires: pip install pyarrow pandas
    """
    try:
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        print("[export] Parquet requires: pip install pyarrow pandas")
        print("[export] Run: pip install pyarrow pandas")
        return None

    if conn is None:
        conn = get_conn()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for table in EXPORT_TABLES:
        columns, rows = _get_rows(conn, table)
        if not columns or not rows:
            continue

        filtered_cols, filtered_rows = _filter_columns(columns, rows, table)
        output_path = output_dir / f"{table}.parquet"

        df    = pd.DataFrame(filtered_rows, columns=filtered_cols)
        table_pa = pa.Table.from_pandas(df)
        pq.write_table(table_pa, str(output_path), compression="snappy")

        size_kb = output_path.stat().st_size / 1024
        print(f"[export] {table:<20} → {output_path.name}  "
              f"({len(filtered_rows)} rows  {size_kb:.1f} KB)")

    print(f"[export] Parquet → {output_dir}/")
    return output_dir


# ── ENTITIES FLAT EXPORT ──────────────────────────────────────────

def export_entities_flat(output_path, conn=None) -> Path:
    """
    Special export: flat CSV of all entities with full document context.
    Most useful for downstream analytics and data licensing.

    Columns:
      entity_id, owner_id, doc_id, filename, filepath,
      category, sensitivity, entity_type, value, normalized_value,
      context, page_number, char_start, char_end, confidence,
      extraction_model, created_at
    """
    import csv

    if conn is None:
        conn = get_conn()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = conn.execute("""
        SELECT
            e.id            as entity_id,
            e.owner_id,
            e.doc_id,
            d.filename,
            d.filepath,
            d.category,
            d.sensitivity,
            e.entity_type,
            e.value,
            e.normalized_value,
            e.context,
            e.page_number,
            e.char_start,
            e.char_end,
            e.confidence,
            e.extraction_model,
            e.created_at
        FROM entities e
        JOIN documents d ON e.doc_id = d.id
        ORDER BY d.id, e.page_number, e.id
    """).fetchall()

    if not rows:
        print("[export] No entities to export")
        return output_path

    columns = [d[0] for d in rows[0].keys()] if rows else []
    columns = list(rows[0].keys())

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    size_kb = output_path.stat().st_size / 1024
    print(f"[export] Entities flat → {output_path}  "
          f"({len(rows)} rows  {size_kb:.1f} KB)")
    return output_path


# ── FULL EXPORT ───────────────────────────────────────────────────

def export_all(output_dir, conn=None) -> dict:
    """
    Run all export formats into a dated output directory.
    """
    if conn is None:
        conn = get_conn()

    output_dir  = Path(output_dir)
    dated_dir   = output_dir / time.strftime("%Y%m%d_%H%M%S")
    dated_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[export] Exporting to {dated_dir}\n")

    results = {}

    print("── SQLite ──")
    results["sqlite"] = str(export_sqlite(
        dated_dir / "done_export.db", conn
    ))

    print("\n── JSON ──")
    results["json"] = str(export_json(
        dated_dir / "done_export.json", conn
    ))

    print("\n── CSV ──")
    results["csv"] = str(export_csv(
        dated_dir / "csv", conn
    ))

    print("\n── Entities flat CSV ──")
    results["entities_flat"] = str(export_entities_flat(
        dated_dir / "csv" / "entities_flat.csv", conn
    ))

    print("\n── Parquet ──")
    parquet_result = export_parquet(dated_dir / "parquet", conn)
    results["parquet"] = str(parquet_result) if parquet_result else "skipped"

    print(f"\n[export] ✓ Complete → {dated_dir}")
    return results


# ── CLI ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="DONE export — export database in multiple formats"
    )
    p.add_argument("--sqlite",         metavar="PATH",
                   help="Export SQLite copy")
    p.add_argument("--json",           metavar="PATH",
                   help="Export JSON")
    p.add_argument("--csv",            metavar="DIR",
                   help="Export CSV files")
    p.add_argument("--parquet",        metavar="DIR",
                   help="Export Parquet files")
    p.add_argument("--entities-flat",  metavar="PATH",
                   help="Export flat entities CSV")
    p.add_argument("--all",            metavar="DIR",
                   help="Export all formats to a directory")
    args = p.parse_args()

    conn = get_conn()

    if args.sqlite:
        export_sqlite(args.sqlite, conn)
    elif args.json:
        export_json(args.json, conn)
    elif args.csv:
        export_csv(args.csv, conn)
    elif args.parquet:
        export_parquet(args.parquet, conn)
    elif args.entities_flat:
        export_entities_flat(args.entities_flat, conn)
    elif args.all:
        export_all(args.all, conn)
    else:
        p.print_help()