"""
DONE · core/schema.py
──────────────────────
Single source of truth for the database schema.

All tables, all columns, all constraints defined here.
Nothing else should create tables directly.

Public API:
  init_db()        → create fresh database with full schema
  migrate_db()     → safely migrate existing database to latest schema
  get_conn()       → get a row_factory connection
  get_version()    → current schema version
"""

import sqlite3
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH  = BASE_DIR / "db" / "done.db"

SCHEMA_VERSION = 3


# ── SCHEMA ────────────────────────────────────────────────────────

SCHEMA = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT NOT NULL
);

-- Every document ever seen by DONE
CREATE TABLE IF NOT EXISTS documents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id          INTEGER NOT NULL DEFAULT 1,
    filename          TEXT NOT NULL,
    filepath          TEXT NOT NULL UNIQUE,
    file_type         TEXT,
    file_size         INTEGER DEFAULT 0,
    page_count        INTEGER DEFAULT 0,
    doc_hash          TEXT UNIQUE,
    language          TEXT DEFAULT 'en',

    -- Classification
    category          TEXT DEFAULT 'UNKNOWN',
    sensitivity       TEXT DEFAULT 'PUBLIC',
    quality_score     REAL DEFAULT 0.0,
    description       TEXT DEFAULT '',

    -- Triage
    triage_status     TEXT DEFAULT 'pending',
    triage_decision   TEXT DEFAULT 'pending',
    triage_at         TEXT DEFAULT '',
    triage_notes      TEXT DEFAULT '',

    -- Processing
    status            TEXT DEFAULT 'queued',
    chunk_count       INTEGER DEFAULT 0,
    entity_count      INTEGER DEFAULT 0,

    -- AI-generated metadata
    questions         TEXT DEFAULT '[]',
    summary           TEXT DEFAULT '',

    -- Provenance
    source_folder     TEXT DEFAULT '',
    date_modified     TEXT DEFAULT '',
    date_indexed      TEXT DEFAULT '',
    raw_text          TEXT DEFAULT '',

    -- Timestamps
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    exported_at       TEXT DEFAULT ''
);

-- Extracted facts with full provenance
CREATE TABLE IF NOT EXISTS entities (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id          INTEGER NOT NULL DEFAULT 1,
    doc_id            INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    entity_type       TEXT NOT NULL,
    value             TEXT NOT NULL,
    normalized_value  TEXT DEFAULT '',
    context           TEXT DEFAULT '',
    page_number       INTEGER DEFAULT 0,
    char_start        INTEGER DEFAULT -1,
    char_end          INTEGER DEFAULT -1,
    confidence        REAL DEFAULT 1.0,
    extraction_model  TEXT DEFAULT 'qwen2.5:14b',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

-- Text chunks for semantic search
CREATE TABLE IF NOT EXISTS chunks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id          INTEGER NOT NULL DEFAULT 1,
    doc_id            INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index       INTEGER NOT NULL,
    text              TEXT NOT NULL,
    page_start        INTEGER DEFAULT 0,
    page_end          INTEGER DEFAULT 0,
    chroma_id         TEXT DEFAULT '',
    created_at        TEXT NOT NULL
);

-- Processing queue
CREATE TABLE IF NOT EXISTS ingest_jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id          INTEGER NOT NULL DEFAULT 1,
    filepath          TEXT NOT NULL,
    filename          TEXT NOT NULL,
    status            TEXT DEFAULT 'pending',
    priority          INTEGER DEFAULT 2,
    page_count        INTEGER DEFAULT 0,
    file_size_mb      REAL DEFAULT 0,
    estimated_secs    INTEGER DEFAULT 0,
    progress_page     INTEGER DEFAULT 0,
    error_message     TEXT DEFAULT '',
    created_at        TEXT NOT NULL,
    started_at        TEXT DEFAULT '',
    finished_at       TEXT DEFAULT ''
);

