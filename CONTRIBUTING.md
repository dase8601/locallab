# Contributing to locallab

Thanks for your interest in making locallab better. This is an open-source, local-first document AI — contributions that keep it fast, private, and dependency-light are most welcome.

---

## How to contribute

### Reporting bugs

Open an issue at [github.com/dase8601/locallab/issues](https://github.com/dase8601/locallab/issues) and include:

- What you did
- What you expected to happen
- What actually happened (paste the error, log line, or screenshot)
- Your OS, Python version, and Ollama version (`ollama --version`)

### Suggesting features

Check [PLAN.md](PLAN.md) first — if it's already on the roadmap, comment on an existing issue or open a new one explaining your use case. Features that keep locallab fully local (no cloud dependencies) are prioritized.

### Submitting a pull request

1. Fork the repo and create a branch from `main`
2. Make your changes (see coding standards below)
3. Test locally — run `python ui/app.py` and exercise the affected path
4. Open a PR against `main` with a clear description of what changed and why

---

## Local setup

```bash
git clone https://github.com/dase8601/locallab
cd locallab
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python ui/app.py          # → http://localhost:5001
```

**Requires:** Python 3.10+, [Ollama](https://ollama.com) running locally with at least `llama3.1:8b` and `nomic-embed-text` pulled.

---

## Project structure

```
core/
  ingest.py       ← ingestion pipeline (extract → chunk → embed → Qdrant)
  ingest_job.py   ← subprocess wrapper (keeps crashes isolated from Flask)
  query.py        ← RAG pipeline (retrieve → re-rank → stream)
  tasks.py        ← document task agents (summarize, action items, compare, …)
  export.py       ← JSON / CSV / SQLite export
  eval.py         ← grounding evaluation pipeline
  schema.py       ← single source of truth for DB schema + migrations
ui/
  app.py          ← Flask server + background worker + watch folder observer
  templates/
    index.html    ← entire frontend (single file, vanilla JS — no build step)
  static/         ← logo assets
config/
  config.yaml     ← models, watch folders, chunk sizes, retrieval settings
db/
  done.db         ← SQLite database
  qdrant/         ← Qdrant local vector store
```

---

## Coding standards

**Python**
- Follow the existing style — no extra dependencies without a strong reason
- Ingest and query are performance-critical — profile before optimizing
- All DB changes go through `schema.py` (`SCHEMA` constant + `migrate_db()`) — never `ALTER TABLE` ad hoc
- Subprocess isolation for ingest is intentional — don't move heavy work into the Flask process

**Frontend**
- `index.html` is a single-file vanilla JS app — no bundler, no npm
- Keep it that way — the zero-build-step constraint is a feature, not a bug
- Use `escHtml()` on all user-supplied or DB-sourced strings before inserting into innerHTML
- SSE streaming uses `AbortController` — don't use `reader.cancel()` (it doesn't unblock pending reads)

**Vector store**
- We use Qdrant (local), not ChromaDB
- Use `client.query_points()` — `client.search()` was removed in qdrant-client v1.13+
- Collection name is `locallab`

---

## What we're NOT looking for

- Cloud integrations (S3, OpenAI API, etc.) — locallab must work 100% offline
- New Python dependencies for things the stdlib handles
- UI framework migrations — the single-file vanilla JS approach is deliberate

---

## Questions?

Open an issue or start a discussion on GitHub. We're happy to help you get oriented.
