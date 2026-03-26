# Contributing to locallab

Thanks for your interest — contributions are welcome and appreciated. This is an open project and there's a lot of room to make it better.

## Getting started

```bash
git clone https://github.com/dase8601/locallab.git
cd locallab
./install.sh          # installs dependencies and sets up venv
source venv/bin/activate
python ui/app.py      # runs at http://localhost:5000
```

You'll also need [Ollama](https://ollama.com) running locally with at least one model pulled:

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

For vision (scanned PDFs / images / video):
```bash
ollama pull qwen2.5vl:7b
```

## How to contribute

1. Fork the repo
2. Create a branch (`git checkout -b my-feature`)
3. Make your changes
4. Open a pull request against `main`

No strict rules — just keep PRs focused and describe what you changed and why.

## What's welcome

- Bug fixes
- New features from the roadmap (see `PLAN.md`)
- UI improvements
- Performance improvements
- Better prompts / RAG quality
- Support for new file types
- Tests

## Project structure

```
core/         — ingestion, querying, entity extraction, agents
ui/
  app.py      — Flask server + background worker
  templates/  — single-page frontend (index.html)
  static/     — logos, assets
config/       — config.yaml (models, chunk sizes, retrieval settings)
db/           — SQLite + Qdrant vector store (local only, not committed)
scripts/      — setup helpers (V-JEPA, etc.)
```

## Questions

Open an issue or reach out directly. Happy to help you get oriented.
