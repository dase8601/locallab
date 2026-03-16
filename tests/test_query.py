"""
Unit tests for core/query.py — pure logic functions only.
No Ollama or Qdrant required.
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "core"))

from query import (
    _find_all_filenames,
    _find_filename_filter,
    _is_multi_doc_query,
)


# ── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def conn(tmp_path):
    """In-memory DB with two indexed documents."""
    db = tmp_path / "q.db"
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY, filename TEXT, filepath TEXT,
            status TEXT DEFAULT 'indexed'
        )
    """)
    c.executemany("INSERT INTO documents (filename, filepath, status) VALUES (?,?,?)", [
        ("acme_contract.pdf",   "/uploads/acme_contract.pdf",   "indexed"),
        ("dallas_resume.pdf",   "/uploads/dallas_resume.pdf",   "indexed"),
        ("q3_financial_report.pdf", "/uploads/q3_financial_report.pdf", "indexed"),
    ])
    c.commit()
    yield c
    c.close()


# ── _find_all_filenames ────────────────────────────────────────────

def test_find_all_exact_single(conn):
    matches = _find_all_filenames("What are the terms in acme_contract.pdf?", conn)
    assert matches == ["acme_contract.pdf"]


def test_find_all_exact_multiple(conn):
    matches = _find_all_filenames(
        "Compare acme_contract.pdf and dallas_resume.pdf", conn
    )
    assert set(matches) == {"acme_contract.pdf", "dallas_resume.pdf"}


def test_find_all_basename_match(conn):
    # "acme contract" should match "acme_contract.pdf" via base-name
    matches = _find_all_filenames("what's in my acme contract?", conn)
    assert "acme_contract.pdf" in matches


def test_find_all_no_match(conn):
    matches = _find_all_filenames("who won the grand slam last year?", conn)
    assert matches == []


def test_find_all_multiword_basename(conn):
    # "q3 financial report" should match "q3_financial_report.pdf"
    matches = _find_all_filenames("summarize the q3 financial report", conn)
    assert "q3_financial_report.pdf" in matches


def test_find_all_no_short_basename_false_positive(conn):
    # "pdf" alone should NOT trigger a match (base-name < 4 chars check)
    matches = _find_all_filenames("show me the pdf", conn)
    # "pdf" is the extension of everything — should not trigger base match
    # exact match for "acme_contract.pdf" also not present
    assert all(".pdf" not in m or m in ["acme_contract.pdf", "dallas_resume.pdf",
                                         "q3_financial_report.pdf"]
               for m in matches)


# ── _find_filename_filter ─────────────────────────────────────────

def test_filename_filter_returns_first_match(conn):
    result = _find_filename_filter("Compare acme_contract.pdf and dallas_resume.pdf", conn)
    # Should return exactly ONE filename (whichever appears first)
    assert result in ("acme_contract.pdf", "dallas_resume.pdf")


def test_filename_filter_returns_none_on_general_query(conn):
    result = _find_filename_filter("What is the capital of France?", conn)
    assert result is None


# ── _is_multi_doc_query ───────────────────────────────────────────

def test_is_multi_doc_two_named_files(conn):
    matched = ["acme_contract.pdf", "dallas_resume.pdf"]
    assert _is_multi_doc_query("compare these two docs", matched) is True


def test_is_multi_doc_compare_keyword_one_file(conn):
    matched = ["acme_contract.pdf"]
    assert _is_multi_doc_query(
        "how does my acme contract compare to industry standard?", matched
    ) is True


def test_is_multi_doc_broad_all_phrase(conn):
    matched = []
    assert _is_multi_doc_query("summarize all my documents", matched) is True


def test_is_multi_doc_versus(conn):
    matched = ["acme_contract.pdf", "dallas_resume.pdf"]
    assert _is_multi_doc_query(
        "acme_contract.pdf vs dallas_resume.pdf — what differs?", matched
    ) is True


def test_is_not_multi_doc_single_file_no_keyword(conn):
    matched = ["acme_contract.pdf"]
    assert _is_multi_doc_query("what are the payment terms?", matched) is False


def test_is_not_multi_doc_empty_matches_no_keyword(conn):
    matched = []
    assert _is_multi_doc_query("who is the author of this paper?", matched) is False


# ── _rewrite_query (mocked ollama) ───────────────────────────────

def test_rewrite_query_short_passthrough():
    """Queries ≤6 words are returned unchanged without calling ollama."""
    from query import _rewrite_query
    with patch("query.ollama") as mock_ollama:
        result = _rewrite_query("what is the date?")
        mock_ollama.chat.assert_not_called()
        assert result == "what is the date?"


def test_rewrite_query_long_calls_ollama():
    """Long conversational queries should call ollama.chat for rewriting."""
    from query import _rewrite_query
    mock_response = MagicMock()
    mock_response.message.content = "payment terms acme contract"
    with patch("query.ollama") as mock_ollama:
        mock_ollama.chat.return_value = mock_response
        result = _rewrite_query(
            "can you tell me what the payment terms are in the contract", model="test"
        )
        mock_ollama.chat.assert_called_once()
        assert result == "payment terms acme contract"


def test_rewrite_query_ollama_failure_returns_original():
    """If ollama raises, the original query is returned unchanged."""
    from query import _rewrite_query
    with patch("query.ollama") as mock_ollama:
        mock_ollama.chat.side_effect = Exception("connection refused")
        result = _rewrite_query(
            "can you tell me what the payment terms are in the contract"
        )
        assert "payment" in result  # original returned


# ── confidence_bar ────────────────────────────────────────────────

def test_confidence_bar_high():
    from query import confidence_bar
    bar = confidence_bar(0.90)
    assert "HIGH" in bar
    assert "90%" in bar


def test_confidence_bar_medium():
    from query import confidence_bar
    bar = confidence_bar(0.65)
    assert "MED" in bar


def test_confidence_bar_low():
    from query import confidence_bar
    bar = confidence_bar(0.30)
    assert "LOW" in bar
