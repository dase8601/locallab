# locallab — Product Plan

> **Vision:** A private, local-first AI that knows everything in your files.
> Zero cloud. No subscriptions. Runs entirely on your Mac.
> As simple as dropping a file in — as powerful as a team of analysts.

---

## What locallab is

locallab is an open-source document AI you install once and run forever on your own machine.
You drop in PDFs, contracts, resumes, notes, spreadsheets — and then you talk to them in plain English.
It indexes everything, understands scanned pages via vision models, extracts entities, and gives you cited answers with a trust score.
Switch between Your docs (RAG) and General (direct Ollama chat) with a single toggle.

---

## Current state — what is BUILT ✓

| Area | Feature | Notes |
|---|---|---|
| **Ingestion** | PDF/DOCX/TXT/CSV/XLSX/PNG/JPG | Supported file types |
| **Ingestion** | Per-page text extraction (pypdf + fitz) | Wraps each page in try/except |
| **Ingestion** | Vision extraction for sparse/scanned pages | qwen2.5vl:7b, triggers at <30 chars/page |
| **Ingestion** | Chunking with configurable size/overlap | 3 profiles: small/medium/large, 200-word overlap |
| **Ingestion** | Named entity extraction | People, orgs, dates, amounts, skills |
| **Ingestion** | Combined enrichment (entities + questions + summary in 1 LLM call) | ~3x faster than 3 separate calls |
| **Ingestion** | Qdrant hybrid search (dense + sparse BM25) | nomic-embed-text + fastembed |
| **Ingestion** | Background worker with priority queue | Smallest files first |
| **Ingestion** | Watch folder (watchdog) | on_created + on_moved (macOS browser downloads) |
| **Ingestion** | Auto-generated questions per doc | 4 questions with filename baked in |
| **Ingestion** | Auto-generated 2-3 sentence summary | Stored in DB, shown in file viewer + hover tooltip |
| **Query** | Streaming SSE answers (token-by-token) | AbortController 45s silence timeout |
| **Query** | Your docs / General toggle | Persists to localStorage, skips RAG in General mode |
| **Query** | Context re-ranking | All pages from top file promoted first |
| **Query** | Query rewriting | Vague conversational queries rewritten to keyword form before retrieval |
| **Query** | Similarity threshold 0.30 | Lower threshold = fewer "not found" fallbacks |
| **Query** | Retrieval pool of 15 candidates | More candidates before re-ranking |
| **Query** | Markdown rendering (marked.js + DOMPurify) | Full md: bullets, code, tables, bold |
| **Query** | Trust/confidence bar | Qdrant cosine similarity, not LLM self-report |
| **Query** | Source citations with expandable panel | Per-chunk: file, page, similarity, snippet |
| **Query** | Post-stream source filtering | Badge + panel update to cited file on `done` event |
| **Query** | Conversation history (multi-turn) | Last 10 turns passed to LLM |
| **UI** | Ask / Files / Queue / Insights / Explore tabs | Single-page app |
| **UI** | File viewer modal | Chunks + entities + questions inspector, tabbed |
| **UI** | Document summary in file viewer | Shown below filename; hover tooltip in Files view |
| **UI** | Delete documents (single) | Removes from SQLite + Qdrant |
| **UI** | Bulk select + delete | Checkbox per row, select-all, bulk delete toolbar |
| **UI** | Re-index button per document | Per-row in Files view |
| **UI** | Files tab discovery hint | Green banner + first-row pulse animation, dismissable |
| **UI** | Dark / light mode | Correct logos per theme, persisted |
| **UI** | Feedback (thumbs up/down) | Saved to DB |
| **UI** | Toast notifications | Replaced all alert() calls |
| **UI** | Drag-and-drop file upload | Drop zone on Ask view |
| **UI** | Recent questions sidebar | Last 6 questions, click to re-ask |
| **UI** | File search/filter bar | Filters by filename client-side |
| **UI** | File tags + tag filter | Custom labels, filter by tag in Files view |
| **UI** | Per-document export | JSON/CSV from file viewer |
| **UI** | Model picker dropdown | All installed Ollama models, persisted |
| **UI** | Ollama status badge | Green/red dot in sidebar footer, polled 60s |
| **UI** | Watch folders modal | Add/remove watch folders from UI |
| **UI** | Keyboard shortcuts | Cmd+K focus input, Esc close modals |
| **UI** | Chat history persistence | localStorage, survives page reload |
| **UI** | Copy answer button | One-click clipboard copy |
| **UI** | Vision threshold setting | Slider in Settings modal, writes to config.yaml |
| **Tasks** | 8 document task agents | Summarize, Action items, Dates, People, Financial, Risk, Draft reply, Compare |
| **Tasks** | Task picker modal | Grid UI triggered from file viewer "Run a task →" |
| **Tasks** | Streaming task results | SSE into Ask view, same protocol as /api/ask/stream |
| **Tasks** | Questions click-to-ask | Clicking a question in file viewer sends it immediately |
| **Export** | core/export.py complete | JSON, CSV zip, SQLite download |
| **Export** | Flask routes wired | /api/export/json, /api/export/csv, /api/export/sqlite |
| **Export** | Export dropdown in Files view | JSON / CSV / SQLite buttons |
| **Eval** | Eval pipeline | Ground-truth eval via extracted entities, trust score |
| **Eval** | Live eval status | Spinning button + progress indicator while running |
| **Eval** | Eval limit input | Run eval on N docs instead of all |
| **Eval** | scripts/reenrich.py | Re-run enrichment on existing docs without re-indexing |
| **Infra** | install.sh | curl-installable, checks Ollama, pulls models |
| **Infra** | README.md | Quickstart, architecture, privacy, models |
| **Infra** | CONTRIBUTING.md | How to contribute, PR process, coding standards |
| **Infra** | .gitignore | venv, db, uploads, logs excluded |
| **Infra** | MIT License | |
| **Infra** | Docker / docker-compose | One-command `docker compose up` |
| **Infra** | GitHub: dase8601/locallab | Live |
| **Scripts** | scripts/gen_test_docs.py | Generates 100 realistic test docs (contracts, invoices, etc.) |
| **Scripts** | scripts/reenrich.py | Re-enriches existing docs with new combined prompt |

