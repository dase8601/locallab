# locallab

**Private AI for your files. 100% local. Zero cloud.**


demo video here ui/static/Screen Recording 2026-03-25 at 8.19.04 PM.mov


Ask questions about your PDFs, contracts, resumes, and documents — get answers with exact source citations. Everything runs on your machine using [Ollama](https://ollama.com).

---

## What it does

- **Ask anything** — "What are the payment terms?" → answer + page citation + trust score
- **Streaming answers** — responses appear token-by-token, no waiting
- **Vision extraction** — scanned PDFs and images are read via AI vision model
- **Audio & video ingestion** — drop in `.mp3`, `.wav`, `.mp4`, `.mov` — audio is transcribed with Whisper, video frames described by vision model, 100% locally
- **Research mode** — ReAct agent combines web search + your documents in one cited answer
- **Entity extraction** — people, companies, dates, amounts automatically pulled from every document
- **Persistent conversations** — chat history saved to local DB, survives page reload, named sidebar
- **Export your data** — download everything as JSON, CSV, or SQLite at any time
- **Dark & light mode** — because details matter

---

## Quickstart

### 1. Install

```bash
curl -fsSL https://raw.githubusercontent.com/dase8601/locallab/main/install.sh | bash
```

Requires macOS with Python 3.10+ and [Ollama](https://ollama.com) installed.

### 2. Start

```bash
locallab
# or: source venv/bin/activate && python ui/app.py
```

Open [http://localhost:5000](http://localhost:5000)

### 3. Add files & ask

Drop in PDFs, images, audio, video, Word docs, or spreadsheets → click "Add files" → ask questions.

---

## Requirements

| Requirement | Notes |
|---|---|
| macOS 12+ | Apple Silicon or Intel |
| Python 3.10+ | 3.11 or 3.12 recommended |
| [Ollama](https://ollama.com) | Local model runner |
| 16 GB RAM | 8 GB minimum (slower) |
| ~15 GB disk | For models + your documents |
| `ffmpeg` (optional) | System binary for video ingestion — `brew install ffmpeg` |

**Ollama models pulled automatically by install.sh:**

| Model | Size | Purpose |
|---|---|---|
| `nomic-embed-text` | 274 MB | Embeddings (semantic search) |
| `llama3.1:8b` | 4.7 GB | Entity extraction |
| `qwen2.5:14b` | 9.0 GB | Question answering |
| `qwen2.5vl:7b` | 4.4 GB | Vision (scanned PDFs) |

---

## How it works

```
Your question
     │
     ▼
Qdrant vector search          ← your file embeddings (nomic-embed-text)
     │
     ▼
Top chunks retrieved
     │
     ▼
qwen2.5:14b answers           ← document context only, no internet
     │
     ▼
Answer + source citation + trust score
```

**Ingestion pipeline:**
```
Your file → text extraction (pypdf / fitz) → vision fallback for sparse pages
         → chunking → entity extraction → embeddings → Qdrant + SQLite
```

---

## Privacy

- **All models run locally** via Ollama — nothing leaves your machine
- **No telemetry, no accounts, no API keys**
- **Your documents** stay in `uploads/` and `db/done.db` — both git-ignored
- **Export anytime** — JSON, CSV, or SQLite via the Files tab

---

## Configuration

`config/config.yaml`:

```yaml
models:
  vision:    qwen2.5vl:7b
  reasoning: qwen2.5:14b
  embedding: nomic-embed-text
  ollama_url: http://localhost:11434

watch:
  folders:
    - ~/Documents          # auto-ingest new files dropped here
  extensions: [.pdf, .docx, .txt, .png, .jpg, .csv, .xlsx]

chunking:
  size: 600
  overlap: 100
```

---

## Supported file types

`.pdf` `.docx` `.doc` `.txt` `.md` `.csv` `.xlsx` `.xls` `.png` `.jpg` `.jpeg` `.tiff` `.bmp` `.json` `.html` `.mp4` `.mov` `.avi` `.mkv` `.mp3` `.wav` `.m4a` `.ogg`

---

## Development

```bash
git clone https://github.com/dase8601/locallab
cd locallab
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python ui/app.py
```

**Project structure:**
```
core/
  ingest.py       — document ingestion pipeline (PDF, image, audio, video)
  query.py        — RAG pipeline (retrieve → rewrite → answer → confidence)
  agent.py        — research mode ReAct agent (web search + document query)
  export.py       — data export (JSON, CSV, SQLite)
  eval.py         — evaluation & scoring
  schema.py       — SQLite schema
  video_gen.py    — text-to-video generation subprocess (LTX-Video, optional)
ui/
  app.py          — Flask server + background worker
  templates/
    index.html    — single-page UI
config/
  config.yaml     — model + watch folder config
```

---

## License

MIT — see [LICENSE](LICENSE)
