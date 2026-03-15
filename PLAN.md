# locallab — Product Plan

> **Vision:** A private, local-first AI that knows everything in your files.
> Zero cloud. No subscriptions. Runs entirely on your Mac.
> As simple as dropping a file in — as powerful as a team of analysts.

---

## What locallab is

locallab is an open-source document AI you install once and run forever on your own machine.
You drop in PDFs, contracts, resumes, notes, spreadsheets — and then you talk to them in plain English.
It indexes everything, understands scanned pages via vision models, extracts entities, and gives you cited answers with a trust score.
When no relevant document exists, it falls back to a general Ollama chat assistant.

---

## Current state — what is BUILT ✓

| Area | Feature | Notes |
|---|---|---|
| **Ingestion** | PDF/DOCX/TXT/CSV/XLSX/PNG/JPG | Supported file types |
| **Ingestion** | Per-page text extraction (pypdf + fitz) | Wraps each page in try/except |
| **Ingestion** | Vision extraction for sparse/scanned pages | qwen2.5vl:7b, triggers at <30 chars/page |
| **Ingestion** | Chunking with configurable size/overlap | 3 profiles: small/medium/large |
| **Ingestion** | Named entity extraction | People, orgs, dates, amounts, skills |
| **Ingestion** | Qdrant hybrid search (dense + sparse BM25) | nomic-embed-text + fastembed |
| **Ingestion** | Background worker with priority queue | Smallest files first |
| **Ingestion** | Watch folder (watchdog) | Watches folders defined in config.yaml |
| **Query** | Streaming SSE answers (token-by-token) | AbortController 45s silence timeout |
| **Query** | Dual-mode: document RAG + general Ollama chat | Threshold: similarity ≥ 0.40 → docs |
| **Query** | Context re-ranking | All pages from top file promoted first |
| **Query** | Markdown rendering (marked.js + DOMPurify) | Full md: bullets, code, tables, bold |
| **Query** | Trust/confidence bar | Qdrant cosine similarity, not LLM self-report |
| **Query** | Source citations with expandable panel | Per-chunk: file, page, similarity, snippet |
| **Query** | Post-stream source filtering | Badge + panel update to cited file on `done` |
| **Query** | Conversation history (multi-turn) | Last 10 turns passed to LLM |
| **UI** | Ask / Files / Queue / Insights tabs | Single-page app |
| **UI** | File viewer modal | Chunks + entities inspector, tabbed |
| **UI** | Delete documents | Removes from SQLite + Qdrant |
| **UI** | Dark / light mode | Correct logos per theme, persisted |
| **UI** | Feedback (thumbs up/down) | Saved to DB |
| **UI** | First-run welcome overlay | Shows on zero documents |
| **UI** | Toast notifications | Replaced all alert() calls |
| **UI** | Drag-and-drop file upload | Drop zone on Ask view |
| **UI** | Recent questions sidebar | Last 6 questions, click to re-ask |
| **Export** | core/export.py complete | JSON, CSV zip, SQLite download |
| **Export** | Flask routes wired | /api/export/json, /api/export/csv, /api/export/sqlite |
| **Infra** | install.sh | curl-installable, checks Ollama, pulls models |
| **Infra** | README.md | Quickstart, architecture, privacy, models |
| **Infra** | .gitignore | venv, db, uploads, logs excluded |
| **Infra** | MIT License | |
| **Infra** | GitHub: dase8601/locallab | Live |

---

## What is NOT built yet — the roadmap

### Phase 1 — Core quality (do first, unblocks everything else)

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 1.1 | **Scan folder UI** | Users have 100s of existing files — no way to bulk-index a folder from the UI today. Only the watch folder (new files) and manual drag-and-drop (one file at a time) exist. Need a "Scan folder" button that walks a directory and queues all supported files. | ❌ Not built |
| 1.2 | **Add / remove watch folders from UI** | Watch folders are hardcoded in config.yaml — no UI to add or remove them. Users shouldn't have to edit YAML. | ❌ Not built |
| 1.3 | **Re-index button per document** | If a file changes, user must delete + re-upload. Need a "Re-index" button that forces re-processing without losing the job history. | ❌ Not built |
| 1.4 | **Vision threshold tunable** | Currently triggers vision at <30 chars. Slides need a higher threshold (~200 chars). Should be per-document or per-upload configurable. | ❌ Not built |
| 1.5 | **Ollama connection status badge** | If Ollama is down, the user just gets a cryptic error or infinite hang. Show a small green/red dot in the sidebar footer indicating live Ollama status. | ❌ Not built |
| 1.6 | **Export buttons in UI** | core/export.py and Flask routes exist, but there are no buttons in the Files view to trigger downloads. | ❌ Not built |
| 1.7 | **Insights view wired** | eval.py exists but the Insights tab shows no data. Need to wire eval results into the UI with a "Run evaluation" button. | ❌ Not built |

### Phase 2 — User experience

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 2.1 | **Search / filter in Files view** | With 50+ docs, scrolling a flat list is painful. Add a search bar that filters by filename. | ❌ Not built |
| 2.2 | **File categories / tags** | Let users tag documents (Work, Legal, Personal, etc.) and filter by tag. | ❌ Not built |
| 2.3 | **Drag-and-drop folder** | Currently can only drop individual files. Dropping a folder should walk it and queue all supported files (same as scan folder but via drag). | ❌ Not built |
| 2.4 | **Keyboard shortcuts** | Cmd+K: focus input. Cmd+/: toggle sidebar. Esc: close modals. `/`: open quick search. | ❌ Not built |
| 2.5 | **Model picker in UI** | Hard-coded to llama3.1:8b / qwen2.5:14b. Let user pick from currently installed Ollama models via a dropdown. Pull new models from UI. | ❌ Not built |
| 2.6 | **Chat history persistence** | Conversation resets on page refresh. Store conversation in localStorage or SQLite so it survives a reload. | ❌ Not built |
| 2.7 | **"Clear chat" button** | Visible button to wipe conversation history rather than requiring a page reload. | ❌ Not built — sidebar new-chat wipes it but it's not obvious |
| 2.8 | **Copy answer button** | One-click copy of the answer text/markdown to clipboard. | ❌ Not built |
| 2.9 | **Per-document export** | Export chunks + entities for a single document, not just the full library. | ❌ Not built |
| 2.10 | **Bulk select + delete** | Select multiple files and delete all at once. | ❌ Not built |