---

## What is NOT built yet — the roadmap

### Phase 1 — Core quality

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 1.4 | **Vision threshold tunable** | Slider in Settings modal, writes config.yaml | ✓ Built |

### Phase 2 — User experience

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 2.2 | **File categories / tags** | Tag documents and filter by tag in Files view | ✓ Built |
| 2.3 | **Drag-and-drop folder** | Dropping a folder not yet supported (files only) | ❌ Not built |
| 2.9 | **Per-document export** | JSON/CSV from file viewer | ✓ Built |
| 2.10 | **Bulk select + delete** | Select multiple files and delete all at once | ✓ Built |

### Phase 3 — Intelligence

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 3.3 | **Multi-document queries** | "Compare my two contracts" — merged context across docs | ❌ Not built |
| 3.4 | **Entity graph view** | Visualize connections between people, orgs, dates across docs | ❌ Not built |
| 3.5 | **Smart de-duplication** | Detect near-duplicate documents | ❌ Not built |
| 3.6 | **Answer grounding score** | Highlight exact sentence the answer came from | ❌ Not built |
| 3.7 | **"What's new" digest** | When watch folder detects new file, surface 1-sentence summary | ❌ Not built |

### Phase 3.5 — Document Task Agents ✓ All built

All 8 tasks built: Summarize, Action items, Dates & deadlines, Key people, Financial terms, Risk flags, Draft reply, Compare two docs.

### Phase 4 — Open source / distribution

| # | Feature | Why it matters | Status |
|---|---|---|---|
| 4.1 | **GitHub releases with versioned tags** | v1.1 tag + release notes | ❌ Not built |
| 4.3 | **Demo GIF / screenshot in README** | Projects without visuals get far fewer stars | ❌ Not built |
| 4.5 | **Windows + Linux install.sh** | Current script is macOS-only | ❌ Not built |
| 4.6 | **GitHub Actions CI** | Basic linting + import checks on push | ❌ Not built |

---

## Immediate next things to build (in order)

1. **GitHub release v1.1** (4.1) — tag + release notes
2. **GitHub Actions CI** (4.6) — basic lint check on push
3. **"What's new" digest** (3.7) — surface new file summaries in UI when watch folder picks them up
4. **Multi-document queries** (3.3) — the most-requested intelligence feature
5. **Demo GIF** (4.3) — record a 30s demo for README

---

## Architecture reference

```
uploads/                   ← drag-dropped files land here
config/config.yaml         ← models, watch folders, chunk sizes, retrieval settings
core/
  ingest.py                ← page extract → chunk → entity → embed (Qdrant)
  ingest_job.py            ← subprocess wrapper (worker-safe, captures stderr)
  query.py                 ← retrieve → rewrite → re-rank → stream answer → detect source
  export.py                ← JSON / CSV / SQLite export
  eval.py                  ← grounding evaluation pipeline
  tasks.py                 ← 8 document task agents + SSE stream generator
  schema.py                ← DB schema constants
scripts/
  gen_test_docs.py         ← generate 100 realistic test docs for stress testing
  reenrich.py              ← re-run enrichment on existing docs without re-indexing
ui/
  app.py                   ← Flask server + background ingest worker + watch folder
  templates/index.html     ← entire frontend (~1800 lines, single-page vanilla JS)
  static/                  ← logos (noback.png, orglocallab.png, etc.)
db/
  done.db                  ← SQLite: documents, chunks, entities, ingest_jobs, eval_results
  qdrant/                  ← Qdrant local vector store (collection: done_docs)
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

- **Qdrant local** (not ChromaDB) — hybrid dense+sparse BM25 gives much better recall on short queries.
- **Subprocess for ingest** — worker calls `ingest_job.py` as a subprocess so a crash in ingestion doesn't kill Flask.
- **SSE streaming over WebSocket** — simpler, stateless, works with Flask dev server, no socket.io dependency.
- **Combined enrichment prompt** — entities + questions + summary in one LLM call, ~3x faster than 3 separate calls. Falls back to individual calls on JSON parse failure.
- **Query rewriting** — vague conversational queries rewritten to keyword form before Qdrant retrieval. Skipped if query already contains a filename (already precise enough).
- **on_moved watch handler** — macOS browser downloads create `.crdownload` then rename in-place, firing `on_moved` not `on_created`. Both are handled.
- **Similarity threshold 0.30** — lower than default to reduce "not found" fallbacks; retrieval pool of 15 candidates provides more context before re-ranking.

---

*Last updated: 2026-03-16*
