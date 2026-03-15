"""
DONE · core/query.py
─────────────────────
RAG pipeline. Takes a plain English question, retrieves relevant
chunks from ChromaDB, passes context to Qwen2.5:14b, returns
an answer with exact source citation and confidence score.

Usage:
  python core/query.py --question "Where does Dallas work?"
  python core/query.py --question "What are the payment terms?" --top-k 7
  python core/query.py --interactive
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

try:
    import ollama
except ImportError:
    print("[query] ERROR: pip install ollama")
    sys.exit(1)

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Filter, FieldCondition, MatchValue,
    )
except ImportError:
    print("[query] ERROR: pip install qdrant-client")
    sys.exit(1)

# ── CONFIG ────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent.parent
DB_PATH        = BASE_DIR / "db" / "done.db"
QDRANT_PATH    = BASE_DIR / "db" / "qdrant"
REASON_MODEL   = "qwen2.5:14b"
EMBED_MODEL             = "nomic-embed-text"
TOP_K                   = 5
GENERAL_CHAT_THRESHOLD  = 0.40   # similarity below this → fall back to general LLM chat

# ── DATABASE ──────────────────────────────────────────────────────

def get_conn():
    if not DB_PATH.exists():
        print("[query] No database found. Run ingest.py first.")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── RETRIEVAL ─────────────────────────────────────────────────────

def _find_filename_filter(question, conn):
    """
    If the question explicitly mentions a known filename (with or without
    extension), return that filename so retrieval can be scoped to it.
    E.g. "what's in physicians.json" -> "physicians.json"
         "give me my facilities"      -> "facilities.json"  (base-name match)
    Returns None if no match.
    """
    q_lower = question.lower()
    rows = conn.execute("SELECT filename FROM documents WHERE status='indexed'").fetchall()
    # Exact filename match first (e.g. "physicians.json")
    for r in rows:
        fn = r["filename"]
        if fn.lower() in q_lower:
            return fn
    # Base-name match (strip extension), require word boundary
    for r in rows:
        fn   = r["filename"]
        base = fn.rsplit(".", 1)[0].lower().replace("_", " ").replace("-", " ")
        # Only match if base-name is at least 4 chars to avoid false positives
        if len(base) >= 4 and re.search(r'\b' + re.escape(base) + r'\b', q_lower):
            return fn
    return None


def retrieve_chunks(question, top_k=TOP_K, filename_filter=None):
    """
    Hybrid retrieval: dense (nomic-embed-text) + sparse (BM25) via Qdrant,
    fused with Reciprocal Rank Fusion. Optionally scoped to one filename.
    """
    if not QDRANT_PATH.exists():
        print("[query] No Qdrant DB found. Run ingest.py first.")
        sys.exit(1)

    client = QdrantClient(path=str(QDRANT_PATH))

    try:
        info  = client.get_collection("locallab")
        count = info.points_count or 0
    except Exception:
        print("[query] No documents indexed yet. Run ingest.py first.")
        sys.exit(1)

    if count == 0:
        print("[query] No documents in index. Run ingest.py first.")
        sys.exit(1)

    # Compute dense embedding via Ollama
    dense_vec = ollama.embeddings(model=EMBED_MODEL, prompt=question)["embedding"]

    # Optional per-filename filter
    qfilter = None
    if filename_filter:
        qfilter = Filter(must=[
            FieldCondition(key="filename", match=MatchValue(value=filename_filter))
        ])

    actual_k = min(top_k, count)

    results = client.query_points(
        collection_name="locallab",
        query=dense_vec,
        using="dense",
        query_filter=qfilter,
        limit=actual_k,
        with_payload=True,
    )

    chunks = []
    for point in results.points:
        p = point.payload or {}
        chunks.append({
            "text":        p.get("text", ""),
            "filename":    p.get("filename", "unknown"),
            "doc_id":      p.get("doc_id", 0),
            "chunk_index": p.get("chunk_index", 0),
            "page_start":  p.get("page_start", 0),
            "page_end":    p.get("page_end", 0),
            "similarity":  round(point.score, 3),
        })

    return chunks

def retrieve_entities(question, conn, limit=10):
    """
    Also check entities table for direct matches.
    Useful for specific fact lookups like names, amounts, dates.
    """
    words = [w.lower() for w in question.split() if len(w) > 3]
    if not words:
        return []

    entities = []
    for word in words[:5]:  # check top 5 keywords
        rows = conn.execute("""
            SELECT e.entity_type, e.value, e.context,
                   d.filename, d.id as doc_id
            FROM entities e
            JOIN documents d ON e.doc_id = d.id
            WHERE LOWER(e.value) LIKE ? OR LOWER(e.context) LIKE ?
            LIMIT 5
        """, (f"%{word}%", f"%{word}%")).fetchall()
        for r in rows:
            entities.append(dict(r))

    # Deduplicate by value
    seen = set()
    unique = []
    for e in entities:
        if e["value"] not in seen:
            seen.add(e["value"])
            unique.append(e)

    return unique[:limit]

# ── ANSWER GENERATION ─────────────────────────────────────────────

ANSWER_PROMPT = """You are locallab, a private document assistant. Answer questions using ONLY the provided document context.

