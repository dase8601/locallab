# done — Document Organization and Navigation Engine
## (also called: locallab)

---

## Current State
*Last updated: 2026-03-13*

### What is working

| Feature | Status |
|---|---|
| Document ingestion pipeline | ✓ Working |
| SQLite chunk + entity storage | ✓ Fixed (NOT NULL bug resolved) |
| ChromaDB vector embeddings | ✓ Working |
| RAG query pipeline | ✓ Working |
| Confidence from ChromaDB similarity | ✓ Working |
| UI: confidence bar (0–100%) | ✓ Working |
| UI: source document + page citation | ✓ Working |
| UI: expandable Sources panel (all chunks) | ✓ Working |
| Background ingest worker | ✓ Working |
| Queue view with progress bars | ✓ Working |
| Flask API (`/api/ask`, `/api/files`, `/api/ingest`) | ✓ Working |

### Index state (as of last run)
- **13/15 PDFs** fully indexed
- **265+ chunks** in SQLite + ChromaDB
- **428+ entities** extracted
- 2 remaining PDFs (`Module6_SVM_Kernel_Trick.pdf`, `Module1_Simple_Linear_Regression.pdf`) — still processing in background

### Files changed in this session

| File | Change |
|---|---|
| `core/ingest.py` | Fixed `NOT NULL` bug: added `updated_at` to entities INSERT, `created_at` to chunks INSERT. Fixed `read_pdf_pages` to catch per-page pypdf exceptions instead of crashing the whole file. |
| `core/query.py` | `ask()` now overrides LLM confidence with ChromaDB cosine similarity from the top chunk. Adds a `sources` array (all retrieved chunks with filename, page, similarity, snippet) to every response. |
| `ui/app.py` | Comment updated — `sources` key passes through to UI. |
| `ui/templates/index.html` | Sources panel now lists ALL retrieved chunks with per-source similarity bars, page numbers, and text snippets. Primary citation quote still shown at top of panel. |

### End-to-end test results (2026-03-13)

**Q1: "What is gradient boosting?"**
- Answer: Gradient boosting involves initializing a model, fitting trees to residuals, and updating the model iteratively (algorithm pseudocode cited)
- Source: `Module5_Gradient_Boosting.pdf` · page 3
- Confidence: 33% (LOW) — PDFs are slide decks with sparse text
- Sources retrieved: 5 chunks from gradient boosting + boosting slides
- Note: Answer is correct but confidence is low because slide text is minimal

**Q2: "How does k-means clustering work?"**
- Answer: "I could not find this information in your documents"
- Source: `Module2_USL_Clustering.pdf`
- Confidence: 37%
- Root cause: Slide chunks are sparse headers ("K-means Algorithm", "What is a centroid?") without algorithm body text — LLM correctly refuses to hallucinate

**Q3: "What is a support vector machine?"**
- Answer: "I could not find this information in your documents"
- Source: none
- Confidence: 35%
- Root cause: Same issue — SVM slide chunks have bullet titles but no algorithm explanation body text

### Root cause of low answer quality
The source documents are **lecture slide PDFs** (PowerPoint → PDF). pypdf extracts only the text layer, which for slides is typically just slide titles and sparse bullet points. Algorithm bodies, diagrams, and formula explanations are in the slide image layer and are not extracted.

### Next priorities

1. **Vision extraction for all slides** — Currently `read_page_with_vision()` only triggers for pages with <30 chars. For slide PDFs, trigger vision extraction on all pages when character density is low (e.g., <200 chars/page). This will dramatically improve chunk content quality and answer accuracy.

2. **Chunk size tuning** — Slide content per page is small (50–350 chars). The current "medium" profile (400 words per chunk) creates chunks that span 3–8 slides. Better to use 1-slide-per-chunk for slide PDFs.

3. **Retry the 2 failed PDFs** — `Module6_SVM_Kernel_Trick.pdf` and `Module1_Simple_Linear_Regression.pdf` have pypdf FloatObject issues. The per-page error handling fix should recover them on retry.

4. **eval.py integration** — Run the eval pipeline against the 13 indexed files to get a trust score and populate the Insights view.

5. **Module1_USL_PCA.pdf** — This file was never queued despite being in the folder. Add it to the index.

---

## Project overview

**done** (Document Organization and Navigation Engine) is a fully local RAG (Retrieval-Augmented Generation) document assistant. All processing happens on your machine — nothing is sent to the cloud.

### Architecture

```
User question
     │
     ▼
ChromaDB vector search (top-k chunks by cosine similarity)
     │
     ▼
SQLite entity lookup (keyword match on entities table)
     │
     ▼
Qwen2.5:14b answer generation (grounded in retrieved context)
     │
     ▼
JSON response: answer + source_file + source_page + confidence + sources[]
     │
     ▼
Flask UI (confidence bar, citation tag, expandable Sources panel)
```

### Models used
- **Extraction / QA**: `qwen2.5:14b` (runs via Ollama)
- **Vision / scanned pages**: `qwen2.5vl:7b` (runs via Ollama)
- **Embeddings**: ChromaDB default (`all-MiniLM-L6-v2` via sentence-transformers)

### Key files

| File | Purpose |
|---|---|
| `core/ingest.py` | Document ingestion pipeline — page extraction, chunking, entity extraction, embedding |
| `core/ingest_job.py` | Subprocess wrapper for worker-safe ingestion |
| `core/query.py` | RAG query pipeline — retrieval + answer generation |
| `core/eval.py` | Evaluation pipeline — grounding score, verdict, trust score |
| `ui/app.py` | Flask server — routes + background worker thread |
| `ui/templates/index.html` | Single-page UI (Ask, Files, Queue, Insights views) |
| `db/done.db` | SQLite database (documents, chunks, entities, ingest_jobs, eval_results) |
| `db/chroma/` | ChromaDB vector store |
| `config/config.yaml` | Configuration file |

### Database schema (key tables)

**documents** — one row per indexed file
**chunks** — one row per text chunk (linked to ChromaDB by `chroma_id`)
**entities** — extracted named entities (PERSON, ORG, DATE, SKILL, etc.)
**ingest_jobs** — background job queue (pending → processing → done/failed)
**eval_results** — historical evaluation runs

### Running the app

```bash
cd /Users/dallassellers/Documents/UniversityOfColorodoBoulder/done
source venv/bin/activate
python ui/app.py
# → http://localhost:5000
```

### Re-indexing from scratch

```bash
sqlite3 db/done.db "DELETE FROM chunks; DELETE FROM entities; DELETE FROM documents;"
rm -rf db/chroma/
sqlite3 db/done.db "UPDATE ingest_jobs SET status='pending' WHERE status IN ('done','failed');"
# then restart app.py — worker will process all pending jobs
```

### Supported file types
`.pdf`, `.docx`, `.doc`, `.txt`, `.md`, `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, `.csv`, `.xlsx`, `.xls`, `.json`, `.html`

### Confidence score
The confidence displayed in the UI is the **cosine similarity** of the top-retrieved ChromaDB chunk against the query — not the LLM's self-reported score. Higher = more semantically relevant source material. Current slide PDFs score 30–40% due to sparse text extraction.

| Score | Label | Meaning |
|---|---|---|
| ≥ 80% | HIGH | Strong match — answer likely reliable |
| 55–79% | MED | Moderate match |
| < 55% | LOW | Weak match — answer may be incomplete |