### Phase 3 — Intelligence

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 3.1 | **Auto-generated questions per doc** | After indexing, automatically generate 3–5 sample questions the user could ask about each document. Show them in the file viewer modal and as starter prompts. | ❌ Not built |
| 3.2 | **Document summary on ingest** | Generate a 2-3 sentence summary of each document during ingestion. Show in the Files view row hover. | ❌ Not built |
| 3.3 | **Multi-document queries** | "Compare my two contracts" — query across multiple specified documents simultaneously with merged context. | ❌ Not built |
| 3.4 | **Entity graph view** | Visualize connections between people, orgs, and dates across all documents (who appears in which files, what dates are mentioned). | ❌ Not built |
| 3.5 | **Smart de-duplication** | Detect near-duplicate documents (same contract, different version) and warn the user. | ❌ Not built |
| 3.6 | **Answer grounding score** | Show which specific sentence in the source document the answer came from, not just which page. Highlight the exact span. | ❌ Not built |
| 3.7 | **"What's new" digest** | When watch folder detects new files, generate a 1-sentence summary of what changed and surface it in the UI. | ❌ Not built |

### Phase 4 — Open source / distribution

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 4.1 | **GitHub releases with versioned tags** | v1.0 tag exists in commit but no GitHub Release object with release notes. | ❌ Not built |
| 4.2 | **CONTRIBUTING.md** | How to file issues, submit PRs, coding standards. | ❌ Not built |
| 4.3 | **Demo GIF / screenshot in README** | Projects without visuals get far fewer stars. Record a 30s demo. | ❌ Not built |
| 4.4 | **Docker / docker-compose** | One-command `docker compose up` for users who don't want to manage Python venvs. | ❌ Not built |
| 4.5 | **Windows + Linux install.sh** | Current script is macOS-only (brew, macOS paths). | ❌ Not built |
| 4.6 | **GitHub Actions CI** | Basic linting + import checks on push. | ❌ Not built |
| 4.7 | **Plugin / extension API** | Let community add custom extractors (e.g., Notion, Obsidian, email) via a simple interface. | ❌ Not built (long-term) |

---

## Immediate next 3 things to build (in order)

1. **Scan folder UI** (1.1) — single highest-value gap. Users expect to point at a folder and have it indexed.
2. **Export buttons in UI** (1.6) — routes exist, just need buttons wired in Files view.
3. **Ollama status badge** (1.5) — stops silent hangs from being mysterious.

---

## Architecture reference

```
uploads/                   ← drag-dropped files land here
config/config.yaml         ← models, watch folders, chunk sizes, retrieval settings
core/
  ingest.py                ← page extract → chunk → entity → embed (Qdrant)
  ingest_job.py            ← subprocess wrapper (worker-safe, captures stderr)
  query.py                 ← retrieve → re-rank → stream answer → detect source
  export.py                ← JSON / CSV / SQLite export
  eval.py                  ← grounding evaluation pipeline
  normalize.py             ← text normalization utilities
  schema.py                ← DB schema constants
  triage.py                ← document triage / routing logic
ui/
  app.py                   ← Flask server + background ingest worker + watch folder
  templates/index.html     ← entire frontend (single file, vanilla JS)
  static/                  ← logos (noback.png, orglocallab.png, etc.)
db/
  done.db                  ← SQLite: documents, chunks, entities, ingest_jobs, eval_results
  qdrant/                  ← Qdrant local vector store (hybrid dense+sparse)
logs/
  app.log                  ← server output
```

## Models

| Role | Model | How |
|---|---|---|
| Answer generation | `llama3.1:8b` (default) or any Ollama model | Ollama streaming |
| Vision / scanned PDFs | `qwen2.5vl:7b` | Ollama, triggered for sparse pages |
| Embeddings (dense) | `nomic-embed-text` | via fastembed |
| Embeddings (sparse) | BM25 | via fastembed |

## Key decisions / why we did things this way

- **Qdrant local** (not ChromaDB) — hybrid dense+sparse BM25 gives much better recall on short queries like "articles of inc" or "resume" where keyword matching matters.
- **Subprocess for ingest** — worker calls `ingest_job.py` as a subprocess so a crash in ingestion doesn't kill the Flask server.
- **SSE streaming over WebSocket** — simpler, stateless, works with Flask dev server, no socket.io dependency.
- **`sys.exit` → `SystemExit` bug** — `retrieve_chunks()` historically called `sys.exit(1)` on Qdrant errors; fixed with `try/except SystemExit` wrapper so the stream doesn't kill Flask.
- **AbortController for stream timeout** — `reader.cancel()` does NOT unblock a pending `await reader.read()`. `controller.abort()` throws `AbortError` which actually breaks the await. Timeout: 45s of silence.
- **Context re-ranking** — after Qdrant retrieval, all chunks from the top-scoring file are promoted to the front of the context window before other files. Prevents "tell me about Dallas's projects" from being answered with Invisalign content just because Invisalign chunks score slightly higher globally.

---

*Last updated: 2026-03-15*