Rules:
1. Answer ONLY from the context provided — never use outside knowledge
2. If the answer is in the context, give it clearly and specifically
3. If the answer is NOT in the context, say exactly: "I could not find this information in your documents."
4. Always cite which document your answer comes from
5. Be concise and direct
6. If the conversation history shows prior questions, use them to understand follow-up questions (e.g. "what else?", "who is that?") but still answer from document context only

Return ONLY valid JSON, no other text:
{{
  "answer": "your specific answer here",
  "source_file": "filename the answer came from",
  "source_page": page number as integer or 0 if unknown,
  "source_span": "exact quote from the context that supports your answer (under 100 words)",
  "confidence": 0.0 to 1.0,
  "found": true or false
}}"""

def generate_answer(question, chunks, entities, conversation=None, model=None):
    """
    Pass retrieved context to Qwen2.5:14b and get a grounded answer.
    """
    # Build context from chunks
    context_parts = []
    for i, c in enumerate(chunks):
        page_ref = (f"Page {c['page_start']}"
                    if c.get("page_start") and c["page_start"] > 0
                    else "")
        context_parts.append(
            f"[Document: {c['filename']} | {page_ref} | Chunk {c['chunk_index']} "
            f"| Relevance: {c['similarity']:.2f}]\n{c['text']}"
        )

    # Add entity context if relevant
    if entities:
        entity_lines = []
        for e in entities[:8]:
            entity_lines.append(
                f"  [{e['entity_type']}] {e['value']} "
                f"(from {e['filename']}): {e['context']}"
            )
        context_parts.append(
            "Extracted facts from documents:\n" + "\n".join(entity_lines)
        )

    context = "\n\n---\n\n".join(context_parts)

    prompt = (
        f"Question: {question}\n\n"
        f"Document context:\n{context}\n\n"
        f"Answer the question using only the context above."
    )

    try:
        # Build message list: system → prior conversation (last 6) → current prompt
        messages = [{"role": "system", "content": ANSWER_PROMPT}]
        if conversation:
            messages.extend(conversation[-6:])
        messages.append({"role": "user", "content": prompt})

        response = ollama.chat(
            model=model or REASON_MODEL,
            messages=messages,
            options={"temperature": 0.1, "num_ctx": 8192}
        )
        raw = response["message"]["content"].strip()

        # Strip markdown fences
        raw = re.sub(r'```(?:json)?\s*', '', raw).strip()
        raw = raw.rstrip('`').strip()

        # Extract JSON
        start = raw.find('{')
        end   = raw.rfind('}')
        if start == -1 or end == -1:
            return fallback_answer(question, chunks)

        parsed = json.loads(raw[start:end+1])
        return parsed

    except json.JSONDecodeError:
        return fallback_answer(question, chunks)
    except Exception as e:
        print(f"[query] Answer generation error: {e}")
        return fallback_answer(question, chunks)

def fallback_answer(question, chunks):
    """If JSON parsing fails, return best chunk as plain answer."""
    if chunks:
        return {
            "answer":      chunks[0]["text"][:300],
            "source_file": chunks[0]["filename"],
            "source_span": chunks[0]["text"][:150],
            "confidence":  chunks[0]["similarity"],
            "found":       True,
        }
    return {
        "answer":      "I could not find this information in your documents.",
        "source_file": "",
        "source_span": "",
        "confidence":  0.0,
        "found":       False,
    }

# ── CONFIDENCE DISPLAY ────────────────────────────────────────────

def confidence_bar(score, width=20):
    filled = int(score * width)
    bar    = "█" * filled + "░" * (width - filled)
    pct    = int(score * 100)
    if pct >= 80:   label = "HIGH"
    elif pct >= 55: label = "MED"
    else:           label = "LOW"
    return f"[{bar}] {pct}% {label}"

# ── GENERAL CHAT FALLBACK ─────────────────────────────────────────

def _general_chat(question, conversation, model):
    """
    Direct Ollama chat with no document context.
    Called when retrieved chunk similarity is below GENERAL_CHAT_THRESHOLD,
    meaning the query is not about any indexed document.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful, knowledgeable assistant. "
                "Answer the user's question clearly and concisely. "
                "If you are unsure about something, say so — do not fabricate facts."
            ),
        }
    ]
    if conversation:
        messages.extend(conversation[-6:])
    messages.append({"role": "user", "content": question})

    response = ollama.chat(
        model=model or REASON_MODEL,
        messages=messages,
        options={"temperature": 0.7, "num_ctx": 8192},
    )
    return response["message"]["content"].strip()


