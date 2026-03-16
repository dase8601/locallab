"""
Integration tests for Flask API endpoints.
Uses Flask test client — no Ollama or Qdrant required.

Response shape: ok() returns {**data, "success": True} — no "data" wrapper.
"""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "ui"))


# ── Schema + seed ─────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL DEFAULT 1,
    filename TEXT NOT NULL, filepath TEXT NOT NULL UNIQUE,
    file_type TEXT, file_size INTEGER DEFAULT 0, page_count INTEGER DEFAULT 0,
    doc_hash TEXT UNIQUE, language TEXT DEFAULT 'en',
    category TEXT DEFAULT 'UNKNOWN', sensitivity TEXT DEFAULT 'PUBLIC',
    quality_score REAL DEFAULT 0.0, description TEXT DEFAULT '',
    triage_status TEXT DEFAULT 'pending', triage_decision TEXT DEFAULT 'pending',
    triage_at TEXT DEFAULT '', triage_notes TEXT DEFAULT '',
    status TEXT DEFAULT 'queued', chunk_count INTEGER DEFAULT 0,
    entity_count INTEGER DEFAULT 0, source_folder TEXT DEFAULT '',
    date_modified TEXT DEFAULT '', date_indexed TEXT DEFAULT '',
    raw_text TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    exported_at TEXT DEFAULT '', questions TEXT DEFAULT '[]',
    summary TEXT DEFAULT '', tags TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL DEFAULT 1,
    doc_id INTEGER NOT NULL, entity_type TEXT NOT NULL,
    value TEXT NOT NULL, normalized_value TEXT DEFAULT '',
    context TEXT DEFAULT '', page_number INTEGER DEFAULT 0,
    char_start INTEGER DEFAULT -1, char_end INTEGER DEFAULT -1,
    confidence REAL DEFAULT 1.0, extraction_model TEXT DEFAULT 'test',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL DEFAULT 1,
    doc_id INTEGER NOT NULL, chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL, page_start INTEGER DEFAULT 0, page_end INTEGER DEFAULT 0,
    chroma_id TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingest_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL DEFAULT 1,
    filepath TEXT NOT NULL, filename TEXT NOT NULL,
    status TEXT DEFAULT 'pending', priority INTEGER DEFAULT 2,
    page_count INTEGER DEFAULT 0, file_size_mb REAL DEFAULT 0,
    estimated_secs INTEGER DEFAULT 0, progress_page INTEGER DEFAULT 0,
    error_message TEXT DEFAULT '', created_at TEXT NOT NULL,
    started_at TEXT DEFAULT '', finished_at TEXT DEFAULT '',
    source TEXT DEFAULT 'upload'
);
CREATE TABLE IF NOT EXISTS whats_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER,
    filename TEXT NOT NULL, summary TEXT NOT NULL,
    created_at TEXT NOT NULL, read INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS query_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT, answer TEXT, source_file TEXT,
    confidence REAL, thumbs TEXT CHECK(thumbs IN ('up','down')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL DEFAULT 1,
    doc_id INTEGER, entity_id INTEGER, question TEXT NOT NULL,
    expected_answer TEXT NOT NULL, expected_source TEXT DEFAULT '',
    entity_type TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT, question_id INTEGER,
    actual_answer TEXT DEFAULT '', actual_source TEXT DEFAULT '',
    actual_span TEXT DEFAULT '', confidence_given REAL DEFAULT 0.0,
    entity_match_score REAL DEFAULT 0.0, source_match_score REAL DEFAULT 0.0,
    grounding_score REAL DEFAULT 0.0, counterfactual_pass INTEGER DEFAULT -1,
    verdict TEXT DEFAULT '', elapsed REAL DEFAULT 0.0, run_at TEXT NOT NULL
);
"""


def _seed(conn):
    now = "2026-01-01T00:00:00Z"
    conn.execute("""
        INSERT INTO documents (id, filename, filepath, file_type, status, page_count,
                               summary, questions, tags, created_at, updated_at)
        VALUES (1, 'acme_contract.pdf', '/uploads/acme_contract.pdf', 'pdf', 'indexed', 5,
                'Service agreement between Acme Corp and Widget Inc.',
                '["What are the payment terms?"]', '["legal"]', ?, ?)
    """, (now, now))
    conn.execute("""
        INSERT INTO entities (doc_id, entity_type, value, context, created_at, updated_at)
        VALUES (1, 'ORG', 'Acme Corp', 'Client in this contract.', ?, ?)
    """, (now, now))
    conn.execute("""
        INSERT INTO ingest_jobs (filepath, filename, status, priority, created_at)
        VALUES ('/uploads/acme_contract.pdf', 'acme_contract.pdf', 'done', 2, ?)
    """, (now,))
    conn.commit()


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test_api.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _seed(conn)
    conn.close()

    def _get_conn():
        c = sqlite3.connect(str(db_path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    with patch("threading.Thread"), \
         patch("ui.app.init_db", return_value=sqlite3.connect(str(db_path))), \
         patch("ui.app._reset_stale_jobs"), \
         patch("ui.app._init_whats_new"), \
         patch("ui.app._start_watch_folders"):

        import ui.app as flask_app
        flask_app.get_conn = _get_conn
        flask_app.app.config["TESTING"] = True
        with flask_app.app.test_client() as c:
            yield c


def _j(r):
    """Decode JSON response."""
    return json.loads(r.data)


# ── Health ─────────────────────────────────────────────────────────

def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = _j(r)
    assert data["success"] is True
    assert data["status"] == "ok"


# ── Files ──────────────────────────────────────────────────────────

def test_files_returns_list(client):
    r = client.get("/api/files")
    assert r.status_code == 200
    data = _j(r)
    assert data["success"] is True
    docs = data["documents"]
    assert len(docs) >= 1
    assert docs[0]["filename"] == "acme_contract.pdf"


def test_files_has_summary(client):
    r = client.get("/api/files")
    docs = _j(r)["documents"]
    doc = docs[0]
    assert "summary" in doc
    assert isinstance(doc["summary"], str)


# ── Ingest status ──────────────────────────────────────────────────

def test_ingest_status_returns_jobs(client):
    r = client.get("/api/ingest/status")
    assert r.status_code == 200
    data = _j(r)
    assert data["success"] is True
    assert "done" in data
    assert len(data["done"]) >= 1


# ── Insights ───────────────────────────────────────────────────────

def test_insights_returns_stats(client):
    r = client.get("/api/insights")
    assert r.status_code == 200
    data = _j(r)
    assert data["success"] is True
    assert data["total_docs"] >= 1
    assert "entity_dist" in data  # actual field name


# ── Explore ────────────────────────────────────────────────────────

def test_explore_entities(client):
    r = client.get("/api/explore/entities")
    assert r.status_code == 200
    data = _j(r)
    assert data["success"] is True
    assert "entities" in data
    assert len(data["entities"]) >= 1


def test_explore_entities_filter_by_type(client):
    r = client.get("/api/explore/entities?type=ORG")
    assert r.status_code == 200
    entities = _j(r)["entities"]
    for e in entities:
        assert e["entity_type"] == "ORG"


def test_explore_entities_search(client):
    r = client.get("/api/explore/entities?q=Acme")
    assert r.status_code == 200
    entities = _j(r)["entities"]
    assert any("Acme" in e["value"] for e in entities)


# ── What's new ─────────────────────────────────────────────────────

def test_whats_new_empty(client):
    r = client.get("/api/whats-new")
    assert r.status_code == 200
    notifications = _j(r)["notifications"]
    assert isinstance(notifications, list)


def test_whats_new_shows_unread(client):
    import ui.app as flask_app
    conn = flask_app.get_conn()
    conn.execute("""
        INSERT INTO whats_new (filename, summary, created_at, read)
        VALUES ('new_doc.pdf', 'A new document was indexed.', '2026-01-02T00:00:00Z', 0)
    """)
    conn.commit()
    conn.close()

    r = client.get("/api/whats-new")
    notifications = _j(r)["notifications"]
    assert any(n["filename"] == "new_doc.pdf" for n in notifications)


def test_whats_new_dismiss(client):
    import ui.app as flask_app
    conn = flask_app.get_conn()
    conn.execute("""
        INSERT INTO whats_new (filename, summary, created_at, read)
        VALUES ('another.pdf', 'Another summary.', '2026-01-02T00:00:00Z', 0)
    """)
    conn.commit()
    conn.close()

    r = client.post("/api/whats-new/dismiss")
    assert r.status_code == 200
    assert _j(r)["dismissed"] is True

    r = client.get("/api/whats-new")
    assert _j(r)["notifications"] == []


# ── Feedback ───────────────────────────────────────────────────────

def test_feedback_submit_up(client):
    r = client.post("/api/feedback", json={
        "thumbs": "up",
        "question": "What are the payment terms?",
        "answer": "Net 30.",
        "source_file": "acme_contract.pdf",
        "confidence": 0.85,
    })
    assert r.status_code == 200
    assert _j(r)["success"] is True


def test_feedback_rejects_invalid_thumbs(client):
    r = client.post("/api/feedback", json={"thumbs": "sideways"})
    assert r.status_code in (400, 422, 500)


# ── Delete document ────────────────────────────────────────────────

def test_delete_nonexistent_doc_returns_404(client):
    # QdrantClient is imported inside the delete function, patch it there
    with patch("qdrant_client.QdrantClient"):
        r = client.delete("/api/files/9999")
    assert r.status_code == 404
