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
| **Ingestion** | Auto-generated questions per doc | 4 questions with filename baked in |
| **Ingestion** | Auto-generated 2-3 sentence summary | Stored in DB, shown in file viewer + hover tooltip |
| **Query** | Streaming SSE answers (token-by-token) | AbortController 45s silence timeout |
| **Query** | Dual-mode: document RAG + general Ollama chat | Threshold: similarity ≥ 0.40 → docs |
| **Query** | Context re-ranking | All pages from top file promoted first |
| **Query** | Markdown rendering (marked.js + DOMPurify) | Full md: bullets, code, tables, bold |
| **Query** | Trust/confidence bar | Qdrant cosine similarity, not LLM self-report |
| **Query** | Source citations with expandable panel | Per-chunk: file, page, similarity, snippet |
| **Query** | Post-stream source filtering | Badge + panel update to cited file on `done` |
| **Query** | Conversation history (multi-turn) | Last 10 turns passed to LLM |
| **UI** | Ask / Files / Queue / Insights / Explore tabs | Single-page app |
| **UI** | File viewer modal | Chunks + entities + questions inspector, tabbed |
| **UI** | Document summary in file viewer | Shown below filename; hover tooltip in Files view |
| **UI** | Delete documents | Removes from SQLite + Qdrant |
| **UI** | Re-index button per document | Per-row in Files view |
| **UI** | Dark / light mode | Correct logos per theme, persisted |
| **UI** | Feedback (thumbs up/down) | Saved to DB |
| **UI** | First-run welcome overlay | Shows on zero documents |
| **UI** | Toast notifications | Replaced all alert() calls |
| **UI** | Drag-and-drop file upload | Drop zone on Ask view |
| **UI** | Recent questions sidebar | Last 6 questions, click to re-ask |
| **UI** | File search/filter bar | Filters by filename client-side |
| **UI** | Model picker dropdown | All installed Ollama models, persisted |
| **UI** | Ollama status badge | Green/red dot in sidebar footer, polled 60s |
| **UI** | Watch folders modal | Add/remove watch folders from UI |
| **UI** | Keyboard shortcuts | Cmd+K focus input, Esc close modals |
| **UI** | Chat history persistence | localStorage, survives page reload |
| **UI** | Copy answer button | One-click clipboard copy |
| **Tasks** | 8 document task agents | Summarize, Action items, Dates, People, Financial, Risk, Draft reply, Compare |
| **Tasks** | Task picker modal | Grid UI triggered from file viewer "Run a task →" |
| **Tasks** | Streaming task results | SSE into Ask view, same protocol as /api/ask/stream |
| **Export** | core/export.py complete | JSON, CSV zip, SQLite download |
| **Export** | Flask routes wired | /api/export/json, /api/export/csv, /api/export/sqlite |
| **Export** | Export dropdown in Files view | JSON / CSV / SQLite buttons |
| **Infra** | install.sh | curl-installable, checks Ollama, pulls models |
| **Infra** | README.md | Quickstart, architecture, privacy, models |
| **Infra** | CONTRIBUTING.md | How to contribute, PR process, coding standards |
| **Infra** | .gitignore | venv, db, uploads, logs excluded |
| **Infra** | MIT License | |
| **Infra** | GitHub: dase8601/locallab | Live |

---

## What is NOT built yet — the roadmap

### Phase 1 — Core quality (do first, unblocks everything else)

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 1.1 | **Scan folder UI** | Paste a folder path in the Add Files modal — queues all supported files recursively. | ✓ Built |
| 1.2 | **Add / remove watch folders from UI** | Watch Folders modal in sidebar footer. | ✓ Built |
| 1.3 | **Re-index button per document** | Per-row circular arrow button in Files view. | ✓ Built |
| 1.4 | **Vision threshold tunable** | Currently triggers vision at <30 chars. Per-document config not yet exposed. | ❌ Not built |
| 1.5 | **Ollama connection status badge** | Green/red dot in sidebar footer, polled every 60s. | ✓ Built |
| 1.6 | **Export buttons in UI** | Export dropdown (JSON/CSV/SQLite) in Files view header. | ✓ Built |
| 1.7 | **Insights view wired** | Stats, entity distribution, file types, health, feedback shown. eval.py run-button not yet wired. | ~ Partial |