-- Triage queue
CREATE TABLE IF NOT EXISTS triage_queue (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id          INTEGER NOT NULL DEFAULT 1,
    filepath          TEXT NOT NULL UNIQUE,
    filename          TEXT NOT NULL,
    file_type         TEXT DEFAULT '',
    file_size         INTEGER DEFAULT 0,
    page_count        INTEGER DEFAULT 0,
    estimated_secs    INTEGER DEFAULT 0,
    priority          INTEGER DEFAULT 2,

    -- Fast scan results
    description       TEXT DEFAULT '',
    category          TEXT DEFAULT 'UNKNOWN',
    sensitivity       TEXT DEFAULT 'PUBLIC',
    quality_score     REAL DEFAULT 0.0,
    sample_text       TEXT DEFAULT '',
    is_duplicate      INTEGER DEFAULT 0,
    duplicate_of      INTEGER DEFAULT 0,

    -- Decision
    decision          TEXT DEFAULT 'pending',
    decided_by        TEXT DEFAULT 'pending',
    decided_at        TEXT DEFAULT '',
    decision_notes    TEXT DEFAULT '',

    created_at        TEXT NOT NULL
);

-- Ground truth eval pairs
CREATE TABLE IF NOT EXISTS eval_questions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id          INTEGER NOT NULL DEFAULT 1,
    doc_id            INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    entity_id         INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    question          TEXT NOT NULL,
    expected_answer   TEXT NOT NULL,
    expected_source   TEXT DEFAULT '',
    entity_type       TEXT DEFAULT '',
    created_at        TEXT NOT NULL
);

-- Scored eval results
CREATE TABLE IF NOT EXISTS eval_results (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id           INTEGER REFERENCES eval_questions(id) ON DELETE CASCADE,
    actual_answer         TEXT DEFAULT '',
    actual_source         TEXT DEFAULT '',
    actual_span           TEXT DEFAULT '',
    confidence_given      REAL DEFAULT 0.0,
    entity_match_score    REAL DEFAULT 0.0,
    source_match_score    REAL DEFAULT 0.0,
    grounding_score       REAL DEFAULT 0.0,
    counterfactual_pass   INTEGER DEFAULT -1,
    verdict               TEXT DEFAULT '',
    elapsed               REAL DEFAULT 0.0,
    run_at                TEXT NOT NULL
);

-- Agent improvement loop history
CREATE TABLE IF NOT EXISTS agent_runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at                TEXT NOT NULL,
    parameter_changed     TEXT DEFAULT '',
    old_value             TEXT DEFAULT '',
    new_value             TEXT DEFAULT '',
    trust_score_before    REAL DEFAULT 0.0,
    trust_score_after     REAL DEFAULT 0.0,
    verdict               TEXT DEFAULT '',
    notes                 TEXT DEFAULT ''
);

-- Named conversation sessions
CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL DEFAULT 'New conversation',
    mode          TEXT    NOT NULL DEFAULT 'docs',
    model         TEXT    NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);

-- Individual messages within a conversation
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT    NOT NULL CHECK(role IN ('user','assistant')),
    content         TEXT    NOT NULL,
    source_file     TEXT    DEFAULT '',
    confidence      REAL    DEFAULT NULL,
    mode            TEXT    DEFAULT 'docs',
    created_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conv         ON messages(conversation_id, id ASC);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_documents_owner     ON documents(owner_id);
CREATE INDEX IF NOT EXISTS idx_documents_category  ON documents(category);
CREATE INDEX IF NOT EXISTS idx_documents_status    ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_triage    ON documents(triage_status);
CREATE INDEX IF NOT EXISTS idx_documents_hash      ON documents(doc_hash);
CREATE INDEX IF NOT EXISTS idx_entities_owner      ON entities(owner_id);
CREATE INDEX IF NOT EXISTS idx_entities_doc        ON entities(doc_id);
CREATE INDEX IF NOT EXISTS idx_entities_type       ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_value      ON entities(value);
CREATE INDEX IF NOT EXISTS idx_chunks_doc          ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status  ON ingest_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_priority ON ingest_jobs(priority, status);
CREATE INDEX IF NOT EXISTS idx_triage_decision     ON triage_queue(decision);
CREATE INDEX IF NOT EXISTS idx_triage_owner        ON triage_queue(owner_id);
"""


# ── MIGRATION ─────────────────────────────────────────────────────

def _get_existing_columns(conn, table):
    """Return set of column names for an existing table."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row[1] for row in rows}
    except Exception:
        return set()


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)
    ).fetchone()
    return row is not None


