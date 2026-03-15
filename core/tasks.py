"""
locallab · core/tasks.py
─────────────────────────
Pre-built document task agents.

Each task retrieves the most relevant chunks from one or more documents,
runs a specialized prompt against them, and streams the result as SSE —
the same token/done protocol used by /api/ask/stream.

Public API:
  TASK_DEFINITIONS   — dict of task metadata for the UI
  run_task_stream()  — SSE generator, yields event: token / done / error
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DB_PATH  = BASE_DIR / "db" / "done.db"

try:
    import ollama
except ImportError:
    print("[tasks] ERROR: pip install ollama")
    sys.exit(1)

# ── TASK DEFINITIONS ──────────────────────────────────────────────
# Each task has:
#   name        — display name
#   description — one-liner shown in the picker
#   icon        — emoji for the card
#   multi_doc   — True if the task takes 2 documents
#   prompt      — template; {filename}, {context}, {filename2}, {context2}

TASK_DEFINITIONS = {
    "summarize": {
        "id":          "summarize",
        "name":        "Summarize",
        "description": "Get a concise summary of this document",
        "icon":        "📋",
        "multi_doc":   False,
    },
    "action_items": {
        "id":          "action_items",
        "name":        "Action items",
        "description": "Find all tasks, obligations, and required actions",
        "icon":        "✅",
        "multi_doc":   False,
    },
    "dates_deadlines": {
        "id":          "dates_deadlines",
        "name":        "Dates & deadlines",
        "description": "Extract every date, deadline, and timeframe",
        "icon":        "📅",
        "multi_doc":   False,
    },
    "key_people": {
        "id":          "key_people",
        "name":        "Key people & roles",
        "description": "Identify all people, companies, and their roles",
        "icon":        "👥",
        "multi_doc":   False,
    },
    "financial_terms": {
        "id":          "financial_terms",
        "name":        "Financial terms",
        "description": "Extract all amounts, fees, and financial obligations",
        "icon":        "💰",
        "multi_doc":   False,
    },
    "risk_flags": {
        "id":          "risk_flags",
        "name":        "Risk flags",
        "description": "Spot unusual clauses, missing terms, or red flags",
        "icon":        "🚩",
        "multi_doc":   False,
    },
    "draft_reply": {
        "id":          "draft_reply",
        "name":        "Draft a reply",
        "description": "Generate a professional response to this document",
        "icon":        "✉️",
        "multi_doc":   False,
    },
    "compare": {
        "id":          "compare",
        "name":        "Compare two docs",
        "description": "Side-by-side comparison of similarities and differences",
        "icon":        "⚖️",
        "multi_doc":   True,
    },
}

# ── PROMPTS ───────────────────────────────────────────────────────
_PROMPTS = {
    "summarize": """\
You are analyzing "{filename}". Write a concise summary of this document.

Rules:
- Output 4-6 bullet points (use markdown - )
- Each bullet must be specific to the actual content — no generic filler
- Mention key names, amounts, dates, or obligations from the document
- End with one sentence: "**Bottom line:** ..."

Document content from {filename}:
{context}""",

    "action_items": """\
You are analyzing "{filename}". Extract every action item, obligation, task, and requirement.

Rules:
- Format as a markdown checklist: - [ ] item
- Include WHO is responsible (if stated) and WHEN it is due (if stated)
- Be specific — quote exact language where it matters
- If none found, say so clearly

Document content from {filename}:
{context}""",

    "dates_deadlines": """\
You are analyzing "{filename}". Extract every date, deadline, timeframe, and time-sensitive item.

Rules:
- Format as a markdown table with columns: Date | What it refers to | Who is affected
- Include relative timeframes ("within 30 days", "monthly") as well as absolute dates
- Sort chronologically where possible
- If none found, say so clearly

Document content from {filename}:
{context}""",

    "key_people": """\
You are analyzing "{filename}". Identify every person, company, and organization mentioned.

Rules:
- Format as a markdown table: Name | Type (Person/Company/Org) | Role/Relationship
- Include all parties, signatories, referenced individuals, and organizations
- If a role is unclear, note "mentioned" in the Role column

Document content from {filename}:
{context}""",

    "financial_terms": """\