# ── MAIN QUERY ────────────────────────────────────────────────────

def ask(question, top_k=TOP_K, verbose=False, conversation=None, model=None):
    """
    Full RAG pipeline:
    question → retrieve chunks → retrieve entities → generate answer → return result
    """
    conn = get_conn()
    t0   = time.time()

    if verbose:
        print(f"\n[query] Question: {question}")
        print(f"[query] Retrieving top-{top_k} chunks...", end=" ", flush=True)

    # Detect explicit filename mention → scope retrieval to that document
    filename_filter = _find_filename_filter(question, conn)
    if verbose and filename_filter:
        print(f"[query] Filename filter active: {filename_filter}")

    # Retrieve 10 candidates via hybrid search, pass top 5 to LLM
    # (more candidates improves RRF fusion quality)
    fetch_k = max(top_k * 2, 10)
    chunks  = retrieve_chunks(question, top_k=fetch_k, filename_filter=filename_filter)
    if not chunks and filename_filter:
        if verbose:
            print("[query] Filter returned no results, retrying without filter")
        chunks = retrieve_chunks(question, top_k=fetch_k)
    entities = retrieve_entities(question, conn)

    # Attach filepath to each chunk via documents table
    if chunks:
        doc_ids = list({c["doc_id"] for c in chunks if c["doc_id"]})
        rows = conn.execute(
            f"SELECT id, filepath FROM documents WHERE id IN ({','.join('?'*len(doc_ids))})",
            doc_ids
        ).fetchall()
        filepath_map = {r[0]: r[1] for r in rows}
        for c in chunks:
            c["filepath"] = filepath_map.get(c["doc_id"], "")

    if verbose:
        print(f"-> {len(chunks)} chunks, {len(entities)} entity matches")
        if chunks:
            print(f"[query] Best chunk similarity: {chunks[0]['similarity']:.3f} ({chunks[0]['filename']})")

    if not chunks:
        return {
            "question":    question,
            "answer":      "No documents indexed yet. Run ingest.py first.",
            "source_file": "",
            "source_span": "",
            "confidence":  None,
            "found":       False,
            "elapsed":     0.0,
            "mode":        "general",
            "model":       model or REASON_MODEL,
            "sources":     [],
        }

    # Low similarity → fall back to general LLM chat (no document context)
    top_similarity = chunks[0]["similarity"]
    if top_similarity < GENERAL_CHAT_THRESHOLD:
        if verbose:
            print(f"[query] Best similarity {top_similarity:.3f} < threshold {GENERAL_CHAT_THRESHOLD} → general chat mode")
        t_gen = time.time()
        answer = _general_chat(question, conversation, model)
        return {
            "question":    question,
            "answer":      answer,
            "source_file": "",
            "source_span": "",
            "confidence":  None,
            "found":       False,
            "elapsed":     round(time.time() - t_gen, 2),
            "mode":        "general",
            "model":       model or REASON_MODEL,
            "sources":     [],
        }

    # Generate answer
    if verbose:
        print(f"[query] Generating answer...", end=" ", flush=True)

    # Pass only top 5 chunks to LLM — hybrid ranking already surfaced the best ones
    result  = generate_answer(question, chunks[:5], entities, conversation=conversation, model=model)
    elapsed = time.time() - t0

    if verbose:
        print(f"-> done ({elapsed:.1f}s)")

    result["question"] = question
    result["elapsed"]  = round(elapsed, 2)
    result["model"]    = model or REASON_MODEL
    result["mode"]     = "document"

    # Override confidence with Qdrant similarity score from top chunk.
    # The LLM's self-reported confidence is not well-calibrated; the
    # cosine similarity from ChromaDB is a more reliable signal.
    if chunks:
        top_similarity = chunks[0]["similarity"]
        result["confidence"] = round(top_similarity, 3)
        result["source_path"] = chunks[0].get("filepath", "")

    # Build sources list for UI citations panel.
    # Always use the top-ranked chunk's filename as primary — the LLM-reported
    # source_file can be empty. Only show chunks from that same document so
    # unrelated files don't pollute the panel when confidence is low.
    primary_file = chunks[0]["filename"] if chunks else ""

    visible_sources = [c for c in chunks if c["filename"] == primary_file]

    result["sources"] = [
        {
            "filename":   c["filename"],
            "filepath":   c.get("filepath", ""),
            "page_start": c["page_start"],
            "page_end":   c["page_end"],
            "similarity": c["similarity"],
            "snippet":    c["text"][:200],
        }
        for c in visible_sources
    ]

    return result