### Phase 2 — User experience

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 2.1 | **Search / filter in Files view** | Search bar above files table, client-side filter. | ✓ Built |
| 2.2 | **File categories / tags** | Let users tag documents (Work, Legal, Personal, etc.) and filter by tag. | ❌ Not built |
| 2.3 | **Drag-and-drop folder** | Dropping a folder not yet supported (files only). | ❌ Not built |
| 2.4 | **Keyboard shortcuts** | Cmd+K focus input, Esc close modals. | ✓ Built |
| 2.5 | **Model picker in UI** | Dropdown of all installed Ollama models, persisted in localStorage. | ✓ Built |
| 2.6 | **Chat history persistence** | localStorage, survives page reload, last 20 turns. | ✓ Built |
| 2.7 | **"Clear chat" button** | "New chat" button in sidebar clears history. | ✓ Built |
| 2.8 | **Copy answer button** | Clipboard copy button on every answer card. | ✓ Built |
| 2.9 | **Per-document export** | Export chunks + entities for a single document. | ❌ Not built |
| 2.10 | **Bulk select + delete** | Select multiple files and delete all at once. | ❌ Not built |

### Phase 3 — Intelligence

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 3.1 | **Auto-generated questions per doc** | 4 questions with filename baked in, shown in file viewer Questions tab, clickable. | ✓ Built |
| 3.2 | **Document summary on ingest** | 2-3 sentence summary generated during ingest, shown in file viewer + hover tooltip in Files view. | ✓ Built |
| 3.3 | **Multi-document queries** | "Compare my two contracts" — query across multiple specified documents simultaneously with merged context. | ❌ Not built |
| 3.4 | **Entity graph view** | Visualize connections between people, orgs, and dates across all documents (who appears in which files, what dates are mentioned). | ❌ Not built |
| 3.5 | **Smart de-duplication** | Detect near-duplicate documents (same contract, different version) and warn the user. | ❌ Not built |
| 3.6 | **Answer grounding score** | Show which specific sentence in the source document the answer came from, not just which page. Highlight the exact span. | ❌ Not built |
| 3.7 | **"What's new" digest** | When watch folder detects new files, generate a 1-sentence summary of what changed and surface it in the UI. | ❌ Not built |

### Phase 3.5 — Document Task Agents

> Pre-built AI task chains you trigger on one or more documents. Each task retrieves the relevant chunks, runs a specialized prompt, and streams a structured result — fully local, no cloud.

| # | Task | What it does | Multi-doc | Status |
|---|---|---|---|---|
| A.1 | **Summarize** | 3-5 bullet summary specific to the document | No | ✓ Built |
| A.2 | **Extract action items** | All tasks, obligations, required actions as a checklist | No | ✓ Built |
| A.3 | **Find dates & deadlines** | Every date/deadline with context | No | ✓ Built |
| A.4 | **Key people & roles** | All people, orgs, and their roles | No | ✓ Built |
| A.5 | **Financial terms** | All amounts, fees, payment obligations | No | ✓ Built |
| A.6 | **Draft a reply** | Professional response to the document | No | ✓ Built |
| A.7 | **Compare two documents** | Side-by-side comparison of similarities and differences | Yes (2 docs) | ✓ Built |
| A.8 | **Risk flags** | Identify unusual clauses, missing terms, red flags in contracts/legal docs | No | ✓ Built |

**Architecture:**
- `core/tasks.py` — task definitions + `run_task_stream()` generator
- `GET /api/tasks` — list available tasks
- `POST /api/tasks/run/stream` — SSE stream, same protocol as `/api/ask/stream`
- UI: "Run task →" button in file viewer modal → task picker → streams result into Ask view

### Phase 4 — Open source / distribution

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 4.1 | **GitHub releases with versioned tags** | v1.0 tag exists in commit but no GitHub Release object with release notes. | ❌ Not built |
| 4.2 | **CONTRIBUTING.md** | How to file issues, submit PRs, coding standards. | ✓ Built |
| 4.3 | **Demo GIF / screenshot in README** | Projects without visuals get far fewer stars. Record a 30s demo. | ❌ Not built |
| 4.4 | **Docker / docker-compose** | One-command `docker compose up` for users who don't want to manage Python venvs. | ❌ Not built |
| 4.5 | **Windows + Linux install.sh** | Current script is macOS-only (brew, macOS paths). | ❌ Not built |
| 4.6 | **GitHub Actions CI** | Basic linting + import checks on push. | ❌ Not built |
| 4.7 | **Plugin / extension API** | Let community add custom extractors (e.g., Notion, Obsidian, email) via a simple interface. | ❌ Not built (long-term) |

---

## Immediate next things to build (in order)

1. **Vision threshold tunable** (1.4) — per-upload slider or config option for OCR sensitivity.
2. **File categories / tags** (2.2) — tag documents and filter by tag in Files view.
3. **Per-document export** (2.9) — export a single doc's chunks + entities.
4. **Insights eval button** (1.7) — wire "Run evaluation" button to eval.py, show results.
5. **GitHub release v1.1** (4.1) — tag and release with updated notes.
6. **Docker** (4.4) — `docker compose up` for non-Python users.

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
