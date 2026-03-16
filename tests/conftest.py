"""
Shared pytest fixtures for locallab tests.

All tests run without Ollama or Qdrant — external calls are mocked.
A temporary SQLite database is seeded with realistic fixture data.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make core/ and ui/ importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "ui"))

# ── SQLite schema bootstrap ────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 1,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL UNIQUE,
    file_type TEXT,
    file_size INTEGER DEFAULT 0,
    page_count INTEGER DEFAULT 0,
    doc_hash TEXT UNIQUE,
    language TEXT DEFAULT 'en',
    category TEXT DEFAULT 'UNKNOWN',
    sensitivity TEXT DEFAULT 'PUBLIC',
    quality_score REAL DEFAULT 0.0,
    description TEXT DEFAULT '',
    triage_status TEXT DEFAULT 'pending',
    triage_decision TEXT DEFAULT 'pending',
    triage_at TEXT DEFAULT '',
    triage_notes TEXT DEFAULT '',
    status TEXT DEFAULT 'queued',
    chunk_count INTEGER DEFAULT 0,
    entity_count INTEGER DEFAULT 0,
    source_folder TEXT DEFAULT '',
    date_modified TEXT DEFAULT '',
    date_indexed TEXT DEFAULT '',
    raw_text TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    exported_at TEXT DEFAULT '',
    questions TEXT DEFAULT '[]',
    summary TEXT DEFAULT '',
    tags TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 1,
    doc_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL,
    value TEXT NOT NULL,
    normalized_value TEXT DEFAULT '',
    context TEXT DEFAULT '',
    page_number INTEGER DEFAULT 0,
    char_start INTEGER DEFAULT -1,
    char_end INTEGER DEFAULT -1,
    confidence REAL DEFAULT 1.0,
    extraction_model TEXT DEFAULT 'test',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 1,
    doc_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    page_start INTEGER DEFAULT 0,
    page_end INTEGER DEFAULT 0,
    chroma_id TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingest_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 1,
    filepath TEXT NOT NULL,
    filename TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    priority INTEGER DEFAULT 2,
    page_count INTEGER DEFAULT 0,
    file_size_mb REAL DEFAULT 0,
    estimated_secs INTEGER DEFAULT 0,
    progress_page INTEGER DEFAULT 0,
    error_message TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT DEFAULT '',
    finished_at TEXT DEFAULT '',
    source TEXT DEFAULT 'upload'
);
CREATE TABLE IF NOT EXISTS whats_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER,
    filename TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS query_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT,
    answer TEXT,
    source_file TEXT,
    confidence REAL,
    thumbs TEXT CHECK(thumbs IN ('up','down')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 1,
    doc_id INTEGER,
    entity_id INTEGER,
    question TEXT NOT NULL,
    expected_answer TEXT NOT NULL,
    expected_source TEXT DEFAULT '',
    entity_type TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER,
    actual_answer TEXT DEFAULT '',
    actual_source TEXT DEFAULT '',
    actual_span TEXT DEFAULT '',
    confidence_given REAL DEFAULT 0.0,
    entity_match_score REAL DEFAULT 0.0,
    source_match_score REAL DEFAULT 0.0,
    grounding_score REAL DEFAULT 0.0,
    counterfactual_pass INTEGER DEFAULT -1,
    verdict TEXT DEFAULT '',
    elapsed REAL DEFAULT 0.0,
    run_at TEXT NOT NULL
);
"""


def _seed_db(conn):
    """Insert realistic fixture documents, chunks, and entities."""
    now = "2026-01-01T00:00:00Z"
    # Two documents
    conn.execute("""
        INSERT INTO documents (id, filename, filepath, file_type, status, page_count,
                               summary, questions, created_at, updated_at)
        VALUES (1, 'acme_contract.pdf', '/uploads/acme_contract.pdf', 'pdf', 'indexed', 5,
                'Service agreement between Acme Corp and Widget Inc for software development.',
                '["What are the payment terms?","Who are the parties?"]', ?, ?)
    """, (now, now))
    conn.execute("""
        INSERT INTO documents (id, filename, filepath, file_type, status, page_count,
                               summary, questions, created_at, updated_at)
        VALUES (2, 'dallas_resume.pdf', '/uploads/dallas_resume.pdf', 'pdf', 'indexed', 2,
                'Resume of Dallas Sellers, software engineer with 5 years experience.',
                '["What are Dallas skills?","Where did Dallas work?"]', ?, ?)
    """, (now, now))
    # Chunks
    conn.executemany("""
        INSERT INTO chunks (doc_id, chunk_index, text, page_start, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, [
        (1, 0, "Payment terms: Net 30. Acme Corp shall pay Widget Inc within 30 days of invoice.", 1, now),
        (1, 1, "This agreement is entered into between Acme Corp and Widget Inc on January 1, 2026.", 1, now),
        (2, 0, "Dallas Sellers — Software Engineer. Skills: Python, Flask, SQL, React.", 1, now),
        (2, 1, "Work experience: Senior Engineer at TechCorp (2022-2024). Engineer at StartupXYZ (2020-2022).", 2, now),
    ])
    # Entities
    conn.executemany("""
        INSERT INTO entities (doc_id, entity_type, value, context, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [
        (1, "ORG", "Acme Corp", "Acme Corp is the client in this contract.", now, now),
        (1, "ORG", "Widget Inc", "Widget Inc is the service provider.", now, now),
        (1, "DATE", "January 1, 2026", "Agreement date.", now, now),
        (2, "PERSON", "Dallas Sellers", "Resume owner.", now, now),
        (2, "SKILL", "Python", "Programming language.", now, now),
    ])
    conn.commit()


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite database seeded with fixture data."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    _seed_db(conn)
    conn.close()
    return db_path


@pytest.fixture
def db_conn(tmp_db):
    """Open connection to the seeded test DB."""
    conn = sqlite3.connect(str(tmp_db))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def app_client(tmp_db, tmp_path, monkeypatch):
    """Flask test client with isolated DB and mocked ingest worker."""
    # Point app to temp DB
    monkeypatch.setenv("LOCALLAB_DB", str(tmp_db))

    # Patch heavy startup operations before import
    with patch("threading.Thread"), \
         patch("ui.app.init_db", return_value=sqlite3.connect(str(tmp_db))), \
         patch("ui.app._reset_stale_jobs"), \
         patch("ui.app._init_whats_new"), \
         patch("ui.app._start_watch_folders"):

        # Patch DB path inside app
        import ui.app as flask_app
        monkeypatch.setattr(flask_app, "get_conn",
                            lambda: _patched_conn(str(tmp_db)))

        flask_app.app.config["TESTING"] = True
        flask_app.app.config["WTF_CSRF_ENABLED"] = False
        with flask_app.app.test_client() as client:
            yield client


def _patched_conn(db_path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