STREAM_PROMPT = """You are locallab, a private document assistant. Answer the question using ONLY the provided document context.

Rules:
1. Answer ONLY from the context — never use outside knowledge
2. If the answer is not in the context, say: "I could not find this information in your documents."
3. Cite the document your answer comes from (e.g. "According to filename.pdf...")
4. Be clear and direct. Use markdown for structure (bullet points, bold) when helpful."""


def ask_stream(question, top_k=TOP_K, conversation=None, model=None):
    """
    Streaming RAG pipeline. Yields SSE-formatted strings.

    Event sequence:
      event: meta   — retrieval metadata (sources, confidence, mode) sent first
      event: token  — each LLM token as it arrives
      event: done   — end of stream
    """
    import json as _json

    conn = get_conn()
    t0   = time.time()

    # ── Retrieval (non-streaming, fast ~200ms) ─────────────────────
    # retrieve_chunks may sys.exit(1) if Qdrant is empty — treat as no results
    filename_filter = _find_filename_filter(question, conn)
    fetch_k = max(top_k * 2, 10)
    try:
        chunks = retrieve_chunks(question, top_k=fetch_k, filename_filter=filename_filter)
        if not chunks and filename_filter:
            chunks = retrieve_chunks(question, top_k=fetch_k)
    except SystemExit:
        chunks = []
    entities = retrieve_entities(question, conn)

    if chunks:
        doc_ids = list({c["doc_id"] for c in chunks if c["doc_id"]})
        rows = conn.execute(
            f"SELECT id, filepath FROM documents WHERE id IN ({','.join('?'*len(doc_ids))})",
            doc_ids
        ).fetchall()
        filepath_map = {r[0]: r[1] for r in rows}
        for c in chunks:
            c["filepath"] = filepath_map.get(c["doc_id"], "")

    retrieval_elapsed = round(time.time() - t0, 2)

    # ── Determine mode ─────────────────────────────────────────────
    if not chunks:
        meta = {
            "mode": "general", "confidence": None, "sources": [],
            "source_file": "", "source_path": "", "model": model or REASON_MODEL,
            "retrieval_elapsed": retrieval_elapsed,
        }
        yield f"event: meta\ndata: {_json.dumps(meta)}\n\n"
        # Stream general chat
        messages = [
            {"role": "system", "content": "You are a helpful, knowledgeable assistant. Answer clearly and concisely."}
        ]
        if conversation:
            messages.extend(conversation[-6:])
        messages.append({"role": "user", "content": question})
        for chunk in ollama.chat(model=model or REASON_MODEL, messages=messages,
                                  options={"temperature": 0.7, "num_ctx": 8192}, stream=True):
            token = chunk.get("message", {}).get("content", "")
            if token:
                yield f"event: token\ndata: {_json.dumps({'text': token})}\n\n"
        yield "event: done\ndata: {}\n\n"
        return

    top_similarity = chunks[0]["similarity"]
    is_general = top_similarity < GENERAL_CHAT_THRESHOLD

    # Show ALL retrieved sources (all files), sorted by similarity.
    # We don't know which file the LLM will cite until after streaming —
    # we'll update the source badge in the `done` event once we can scan the answer.
    all_sources = [
        {
            "filename":   c["filename"],
            "filepath":   c.get("filepath", ""),
            "page_start": c["page_start"],
            "page_end":   c["page_end"],
            "similarity": c["similarity"],
            "snippet":    c["text"][:200],
        }
        for c in chunks
    ]

    # Best guess at primary file for the initial badge — will be corrected in `done`
    primary_file = chunks[0]["filename"] if chunks else ""

    meta = {
        "mode":               "general" if is_general else "document",
        "confidence":         None if is_general else round(top_similarity, 3),
        "source_file":        "" if is_general else primary_file,
        "source_path":        "" if is_general else chunks[0].get("filepath", ""),
        "sources":            [] if is_general else all_sources,
        "model":              model or REASON_MODEL,
        "retrieval_elapsed":  retrieval_elapsed,
    }
    yield f"event: meta\ndata: {_json.dumps(meta)}\n\n"

    # ── Build messages ─────────────────────────────────────────────
    if is_general:
        messages = [
            {"role": "system", "content": "You are a helpful, knowledgeable assistant. Answer clearly and concisely."}
        ]
        if conversation:
            messages.extend(conversation[-6:])
        messages.append({"role": "user", "content": question})
        temp = 0.7
    else:
        # Re-rank: all chunks from the top-scoring file come first, then fill
        # remaining slots from other files. This ensures the LLM sees every page
        # of the most relevant document even if some pages scored lower globally.
        top_file = chunks[0]["filename"]
        primary_chunks = [c for c in chunks if c["filename"] == top_file]
        other_chunks   = [c for c in chunks if c["filename"] != top_file]
        context_chunks = (primary_chunks + other_chunks)[:5]

        context_parts = []
        for c in context_chunks:
            page_ref = f"Page {c['page_start']}" if c.get("page_start") and c["page_start"] > 0 else ""
            context_parts.append(
                f"[Document: {c['filename']} | {page_ref}]\n{c['text']}"
            )
        if entities:
            entity_lines = [f"  [{e['entity_type']}] {e['value']} (from {e['filename']})" for e in entities[:8]]
            context_parts.append("Extracted facts:\n" + "\n".join(entity_lines))
        context = "\n\n---\n\n".join(context_parts)
        prompt = f"Question: {question}\n\nDocument context:\n{context}\n\nAnswer using only the context above."
        messages = [{"role": "system", "content": STREAM_PROMPT}]
        if conversation:
            messages.extend(conversation[-6:])
        messages.append({"role": "user", "content": prompt})
        temp = 0.1

    # ── Stream tokens — collect full answer to detect cited file ───
    known_filenames = list({c["filename"] for c in chunks})
    full_answer = []
    for chunk in ollama.chat(model=model or REASON_MODEL, messages=messages,
                              options={"temperature": temp, "num_ctx": 8192}, stream=True):
        token = chunk.get("message", {}).get("content", "")
        if token:
            full_answer.append(token)
            yield f"event: token\ndata: {_json.dumps({'text': token})}\n\n"

    # ── Detect the actual cited file from the completed answer ─────
    # Scan the answer text for any known filename mentions.
    # The file mentioned first (earliest position) is the primary source.
    answer_text = "".join(full_answer).lower()
    cited_file = None
    earliest_pos = len(answer_text) + 1
    for fn in known_filenames:
        pos = answer_text.find(fn.lower())
        if pos != -1 and pos < earliest_pos:
            earliest_pos = pos
            cited_file = fn

    # If none found in answer text, fall back to highest-similarity chunk's file
    if not cited_file:
        cited_file = primary_file

    cited_path = next((c.get("filepath", "") for c in chunks if c["filename"] == cited_file), "")
    cited_conf = next((c["similarity"] for c in chunks if c["filename"] == cited_file), top_similarity)

    yield f"event: done\ndata: {_json.dumps({'source_file': cited_file, 'source_path': cited_path, 'confidence': round(cited_conf, 3)})}\n\n"


