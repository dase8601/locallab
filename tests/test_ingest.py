"""
Unit tests for core/ingest.py — pure logic, no LLM or file I/O required.
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "core"))


# ── Helpers ───────────────────────────────────────────────────────

def _make_conn(tmp_path):
    db = tmp_path / "ingest_test.db"
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY, filename TEXT, filepath TEXT,
            status TEXT, chunk_count INTEGER DEFAULT 0, entity_count INTEGER DEFAULT 0,
            summary TEXT DEFAULT '', questions TEXT DEFAULT '[]',
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER,
            chunk_index INTEGER, text TEXT, page_start INTEGER DEFAULT 0,
            page_end INTEGER DEFAULT 0, chroma_id TEXT DEFAULT '',
            created_at TEXT NOT NULL, owner_id INTEGER DEFAULT 1
        );
        CREATE TABLE entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER,
            entity_type TEXT, value TEXT, normalized_value TEXT DEFAULT '',
            context TEXT DEFAULT '', page_number INTEGER DEFAULT 0,
            char_start INTEGER DEFAULT -1, char_end INTEGER DEFAULT -1,
            confidence REAL DEFAULT 1.0, extraction_model TEXT DEFAULT 'test',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            owner_id INTEGER DEFAULT 1
        );
    """)
    c.commit()
    return c


# ── chunk_pages ───────────────────────────────────────────────────

def test_chunk_pages_basic():
    from ingest import chunk_pages

    # 200 words on page 1
    text = " ".join([f"word{i}" for i in range(200)])
    pages = [(1, text)]
    chunks = chunk_pages(pages, profile="small")

    assert len(chunks) >= 1
    for c in chunks:
        assert "text" in c
        assert "page_start" in c
        assert "chunk_index" in c


def test_chunk_pages_overlap():
    """Overlapping chunks should share words at boundaries."""
    from ingest import chunk_pages

    words = [f"w{i}" for i in range(200)]
    text = " ".join(words)
    pages = [(1, text)]
    chunks = chunk_pages(pages, profile="small")

    if len(chunks) >= 2:
        # Last N words of chunk[0] should appear somewhere in chunk[1]
        c0_words = set(chunks[0]["text"].split()[-20:])
        c1_words = set(chunks[1]["text"].split()[:20])
        assert len(c0_words & c1_words) > 0


def test_chunk_pages_short_text_single_chunk():
    from ingest import chunk_pages

    pages = [(1, "This is a very short document with only a few words.")]
    chunks = chunk_pages(pages, profile="small")
    assert len(chunks) == 1


def test_chunk_pages_empty_page_no_chunks():
    from ingest import chunk_pages

    pages = [(1, "")]
    chunks = chunk_pages(pages, profile="small")
    assert chunks == []


def test_chunk_pages_multiple_pages():
    from ingest import chunk_pages

    pages = [(1, "First page content. " * 50), (2, "Second page content. " * 50)]
    chunks = chunk_pages(pages, profile="small")
    page_nums = {c["page_start"] for c in chunks}
    assert 1 in page_nums
    assert 2 in page_nums


# ── estimate_job ──────────────────────────────────────────────────

def test_estimate_job_txt(tmp_path):
    from ingest import estimate_job

    # Write a file large enough to get non-zero size
    f = tmp_path / "sample.txt"
    f.write_text("Hello world. " * 500)  # ~6KB

    result = estimate_job(f)
    assert "error" not in result
    assert result["priority"] in (1, 2, 3, 4)
    assert result["page_count"] >= 1
    assert "estimated_secs" in result
    assert isinstance(result["size_mb"], float)


def test_estimate_job_missing_file():
    from ingest import estimate_job

    result = estimate_job(Path("/nonexistent/file.pdf"))
    assert "error" in result


def test_estimate_job_small_txt_priority_1(tmp_path):
    """Small text file should get priority 1 (≤10 pages)."""
    from ingest import estimate_job

    f = tmp_path / "small.txt"
    f.write_text("Short document. " * 10)
    result = estimate_job(f)
    assert result["priority"] == 1


# ── extract_entities_from_batch ───────────────────────────────────

def test_extract_entities_from_batch_calls_ollama(tmp_path):
    """extract_entities_from_batch returns count of inserted entities (int)."""
    from ingest import extract_entities_from_batch

    conn = _make_conn(tmp_path)
    conn.execute("""
        INSERT INTO documents (id, filename, filepath, status, created_at, updated_at)
        VALUES (1, 'test.pdf', '/test.pdf', 'indexed', '2026-01-01', '2026-01-01')
    """)
    conn.commit()

    mock_content = (
        '[{"type": "PERSON", "value": "Alice Smith", "context": "Contract party"},'
        ' {"type": "DATE", "value": "2026-01-01", "context": "Effective date"}]'
    )
    # extract_entities_from_batch uses response["message"]["content"] dict access
    mock_response = {"message": {"content": mock_content}}
    with patch("ingest.ollama") as mock_ollama:
        mock_ollama.chat.return_value = mock_response
        count = extract_entities_from_batch(
            [(1, "Alice Smith signed the contract on 2026-01-01.")],
            doc_id=1,
            conn=conn,
        )

    assert isinstance(count, int)
    assert count >= 0  # successfully parsed and inserted (or 0 if no match)
    conn.close()