def migrate_db(conn):
    """
    Safely migrate an existing database to the current schema.
    - Adds missing columns to existing tables
    - Creates missing tables
    - Migrates data from old column names
    - Never drops columns or tables (non-destructive)
    - Preserves all existing data
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    print("[schema] Running migration...")

    # ── documents ────────────────────────────────────────────────
    if _table_exists(conn, "documents"):
        cols = _get_existing_columns(conn, "documents")

        new_cols = {
            "owner_id":       "INTEGER NOT NULL DEFAULT 1",
            "language":       "TEXT DEFAULT 'en'",
            "category":       "TEXT DEFAULT 'UNKNOWN'",
            "sensitivity":    "TEXT DEFAULT 'PUBLIC'",
            "quality_score":  "REAL DEFAULT 0.0",
            "description":    "TEXT DEFAULT ''",
            "triage_status":  "TEXT DEFAULT 'pending'",
            "triage_decision":"TEXT DEFAULT 'pending'",
            "triage_at":      "TEXT DEFAULT ''",
            "triage_notes":   "TEXT DEFAULT ''",
            "source_folder":  "TEXT DEFAULT ''",
            "created_at":     f"TEXT NOT NULL DEFAULT '{now}'",
            "updated_at":     f"TEXT NOT NULL DEFAULT '{now}'",
            "exported_at":    "TEXT DEFAULT ''",
            "questions":      "TEXT DEFAULT '[]'",
            "summary":        "TEXT DEFAULT ''",
            "tags":           "TEXT DEFAULT ''",
        }

        for col, definition in new_cols.items():
            if col not in cols:
                try:
                    conn.execute(
                        f"ALTER TABLE documents ADD COLUMN {col} {definition}"
                    )
                    print(f"  [documents] + {col}")
                except Exception as e:
                    print(f"  [documents] skip {col}: {e}")

        # Migrate date_indexed → created_at if needed
        if "date_indexed" in cols and "created_at" in cols:
            conn.execute("""
                UPDATE documents
                SET created_at = date_indexed,
                    updated_at = date_indexed
                WHERE created_at = '' OR created_at IS NULL
            """)

        # Mark all existing docs as auto-approved
        # (they were indexed before triage existed)
        conn.execute("""
            UPDATE documents
            SET triage_status   = 'auto_approved',
                triage_decision = 'auto',
                triage_at       = ?
            WHERE triage_status = 'pending'
              AND status        = 'indexed'
        """, (now,))

    # ── entities ─────────────────────────────────────────────────
    if _table_exists(conn, "entities"):
        cols = _get_existing_columns(conn, "entities")

        new_cols = {
            "owner_id":         "INTEGER NOT NULL DEFAULT 1",
            "normalized_value": "TEXT DEFAULT ''",
            "char_start":       "INTEGER DEFAULT -1",
            "char_end":         "INTEGER DEFAULT -1",
            "extraction_model": "TEXT DEFAULT 'qwen2.5:14b'",
            "updated_at":       f"TEXT NOT NULL DEFAULT '{now}'",
        }

        # created_at may exist as a different name
        if "created_at" not in cols:
            new_cols["created_at"] = f"TEXT NOT NULL DEFAULT '{now}'"

        for col, definition in new_cols.items():
            if col not in cols:
                try:
                    conn.execute(
                        f"ALTER TABLE entities ADD COLUMN {col} {definition}"
                    )
                    print(f"  [entities] + {col}")
                except Exception as e:
                    print(f"  [entities] skip {col}: {e}")

    # ── chunks ───────────────────────────────────────────────────
    if _table_exists(conn, "chunks"):
        cols = _get_existing_columns(conn, "chunks")

        new_cols = {
            "owner_id":   "INTEGER NOT NULL DEFAULT 1",
            "created_at": f"TEXT NOT NULL DEFAULT '{now}'",
        }

        for col, definition in new_cols.items():
            if col not in cols:
                try:
                    conn.execute(
                        f"ALTER TABLE chunks ADD COLUMN {col} {definition}"
                    )
                    print(f"  [chunks] + {col}")
                except Exception as e:
                    print(f"  [chunks] skip {col}: {e}")

    # ── ingest_jobs ──────────────────────────────────────────────
    if _table_exists(conn, "ingest_jobs"):
        cols = _get_existing_columns(conn, "ingest_jobs")
        if "owner_id" not in cols:
            try:
                conn.execute(
                    "ALTER TABLE ingest_jobs ADD COLUMN "
                    "owner_id INTEGER NOT NULL DEFAULT 1"
                )
                print("  [ingest_jobs] + owner_id")
            except Exception as e:
                print(f"  [ingest_jobs] skip owner_id: {e}")

        # Cancel any stuck pending jobs from before
        conn.execute("""
            UPDATE ingest_jobs
            SET status = 'cancelled'
            WHERE status IN ('pending', 'processing')
        """)
        print("  [ingest_jobs] cancelled stuck jobs")

    # ── create new tables if missing ─────────────────────────────
    conn.executescript(SCHEMA)

    # ── record version ───────────────────────────────────────────
    conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, now)
    )
    conn.commit()
    print(f"[schema] Migration complete → version {SCHEMA_VERSION}")


# ── PUBLIC API ────────────────────────────────────────────────────

def init_db():
    """
    Create database with full schema if it doesn't exist.
    Migrate if it does exist.
    Always returns a ready connection.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Enable WAL mode for better concurrent read/write performance
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    if not _table_exists(conn, "schema_version"):
        # Fresh database or pre-versioned database
        if _table_exists(conn, "documents"):
            # Existing pre-versioned database — migrate
            print("[schema] Existing database detected — migrating...")
            migrate_db(conn)
        else:
            # Brand new database
            conn.executescript(SCHEMA)
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, now)
            )
            conn.commit()
            print(f"[schema] Fresh database created → version {SCHEMA_VERSION}")
    else:
        current = get_version(conn)
        if current < SCHEMA_VERSION:
            migrate_db(conn)

    return conn