def print_result(result):
    """Pretty print a query result to terminal."""
    print(f"\n{'─'*60}")
    print(f"Q: {result['question']}")
    print(f"{'─'*60}")
    print(f"\nA: {result.get('answer', 'No answer')}")

    if result.get("source_file"):
        page = result.get("source_page", 0)
        page_str = f"  ·  page {page}" if page and page > 0 else ""
        print(f"\nSource:  {result['source_file']}{page_str}")

    if result.get("source_span"):
        print(f"Cited:   \"{result['source_span'][:200]}\"")

    conf = result.get("confidence", 0.0)
    print(f"\nTrust:   {confidence_bar(conf)}")
    print(f"Time:    {result.get('elapsed', 0):.1f}s")
    print(f"{'─'*60}")


def interactive_mode(top_k=TOP_K):
    """Run an interactive Q&A session."""
    conn = get_conn()

    # Show indexed docs
    docs = conn.execute(
        "SELECT filename, chunk_count, entity_count FROM documents"
    ).fetchall()

    print(f"\n{'═'*60}")
    print(f"  done — Document Q&A")
    print(f"{'═'*60}")
    print(f"  {len(docs)} document(s) indexed:")
    for d in docs:
        print(f"  · {d[0]}  ({d[1]} chunks, {d[2]} entities)")
    print(f"\n  Type your question. 'quit' to exit.")
    print(f"{'═'*60}\n")

    while True:
        try:
            q = input("Ask: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[done] Goodbye.")
            break

        if not q:
            continue
        if q.lower() in ("quit", "exit", "q"):
            print("[done] Goodbye.")
            break

        result = ask(q, top_k=top_k, verbose=True)
        print_result(result)
        print()


# ── CLI ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="DONE query — ask questions about your documents")
    p.add_argument("--question",    "-q", help="Question to ask")
    p.add_argument("--interactive", "-i", action="store_true",
                   help="Interactive Q&A mode")
    p.add_argument("--top-k",       type=int, default=TOP_K,
                   help="Number of chunks to retrieve")
    p.add_argument("--verbose",     "-v", action="store_true",
                   help="Show retrieval details")
    args = p.parse_args()

    if args.interactive:
        interactive_mode(top_k=args.top_k)
    elif args.question:
        result = ask(args.question, top_k=args.top_k, verbose=args.verbose)
        print_result(result)
    else:
        p.print_help()