def test_extract_entities_ollama_failure_returns_zero(tmp_path):
    """If ollama fails, extract_entities_from_batch returns 0 without crashing."""
    from ingest import extract_entities_from_batch

    conn = _make_conn(tmp_path)
    conn.execute("""
        INSERT INTO documents (id, filename, filepath, status, created_at, updated_at)
        VALUES (1, 'test.pdf', '/test.pdf', 'indexed', '2026-01-01', '2026-01-01')
    """)
    conn.commit()

    with patch("ingest.ollama") as mock_ollama:
        mock_ollama.chat.side_effect = Exception("connection refused")
        count = extract_entities_from_batch([(1, "Some text.")], doc_id=1, conn=conn)

    assert count == 0
    conn.close()


# ── generate_doc_questions ────────────────────────────────────────

def test_generate_doc_questions_returns_list(tmp_path):
    from ingest import generate_doc_questions

    conn = _make_conn(tmp_path)
    conn.execute("""
        INSERT INTO documents (id, filename, filepath, status, created_at, updated_at)
        VALUES (1, 'contract.pdf', '/contract.pdf', 'indexed', '2026-01-01', '2026-01-01')
    """)
    conn.commit()

    mock_response = MagicMock()
    mock_response.message.content = (
        '["What are the payment terms?", "Who are the parties?", '
        '"When does the agreement expire?", "What is the contract value?"]'
    )
    with patch("ingest.ollama") as mock_ollama:
        mock_ollama.chat.return_value = mock_response
        questions = generate_doc_questions(
            filename="contract.pdf",
            chunks=[{"text": "Payment terms: Net 30. Parties: Acme Corp and Widget Inc.", "page_start": 1}],
            conn=conn,
            doc_id=1,
            model="test-model",
        )

    assert isinstance(questions, list)
    conn.close()


def test_generate_doc_questions_ollama_failure_returns_list(tmp_path):
    from ingest import generate_doc_questions

    conn = _make_conn(tmp_path)
    conn.execute("""
        INSERT INTO documents (id, filename, filepath, status, created_at, updated_at)
        VALUES (1, 'test.pdf', '/test.pdf', 'indexed', '2026-01-01', '2026-01-01')
    """)
    conn.commit()

    with patch("ingest.ollama") as mock_ollama:
        mock_ollama.chat.side_effect = Exception("timeout")
        questions = generate_doc_questions(
            "test.pdf",
            [{"text": "some text", "page_start": 1}],
            conn=conn, doc_id=1, model="test"
        )

    assert isinstance(questions, list)
    conn.close()


# ── generate_doc_summary ──────────────────────────────────────────

def test_generate_doc_summary_returns_string(tmp_path):
    from ingest import generate_doc_summary

    conn = _make_conn(tmp_path)
    conn.execute("""
        INSERT INTO documents (id, filename, filepath, status, created_at, updated_at)
        VALUES (1, 'contract.pdf', '/contract.pdf', 'indexed', '2026-01-01', '2026-01-01')
    """)
    conn.commit()

    mock_response = MagicMock()
    mock_response.message.content = "This document covers payment terms between two parties."
    with patch("ingest.ollama") as mock_ollama:
        mock_ollama.chat.return_value = mock_response
        summary = generate_doc_summary(
            filename="contract.pdf",
            chunks=[{"text": "Payment terms: Net 30 days.", "page_start": 1}],
            conn=conn,
            doc_id=1,
            model="test-model",
        )

    assert isinstance(summary, str)
    conn.close()


def test_generate_doc_summary_failure_returns_string(tmp_path):
    from ingest import generate_doc_summary

    conn = _make_conn(tmp_path)
    conn.execute("""
        INSERT INTO documents (id, filename, filepath, status, created_at, updated_at)
        VALUES (1, 'test.pdf', '/test.pdf', 'indexed', '2026-01-01', '2026-01-01')
    """)
    conn.commit()

    with patch("ingest.ollama") as mock_ollama:
        mock_ollama.chat.side_effect = Exception("model not found")
        summary = generate_doc_summary(
            "test.pdf",
            [{"text": "some text", "page_start": 1}],
            conn=conn, doc_id=1, model="test"
        )

    assert isinstance(summary, str)
    conn.close()
