"""
locallab · core/agent.py
────────────────────────
Research Mode ReAct agent.

Three tools:
  search_web(query)         — DuckDuckGo text search (5 results)
  fetch_url(url)            — requests + BeautifulSoup, stripped to ~4000 chars
  query_documents(question) — retrieve_chunks() from the local Qdrant index

Loop:
  1. Call ollama.chat(tools=AGENT_TOOLS) non-streaming.
  2. If tool_calls present, execute each tool, append results.
  3. Repeat up to MAX_ITERATIONS.
  4. Stream final answer with the same SSE format as ask_stream().

SSE event sequence:
  event: agent_step   — tool invoked         {tool, args}
  event: agent_result — tool output          {tool, result (truncated to 800 chars)}
  ...repeated per tool-call round...
  event: meta         — {sources:[], confidence:0, chunk_db_ids:[], mode:'research'}
  event: token        — {text: "..."}         (streamed final answer)
  event: done         — {source_file: ""}
"""

import json
import sys
from pathlib import Path

try:
    import ollama
except ImportError:
    print("[agent] ERROR: pip install ollama")
    sys.exit(1)

BASE_DIR = Path(__file__).parent.parent
MAX_ITERATIONS = 5

# ── TOOL DEFINITIONS ──────────────────────────────────────────────

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Search the web for recent information. Use for current events, prices, "
                "industry standards, or anything not in the user's documents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query, 3–10 words"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch and read the full text content of a URL. "
                "Use after search_web to read a specific page in detail."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to fetch"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_documents",
            "description": (
                "Search the user's private document library. Use for anything the user "
                "may have uploaded — contracts, notes, reports, invoices, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Question to answer from the documents",
                    },
                },
                "required": ["question"],
            },
        },
    },
]

AGENT_SYSTEM_PROMPT = """\
You are a research assistant with access to three tools:
- search_web: search the internet for current information
- fetch_url: read the full text content of a specific web page
- query_documents: search the user's private document library

Strategy:
1. Start with query_documents if the question might be answered from the user's files.
2. Use search_web for current facts, industry standards, prices, or anything not in documents.
3. Use fetch_url to read a specific page after search_web returns a promising URL.
4. After gathering enough information, synthesize a thorough, well-cited answer.

When referencing evidence, insert inline citation markers like [1], [2] in order.
Think step by step. Do not guess — use tools to verify facts first."""

# ── TOOL IMPLEMENTATIONS ──────────────────────────────────────────

def search_web(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "search_web unavailable: pip install duckduckgo-search"
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "No results found."
        return "\n\n".join(
            f"Title: {r['title']}\nURL: {r['href']}\nSnippet: {r['body']}"
            for r in results
        )
    except Exception as e:
        return f"Search error: {e}"


def fetch_url(url: str) -> str:
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return "fetch_url unavailable: pip install requests beautifulsoup4"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:4000]
    except Exception as e:
        return f"Error fetching URL: {e}"


def query_documents(question: str) -> str:
    try:
        sys.path.insert(0, str(BASE_DIR / "core"))
        from query import retrieve_chunks
        try:
            chunks = retrieve_chunks(question)
        except SystemExit:
            return "No documents indexed yet."
        if not chunks:
            return "No relevant documents found in your library."
        return "\n\n".join(
            f"[{c['filename']} p.{c.get('page_start', '?')}]\n{c['text'][:500]}"
            for c in chunks[:5]
        )
    except Exception as e:
        return f"Error querying documents: {e}"


_TOOL_FN = {
    "search_web":      search_web,
    "fetch_url":       fetch_url,
    "query_documents": query_documents,
}

# ── REACT LOOP ────────────────────────────────────────────────────

def agent_stream(question: str, model: str, history: list):
    """
    Generator that yields SSE-formatted strings.
    Runs the ReAct tool-calling loop, then streams the final answer.
    """
    messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    for h in (history or [])[-6:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant"):
            messages.append({"role": h["role"], "content": str(h.get("content", ""))})
    messages.append({"role": "user", "content": question})

    for _iteration in range(MAX_ITERATIONS):
        try:
            resp = ollama.chat(model=model, messages=messages, tools=AGENT_TOOLS)
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            return

        if not resp.message.tool_calls:
            break  # model is done calling tools — ready to synthesize

        for tc in resp.message.tool_calls:
            fn_name = tc.function.name
            fn_args = dict(tc.function.arguments) if tc.function.arguments else {}

            yield f"event: agent_step\ndata: {json.dumps({'tool': fn_name, 'args': fn_args})}\n\n"

            fn     = _TOOL_FN.get(fn_name)
            result = fn(**fn_args) if fn else f"Unknown tool: {fn_name}"

            yield f"event: agent_result\ndata: {json.dumps({'tool': fn_name, 'result': result[:800]})}\n\n"

            # Append assistant turn (with tool_calls) + tool result
            messages.append(resp.message)
            messages.append({"role": "tool", "content": result})

    # Emit meta — agent mode has no Qdrant sources
    yield f"event: meta\ndata: {json.dumps({'sources': [], 'confidence': 0, 'chunk_db_ids': [], 'mode': 'research', 'model': model})}\n\n"

    # Stream the final synthesized answer
    try:
        for chunk in ollama.chat(model=model, messages=messages, stream=True):
            token = chunk.get("message", {}).get("content", "")
            if token:
                yield f"event: token\ndata: {json.dumps({'text': token})}\n\n"
    except Exception as e:
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        return

    yield f"event: done\ndata: {json.dumps({'source_file': '', 'mode': 'research'})}\n\n"