def get_conn():
    """Get a connection to the existing database."""
    if not DB_PATH.exists():
        return init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_version(conn=None):
    """Return current schema version."""
    if conn is None:
        conn = get_conn()
    try:
        row = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row["version"] if row else 0
    except Exception:
        return 0


def db_stats(conn=None):
    """Return summary stats about the database contents."""
    if conn is None:
        conn = get_conn()

    stats = {}

    tables = [
        "documents", "entities", "chunks",
        "ingest_jobs", "triage_queue",
        "eval_questions", "eval_results", "agent_runs"
    ]

    for t in tables:
        try:
            row = conn.execute(f"SELECT COUNT(*) as c FROM {t}").fetchone()
            stats[t] = row["c"]
        except Exception:
            stats[t] = 0

    # Extra useful stats
    try:
        stats["indexed_docs"] = conn.execute(
            "SELECT COUNT(*) as c FROM documents WHERE status='indexed'"
        ).fetchone()["c"]

        stats["pending_triage"] = conn.execute(
            "SELECT COUNT(*) as c FROM triage_queue WHERE decision='pending'"
        ).fetchone()["c"]

        stats["total_entities_by_type"] = {
            r["entity_type"]: r["c"]
            for r in conn.execute(
                "SELECT entity_type, COUNT(*) as c FROM entities "
                "GROUP BY entity_type ORDER BY c DESC"
            ).fetchall()
        }

        stats["docs_by_category"] = {
            r["category"]: r["c"]
            for r in conn.execute(
                "SELECT category, COUNT(*) as c FROM documents "
                "GROUP BY category ORDER BY c DESC"
            ).fetchall()
        }

    except Exception:
        pass

    return stats


# ── CLI ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    p = argparse.ArgumentParser(description="DONE schema — database management")
    p.add_argument("--init",    action="store_true", help="Initialize/migrate database")
    p.add_argument("--stats",   action="store_true", help="Show database stats")
    p.add_argument("--version", action="store_true", help="Show schema version")
    args = p.parse_args()

    if args.init:
        conn = init_db()
        print(f"[schema] Database ready at {DB_PATH}")
        conn.close()

    elif args.stats:
        conn = get_conn()
        stats = db_stats(conn)
        conn.close()
        print(f"\n── DONE Database Stats ──")
        print(f"  Version:        {get_version()}")
        print(f"  Documents:      {stats.get('documents', 0)}")
        print(f"  Indexed:        {stats.get('indexed_docs', 0)}")
        print(f"  Entities:       {stats.get('entities', 0)}")
        print(f"  Chunks:         {stats.get('chunks', 0)}")
        print(f"  Pending triage: {stats.get('pending_triage', 0)}")
        print(f"\n  Entities by type:")
        for t, c in stats.get("total_entities_by_type", {}).items():
            print(f"    {t:<15} {c}")
        print(f"\n  Docs by category:")
        for cat, c in stats.get("docs_by_category", {}).items():
            print(f"    {cat:<15} {c}")

    elif args.version:
        print(f"[schema] Version: {get_version()}")

    else:
        p.print_args()