You are analyzing "{filename}". Extract every financial amount, fee, price, and monetary obligation.

Rules:
- Format as a markdown table: Amount | What it covers | Who pays | When due
- Include one-time payments, recurring fees, penalties, and conditional amounts
- Quote exact language for amounts where important
- If none found, say so clearly

Document content from {filename}:
{context}""",

    "risk_flags": """\
You are analyzing "{filename}" for potential risks, unusual clauses, and red flags.

Rules:
- Format each risk as: **[RISK LEVEL: HIGH/MEDIUM/LOW]** — description
- Look for: unusual obligations, missing standard terms, one-sided clauses, vague language, tight deadlines, auto-renewal traps, liability waivers
- Be specific — quote the problematic language
- If the document appears standard, say so

Document content from {filename}:
{context}""",

    "draft_reply": """\
You are analyzing "{filename}". Draft a professional reply to this document.

Rules:
- Write a complete, ready-to-send response
- Address the key points, obligations, or requests in the document
- Use formal but clear language
- Include placeholders like [YOUR NAME], [DATE], [YOUR COMPANY] where needed
- Keep it concise — one page maximum

Document content from {filename}:
{context}""",

    "compare": """\
You are comparing two documents: "{filename}" and "{filename2}".

Rules:
- Start with a 2-sentence overview of what each document is
- Then a markdown table: Topic | {filename} | {filename2}
- Cover: purpose, parties involved, key terms, obligations, dates, amounts, risks
- End with: **Key differences:** bullet list and **Bottom line:** one sentence

Content from {filename}:
{context}

Content from {filename2}:
{context2}""",
}


# ── HELPERS ───────────────────────────────────────────────────────

def _get_doc_context(doc_id: int, conn) -> tuple[str, str]:
    """Return (filename, context_text) for a document using its top chunks."""
    doc = conn.execute(
        "SELECT filename FROM documents WHERE id=?", (doc_id,)
    ).fetchone()
    if not doc:
        raise ValueError(f"Document {doc_id} not found")

    chunks = conn.execute(
        "SELECT page_start, text FROM chunks WHERE doc_id=? ORDER BY chunk_index",
        (doc_id,)
    ).fetchall()

    # Use up to 6 chunks (~3600 words) for task context
    context = "\n\n".join(
        f"[Page {c['page_start']}]\n{c['text']}"
        for c in chunks[:6]
    )
    return doc["filename"], context


# ── MAIN STREAM GENERATOR ─────────────────────────────────────────

def run_task_stream(task_id: str, doc_ids: list[int], model: str = None):
    """
    SSE generator. Yields:
      event: meta   — task name, doc names
      event: token  — streaming token
      event: done   — task complete
      event: error  — on failure
    """
    if task_id not in TASK_DEFINITIONS:
        yield f"event: error\ndata: {json.dumps({'error': f'Unknown task: {task_id}'})}\n\n"
        return

    task   = TASK_DEFINITIONS[task_id]
    model  = model or "llama3.1:8b"
    prompt_tmpl = _PROMPTS.get(task_id, "")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    try:
        # Fetch document context(s)
        filename, context = _get_doc_context(doc_ids[0], conn)

        filename2 = context2 = ""
        if task["multi_doc"] and len(doc_ids) >= 2:
            filename2, context2 = _get_doc_context(doc_ids[1], conn)

        conn.close()

        # Build prompt
        prompt = prompt_tmpl.format(
            filename=filename,
            context=context,
            filename2=filename2,
            context2=context2,
        )

        # Emit meta event
        doc_names = [filename] + ([filename2] if filename2 else [])
        meta = {
            "task_id":   task_id,
            "task_name": task["name"],
            "task_icon": task["icon"],
            "doc_names": doc_names,
        }
        yield f"event: meta\ndata: {json.dumps(meta)}\n\n"

        # Stream LLM response
        stream = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            options={"temperature": 0.3, "num_predict": 1200},
        )

        for chunk in stream:
            text = (chunk.message.content or "") if hasattr(chunk, "message") else ""
            if text:
                yield f"event: token\ndata: {json.dumps({'text': text})}\n\n"

        yield f"event: done\ndata: {json.dumps({'task_id': task_id})}\n\n"

    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
