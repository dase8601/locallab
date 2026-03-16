"""
locallab · scripts/reenrich.py
──────────────────────────────
Re-runs enrichment (entities + questions + summary) on already-indexed documents
using the new combined single-LLM-call approach.

Does NOT re-embed or touch Qdrant — only rewrites entities, questions, and summary.

Usage:
  python scripts/reenrich.py              # all indexed docs
  python scripts/reenrich.py --limit 10   # first 10 docs
  python scripts/reenrich.py --doc-id 5   # one specific doc
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "core"))

from ingest import enrich_document, ENTITY_MODEL, DB_PATH


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def reenrich_doc(doc_id, conn):
    doc = conn.execute(
        "SELECT id, filename FROM documents WHERE id=?", (doc_id,)
    ).fetchone()
    if not doc:
        print(f"  [skip] Doc {doc_id} not found")
        return False

    filename = doc["filename"]

    # Load existing chunks from DB
    chunk_rows = conn.execute(
        "SELECT text, page_start, page_end, chunk_index FROM chunks WHERE doc_id=? ORDER BY chunk_index",
        (doc_id,)
    ).fetchall()
    if not chunk_rows:
        print(f"  [skip] {filename} — no chunks in DB")
        return False

    chunks = [
        {"text": r["text"], "page_start": r["page_start"],
         "page_end": r["page_end"], "chunk_index": r["chunk_index"]}
        for r in chunk_rows
    ]

    # Reconstruct pages from chunks (deduplicate by page number, preserve order)
    seen_pages = set()
    pages = []
    for c in chunk_rows:
        p = c["page_start"]
        if p not in seen_pages:
            seen_pages.add(p)
            pages.append((p, c["text"]))

    # Clear old entities, questions, summary
    conn.execute("DELETE FROM entities WHERE doc_id=?", (doc_id,))
    conn.execute("UPDATE documents SET questions='[]', summary='' WHERE id=?", (doc_id,))
    conn.commit()

    t0 = time.time()
    print(f"  Enriching: {filename} ({len(chunks)} chunks, {len(pages)} pages)...")
    entity_count, questions, summary = enrich_document(
        filename, chunks, pages, doc_id, conn, model=ENTITY_MODEL
    )
    elapsed = round(time.time() - t0, 1)

    # Update entity_count on document
    conn.execute("UPDATE documents SET entity_count=? WHERE id=?", (entity_count, doc_id))
    conn.commit()

    print(f"  Done in {elapsed}s — {entity_count} entities, {len(questions)} questions, {len(summary)} chars summary")
    return True


def main():
    p = argparse.ArgumentParser(description="Re-enrich existing locallab documents")
    p.add_argument("--limit",  type=int, default=0, help="Process first N docs (0 = all)")
    p.add_argument("--doc-id", type=int, default=0, help="Re-enrich a single document by ID")
    args = p.parse_args()

    conn = get_conn()

    if args.doc_id:
        doc_ids = [args.doc_id]
    else:
        query = "SELECT id FROM documents WHERE status='indexed' ORDER BY id"
        if args.limit:
            query += f" LIMIT {args.limit}"
        doc_ids = [r[0] for r in conn.execute(query).fetchall()]

    total = len(doc_ids)
    print(f"\nlocallab re-enrich — {total} document{'s' if total != 1 else ''}")
    print(f"Model: {ENTITY_MODEL}")
    print("─" * 50)

    success = 0
    for i, doc_id in enumerate(doc_ids, 1):
        print(f"\n[{i}/{total}] doc_id={doc_id}")
        if reenrich_doc(doc_id, conn):
            success += 1

    conn.close()
    print(f"\n{'═'*50}")
    print(f"Re-enriched {success}/{total} documents")
    print(f"Run eval to see score improvement:")
    print(f"  python core/eval.py --limit 10")


if __name__ == "__main__":
    main()
