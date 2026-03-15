"""
DONE · ui/app.py
─────────────────
Flask server. Thin routes only — all business logic lives in core/.

Endpoints:
  POST /api/ask                    question → answer + source + confidence
  GET  /api/files                  all indexed documents
  POST /api/ingest                 queue a file or folder for ingestion
  GET  /api/ingest/status          all jobs (pending, processing, done, failed)
  GET  /api/ingest/status/<job_id> single job status
  GET  /api/insights               library stats, entity distribution, recent docs
  GET  /api/explore/entities       paginated entity browser (?type=&q=&doc_id=&page=)

Background worker:
  One daemon thread pulls pending jobs from ingest_jobs table,
  processes smallest files first (priority 1→4), updates status live.

Usage:
  cd /Users/dallassellers/Documents/UniversityOfColorodoBoulder/done
  source venv/bin/activate
  python ui/app.py
  open http://localhost:5000
"""

import sqlite3
import sys
import threading
import time
import warnings
from pathlib import Path

# Suppress pypdf warnings about malformed PDFs
warnings.filterwarnings("ignore", message=".*wrong pointing object.*")
warnings.filterwarnings("ignore", message=".*PdfReadWarning.*")

from flask import Flask, jsonify, request, render_template

# ── PATH SETUP ────────────────────────────────────────────────────
# Allow importing from core/
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "core"))

from ingest import init_db, ingest_file, estimate_job, list_documents, SUPPORTED
from query  import ask, ask_stream
# eval is imported lazily to avoid heavy startup cost

# ── APP ───────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates")
app.config["JSON_SORT_KEYS"] = False

# ── DATABASE ──────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(
        str(BASE_DIR / "db" / "done.db"),
        timeout=30,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

# ── BACKGROUND WORKER ─────────────────────────────────────────────
# One thread, processes one job at a time, priority order.

_worker_lock   = threading.Lock()
_worker_active = False


def worker_loop():
    """
    Daemon thread. Polls ingest_jobs for pending work.
    Runs each ingestion as a separate subprocess to avoid
    SQLite threading conflicts with Flask.
    """
    global _worker_active
    import subprocess

    while True:
        try:
            conn = get_conn()
            job = conn.execute("""
                SELECT * FROM ingest_jobs
                WHERE status = 'pending'
                ORDER BY priority ASC, id ASC
                LIMIT 1
            """).fetchone()

            if not job:
                _worker_active = False
                conn.close()
                time.sleep(3)
                continue

            _worker_active = True
            job = dict(job)

            # Mark as processing
            conn.execute(
                "UPDATE ingest_jobs SET status='processing', "
                "started_at=? WHERE id=?",
                (time.strftime("%Y-%m-%dT%H:%M:%SZ"), job["id"])
            )
            conn.commit()
            conn.close()

            print(f"[worker] Processing job {job['id']}: {job['filename']}")

            # Run ingestion as separate subprocess — no shared db connection
            script = BASE_DIR / "core" / "ingest_job.py"
            proc = subprocess.Popen(
                [sys.executable, str(script),
                 "--job-id", str(job["id"]),
                 "--filepath", job["filepath"]],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            # Stream output to console
            for line in proc.stdout:
                print(line, end="", flush=True)
            proc.wait()

            # Mark done or failed based on exit code
            final_conn = get_conn()
            if proc.returncode == 0:
                final_conn.execute(
                    "UPDATE ingest_jobs SET status='done', "
                    "finished_at=? WHERE id=?",
                    (time.strftime("%Y-%m-%dT%H:%M:%SZ"), job["id"])
                )
            else:
                final_conn.execute(
                    "UPDATE ingest_jobs SET status='failed', "
                    "error_message='Ingestion process failed', "
                    "finished_at=? WHERE id=?",
                    (time.strftime("%Y-%m-%dT%H:%M:%SZ"), job["id"])
                )
            final_conn.commit()
            final_conn.close()

        except Exception as e:
            print(f"[worker] Error: {e}")
            time.sleep(3)


# On startup: reset any jobs orphaned in 'processing' state from a previous run.
# Without this, a server restart mid-job leaves jobs stuck forever.
def _reset_stale_jobs():
    try:
        conn = get_conn()
        n = conn.execute("""
            UPDATE ingest_jobs
            SET status = 'pending', error_message = 'Reset: server restarted mid-job'
            WHERE status = 'processing'
        """).rowcount
        conn.commit()
        conn.close()
        if n:
            print(f"[worker] Reset {n} stale processing job(s) to pending")
    except Exception as e:
        print(f"[worker] Stale job reset failed: {e}")

_reset_stale_jobs()

# Start worker thread on import
_worker_thread = threading.Thread(target=worker_loop, daemon=True)
_worker_thread.start()


# ── HELPERS ───────────────────────────────────────────────────────

def ok(data):
    """Standard success response."""
    data["success"] = True
    return jsonify(data)


def err(message, status=400):
    """Standard error response."""
    return jsonify({"success": False, "error": message}), status


# ── ROUTES ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── ASK ───────────────────────────────────────────────────────────

@app.route("/api/ask", methods=["POST"])
def api_ask():
    """
    POST /api/ask
    body: { "question": "..." }
    Returns answer with source citation, page number, confidence score.
    """
    data         = request.get_json(silent=True) or {}
    question     = (data.get("question") or "").strip()
    conversation = data.get("conversation") or []
    model        = (data.get("model") or "").strip() or None

    if not question:
        return err("question is required")

    # Sanitise conversation: only keep valid role/content pairs, cap at 10 messages
    conversation = [
        {"role": m["role"], "content": str(m["content"])}
        for m in conversation
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")
    ][-10:]

    try:
        result = ask(question, top_k=5, conversation=conversation or None, model=model)

        # chunks is the raw internal list; sources is the lightweight UI version
        result.pop("chunks", None)

        return ok(result)

    except SystemExit:
        return err("No documents indexed yet. Add some files first.", 503)
    except Exception as e:
        return err(f"Query failed: {str(e)}", 500)


# ── ASK STREAM ────────────────────────────────────────────────────

@app.route("/api/ask/stream", methods=["POST"])
def api_ask_stream():
    """
    POST /api/ask/stream
    body: { "question": "...", "conversation": [...], "model": "..." }
    Returns text/event-stream with events: meta, token, done
    """
    from flask import Response, stream_with_context

    data         = request.get_json(silent=True) or {}
    question     = (data.get("question") or "").strip()
    conversation = data.get("conversation") or []
    model        = (data.get("model") or "").strip() or None

    if not question:
        return err("question is required")

    conversation = [
        {"role": m["role"], "content": str(m["content"])}
        for m in conversation
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")
    ][-10:]

    def generate():
        import json as _json
        yield ": locallab stream\n\n"   # flush HTTP headers immediately
        try:
            yield from ask_stream(question, top_k=5, conversation=conversation or None, model=model)
        except BaseException as e:
            yield f"event: error\ndata: {_json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":      "no-cache",
            "X-Accel-Buffering":  "no",
        },
    )


# ── MODELS ────────────────────────────────────────────────────────

@app.route("/api/models", methods=["GET"])
def api_models():
    """Return list of locally available Ollama models."""
    try:
        import ollama as _ollama
        raw = _ollama.list()
        # raw.models is a list of Model objects with a .model attribute
        names = sorted(m.model for m in (raw.models or []))
        return ok({"models": names})
    except Exception as e:
        return ok({"models": [], "warning": str(e)})


# ── FILES ─────────────────────────────────────────────────────────

@app.route("/api/files", methods=["GET"])
def api_files():
    """
    GET /api/files
    Returns all indexed documents with metadata.
    """
    try:
        conn = get_conn()
        docs = list_documents(conn)
        conn.close()

        # Format file sizes
        for d in docs:
            size = d.get("file_size") or 0
            if size > 1_000_000:
                d["file_size_display"] = f"{size/1_000_000:.1f} MB"
            elif size > 1_000:
                d["file_size_display"] = f"{size/1_000:.0f} KB"
            else:
                d["file_size_display"] = f"{size} B"

        return ok({"documents": docs, "total": len(docs)})

    except Exception as e:
        return err(str(e), 500)


# ── INGEST ────────────────────────────────────────────────────────

@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    """
    POST /api/ingest
    body: { "paths": ["/path/to/file.pdf", "/path/to/folder"] }

    Queues files for background ingestion.
    Returns list of job_ids for status polling.
    """
    data  = request.get_json(silent=True) or {}
    paths = data.get("paths") or []

    if not paths:
        return err("paths array is required")

    conn     = get_conn()
    job_ids  = []
    queued   = 0
    skipped  = 0
    errors   = []

    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()

        if not path.exists():
            errors.append(f"Not found: {raw_path}")
            continue

        # Expand folder to individual files
        if path.is_dir():
            files = []
            for ext in SUPPORTED:
                files.extend(path.rglob(f"*{ext}"))
        else:
            files = [path]

        for filepath in files:
            # Skip unsupported
            if filepath.suffix.lower() not in SUPPORTED:
                continue

            # Skip if already indexed
            existing = conn.execute(
                "SELECT id FROM documents WHERE filepath = ?",
                (str(filepath),)
            ).fetchone()
            if existing:
                skipped += 1
                continue

            # Skip if already queued
            queued_already = conn.execute(
                "SELECT id FROM ingest_jobs "
                "WHERE filepath = ? AND status IN ('pending','processing')",
                (str(filepath),)
            ).fetchone()
            if queued_already:
                skipped += 1
                continue

            # Estimate for priority
            est = estimate_job(filepath)
            if "error" in est:
                errors.append(est["error"])
                continue

            now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            cursor = conn.execute("""
                INSERT INTO ingest_jobs
                (filepath, filename, status, priority, page_count,
                 file_size_mb, estimated_secs, created_at)
                VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)
            """, (
                str(filepath),
                filepath.name,
                est["priority"],
                est["page_count"],
                est["size_mb"],
                est["estimated_secs"],
                now,
            ))
            conn.commit()
            job_ids.append(cursor.lastrowid)
            queued += 1

    conn.close()

    return ok({
        "queued":  queued,
        "skipped": skipped,
        "errors":  errors,
        "job_ids": job_ids,
    })


UPLOAD_DIR = BASE_DIR / "uploads"

@app.route("/api/upload", methods=["POST"])
def api_upload():
    """
    POST /api/upload  (multipart/form-data, field name: 'files')
    Saves uploaded files to uploads/, queues each for ingestion.
    """
    files = request.files.getlist("files")
    if not files:
        return err("No files received")

    UPLOAD_DIR.mkdir(exist_ok=True)
    conn    = get_conn()
    queued  = 0
    skipped = 0
    errors  = []
    job_ids = []

    for f in files:
        if not f.filename:
            continue
        # Sanitise filename
        safe_name = Path(f.filename).name
        if Path(safe_name).suffix.lower() not in SUPPORTED:
            errors.append(f"Unsupported type: {safe_name}")
            continue

        dest = UPLOAD_DIR / safe_name
        # Avoid collisions
        stem, suffix = Path(safe_name).stem, Path(safe_name).suffix
        counter = 1
        while dest.exists():
            dest = UPLOAD_DIR / f"{stem}_{counter}{suffix}"
            counter += 1

        f.save(str(dest))

        existing = conn.execute(
            "SELECT id FROM documents WHERE filepath = ?", (str(dest),)
        ).fetchone()
        if existing:
            skipped += 1
            continue

        queued_already = conn.execute(
            "SELECT id FROM ingest_jobs WHERE filepath = ? AND status IN ('pending','processing')",
            (str(dest),)
        ).fetchone()
        if queued_already:
            skipped += 1
            continue

        est = estimate_job(dest)
        if "error" in est:
            errors.append(est["error"])
            continue

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = conn.execute("""
            INSERT INTO ingest_jobs
            (filepath, filename, status, priority, page_count,
             file_size_mb, estimated_secs, created_at)
            VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)
        """, (
            str(dest), dest.name,
            est["priority"], est["page_count"],
            est["size_mb"], est["estimated_secs"],
            now,
        ))
        job_ids.append(cursor.lastrowid)
        queued += 1

    conn.commit()
    conn.close()

    return ok({"queued": queued, "skipped": skipped, "errors": errors, "job_ids": job_ids})


@app.route("/api/ingest/status", methods=["GET"])
def api_ingest_status_all():
    """
    GET /api/ingest/status
    Returns all jobs grouped by status.
    """
    try:
        conn = get_conn()
        jobs = conn.execute("""
            SELECT id, filename, status, priority, page_count,
                   file_size_mb, estimated_secs, progress_page,
                   error_message, created_at, started_at, finished_at
            FROM ingest_jobs
            ORDER BY
                CASE status
                    WHEN 'processing' THEN 0
                    WHEN 'pending'    THEN 1
                    WHEN 'done'       THEN 2
                    WHEN 'failed'     THEN 3
                END,
                priority ASC,
                id ASC
        """).fetchall()
        conn.close()

        jobs = [dict(j) for j in jobs]

        # Add progress percentage
        for j in jobs:
            pages = j.get("page_count") or 1
            prog  = j.get("progress_page") or 0
            j["progress_pct"] = min(100, int(prog / pages * 100))

            # Human readable ETA
            secs = j.get("estimated_secs") or 0
            j["eta_display"] = (
                f"{secs // 60}m {secs % 60}s" if secs >= 60
                else f"{secs}s"
            )

        # Priority label
        priority_labels = {1: "high", 2: "normal", 3: "low", 4: "lowest"}
        for j in jobs:
            j["priority_label"] = priority_labels.get(j["priority"], "normal")

        pending    = [j for j in jobs if j["status"] == "pending"]
        processing = [j for j in jobs if j["status"] == "processing"]
        done       = [j for j in jobs if j["status"] == "done"]
        failed     = [j for j in jobs if j["status"] == "failed"]

        return ok({
            "processing": processing,
            "pending":    pending,
            "done":       done,
            "failed":     failed,
            "total":      len(jobs),
            "worker_active": _worker_active,
        })

    except Exception as e:
        return err(str(e), 500)


@app.route("/api/ingest/status/<int:job_id>", methods=["GET"])
def api_ingest_status_one(job_id):
    """
    GET /api/ingest/status/<job_id>
    Single job status for polling.
    """
    try:
        conn = get_conn()
        job  = conn.execute(
            "SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        conn.close()

        if not job:
            return err("Job not found", 404)

        job = dict(job)
        pages = job.get("page_count") or 1
        prog  = job.get("progress_page") or 0
        job["progress_pct"] = min(100, int(prog / pages * 100))

        return ok(job)

    except Exception as e:
        return err(str(e), 500)


# ── INSIGHTS ──────────────────────────────────────────────────────

@app.route("/api/insights", methods=["GET"])
def api_insights():
    """
    GET /api/insights
    Returns real library stats computed from the DB — no stubs.
    All aggregation done in SQL for efficiency.
    """
    try:
        conn = get_conn()

        # Core library stats — single query
        doc_stats = conn.execute("""
            SELECT
                COUNT(*)                      AS total_docs,
                COALESCE(SUM(page_count),  0) AS total_pages,
                COALESCE(SUM(chunk_count), 0) AS total_chunks,
                COALESCE(SUM(entity_count),0) AS total_entities,
                COALESCE(SUM(file_size),   0) AS total_bytes
            FROM documents
            WHERE status = 'indexed'
        """).fetchone()

        # Entity type distribution
        entity_dist = conn.execute("""
            SELECT entity_type, COUNT(*) AS count
            FROM entities
            GROUP BY entity_type
            ORDER BY count DESC
        """).fetchall()

        # File type breakdown
        file_dist = conn.execute("""
            SELECT
                COALESCE(file_type, 'unknown') AS file_type,
                COUNT(*)                        AS count
            FROM documents
            WHERE status = 'indexed'
            GROUP BY file_type
            ORDER BY count DESC
        """).fetchall()

        # Recently indexed documents
        recent_docs = conn.execute("""
            SELECT filename, date_indexed, chunk_count, entity_count, file_type
            FROM documents
            WHERE status = 'indexed'
            ORDER BY date_indexed DESC
            LIMIT 6
        """).fetchall()

        # Failed job count for index health indicator
        failed_count = conn.execute(
            "SELECT COUNT(*) FROM ingest_jobs WHERE status = 'failed'"
        ).fetchone()[0]

        # Feedback summary (table may not exist yet)
        feedback = {"up": 0, "down": 0}
        try:
            row = conn.execute("""
                SELECT
                    SUM(CASE WHEN thumbs='up'   THEN 1 ELSE 0 END) AS up,
                    SUM(CASE WHEN thumbs='down' THEN 1 ELSE 0 END) AS down
                FROM query_feedback
            """).fetchone()
            feedback = {"up": row["up"] or 0, "down": row["down"] or 0}
        except Exception:
            pass

        conn.close()

        return ok({
            "total_docs":     doc_stats["total_docs"],
            "total_pages":    doc_stats["total_pages"],
            "total_chunks":   doc_stats["total_chunks"],
            "total_entities": doc_stats["total_entities"],
            "total_bytes":    doc_stats["total_bytes"],
            "entity_dist":    [dict(r) for r in entity_dist],
            "file_dist":      [dict(r) for r in file_dist],
            "recent_docs":    [dict(r) for r in recent_docs],
            "failed_count":   failed_count,
            "feedback":       feedback,
        })

    except Exception as e:
        return err(str(e), 500)


@app.route("/api/explore/entities", methods=["GET"])
def api_explore_entities():
    """
    GET /api/explore/entities
    Paginated entity browser. All filtering done in SQL.

    Query params:
      type    — entity_type exact match (PERSON, ORG, etc.)
      q       — substring search on value + context
      doc_id  — filter to a single document
      page    — 1-based page number (default 1)
    """
    try:
        entity_type = request.args.get("type",   "").strip()
        q           = request.args.get("q",      "").strip()
        doc_id      = request.args.get("doc_id", "").strip()
        page        = max(1, int(request.args.get("page", 1)))
        per_page    = 50
        offset      = (page - 1) * per_page

        conn   = get_conn()
        where  = []
        params = []

        if entity_type:
            where.append("e.entity_type = ?")
            params.append(entity_type)
        if q:
            where.append("(e.value LIKE ? OR e.context LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if doc_id:
            where.append("e.doc_id = ?")
            params.append(int(doc_id))

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        base_sql  = f"""
            FROM entities e
            JOIN documents d ON e.doc_id = d.id
            {where_sql}
        """

        total = conn.execute(
            f"SELECT COUNT(*) {base_sql}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT e.id, e.entity_type, e.value, e.context,
                       e.page_number, d.id AS doc_id, d.filename
                {base_sql}
                ORDER BY e.entity_type, e.value
                LIMIT ? OFFSET ?""",
            params + [per_page, offset]
        ).fetchall()

        # Entity type counts for filter pill badges (no extra round-trip)
        type_counts = conn.execute("""
            SELECT entity_type, COUNT(*) AS count
            FROM entities
            GROUP BY entity_type
            ORDER BY count DESC
        """).fetchall()

        # Document list for the filter dropdown
        docs = conn.execute("""
            SELECT d.id, d.filename
            FROM documents d
            WHERE EXISTS (SELECT 1 FROM entities e WHERE e.doc_id = d.id)
            ORDER BY d.filename
        """).fetchall()

        conn.close()

        return ok({
            "entities":    [dict(r) for r in rows],
            "total":       total,
            "page":        page,
            "per_page":    per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
            "type_counts": [dict(r) for r in type_counts],
            "documents":   [dict(r) for r in docs],
        })

    except Exception as e:
        return err(str(e), 500)


# ── FEEDBACK ──────────────────────────────────────────────────────

@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    """
    POST /api/feedback
    body: { question, answer, source_file, confidence, thumbs: 'up'|'down' }
    Stores one feedback row. Used to surface answer quality in Insights.
    """
    data   = request.get_json(silent=True) or {}
    thumbs = data.get("thumbs", "")
    if thumbs not in ("up", "down"):
        return err("thumbs must be 'up' or 'down'")

    try:
        conn = get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS query_feedback (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                question    TEXT,
                answer      TEXT,
                source_file TEXT,
                confidence  REAL,
                thumbs      TEXT CHECK(thumbs IN ('up','down')),
                created_at  TEXT NOT NULL
            )
        """)
        conn.execute(
            """INSERT INTO query_feedback
               (question, answer, source_file, confidence, thumbs, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                (data.get("question") or "")[:500],
                (data.get("answer")   or "")[:1000],
                (data.get("source_file") or "")[:255],
                float(data.get("confidence") or 0),
                thumbs,
                time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
        conn.commit()
        conn.close()
        return ok({"recorded": thumbs})
    except Exception as e:
        return err(str(e), 500)


# ── EXPORT ────────────────────────────────────────────────────────

@app.route("/api/explore/entities/export", methods=["GET"])
def api_export_entities():
    """
    GET /api/explore/entities/export
    Same filters as /api/explore/entities but streams a CSV file.
    No pagination — returns all matching rows.
    """
    import csv
    import io
    from flask import Response

    entity_type = request.args.get("type",   "").strip()
    q           = request.args.get("q",      "").strip()
    doc_id      = request.args.get("doc_id", "").strip()

    try:
        conn   = get_conn()
        where  = []
        params = []

        if entity_type:
            where.append("e.entity_type = ?")
            params.append(entity_type)
        if q:
            where.append("(e.value LIKE ? OR e.context LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if doc_id:
            where.append("e.doc_id = ?")
            params.append(int(doc_id))

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        rows = conn.execute(
            f"""SELECT e.entity_type, e.value, e.context,
                       e.page_number, d.filename, d.filepath
                FROM entities e
                JOIN documents d ON e.doc_id = d.id
                {where_sql}
                ORDER BY e.entity_type, e.value""",
            params
        ).fetchall()
        conn.close()

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["type", "value", "context", "page", "filename", "filepath"])
        for r in rows:
            writer.writerow([r["entity_type"], r["value"], r["context"],
                             r["page_number"], r["filename"], r["filepath"]])

        filename = f"locallab_entities_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return err(str(e), 500)


# ── FILE DETAIL ───────────────────────────────────────────────────

@app.route("/api/files/<int:doc_id>", methods=["GET"])
def api_file_detail(doc_id):
    """GET /api/files/<id> — document detail with chunks and entities."""
    try:
        conn = get_conn()
        doc = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not doc:
            conn.close()
            return err("Not found", 404)

        chunks = conn.execute(
            "SELECT id, chunk_index, page_start, page_end, text "
            "FROM chunks WHERE doc_id=? ORDER BY chunk_index",
            (doc_id,)
        ).fetchall()

        entities = conn.execute(
            "SELECT id, entity_type, value, normalized_value, context, page_number, confidence "
            "FROM entities WHERE doc_id=? ORDER BY page_number, id",
            (doc_id,)
        ).fetchall()

        conn.close()
        return ok({
            "document": dict(doc),
            "chunks":   [dict(c) for c in chunks],
            "entities": [dict(e) for e in entities],
        })
    except Exception as e:
        return err(str(e), 500)


# ── EXPORT DOWNLOAD ────────────────────────────────────────────────

@app.route("/api/export/<fmt>", methods=["GET"])
def api_export_download(fmt):
    """
    GET /api/export/json    — full JSON export as file download
    GET /api/export/sqlite  — SQLite DB copy as file download
    GET /api/export/csv     — all tables as zipped CSV files
    """
    import io
    import zipfile
    from flask import Response as _Response
    sys.path.insert(0, str(BASE_DIR / "core"))

    allowed = {"json", "sqlite", "csv"}
    if fmt not in allowed:
        return err(f"Unknown format '{fmt}'. Use: {', '.join(allowed)}", 400)

    try:
        from export import export_json, export_sqlite, export_csv
        conn   = get_conn()
        ts     = time.strftime("%Y%m%d_%H%M%S")
        tmpdir = BASE_DIR / "exports"
        tmpdir.mkdir(parents=True, exist_ok=True)

        if fmt == "json":
            path = tmpdir / f"locallab_{ts}.json"
            export_json(path, conn)
            conn.close()
            return _Response(
                path.read_bytes(),
                mimetype="application/json",
                headers={"Content-Disposition": f"attachment; filename=locallab_{ts}.json"},
            )

        elif fmt == "sqlite":
            path = tmpdir / f"locallab_{ts}.db"
            export_sqlite(path, conn)
            conn.close()
            return _Response(
                path.read_bytes(),
                mimetype="application/octet-stream",
                headers={"Content-Disposition": f"attachment; filename=locallab_{ts}.db"},
            )

        elif fmt == "csv":
            csv_dir = tmpdir / f"csv_{ts}"
            export_csv(csv_dir, conn)
            conn.close()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in csv_dir.glob("*.csv"):
                    zf.write(f, f.name)
            buf.seek(0)
            return _Response(
                buf.read(),
                mimetype="application/zip",
                headers={"Content-Disposition": f"attachment; filename=locallab_csv_{ts}.zip"},
            )

    except Exception as e:
        return err(str(e), 500)


# ── DELETE DOCUMENT ───────────────────────────────────────────────

@app.route("/api/files/<int:doc_id>", methods=["DELETE"])
def api_delete_file(doc_id):
    """
    DELETE /api/files/<id>
    Removes document + all chunks/entities/jobs from SQLite and Qdrant.
    """
    try:
        conn = get_conn()
        doc = conn.execute(
            "SELECT filepath, filename FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        if not doc:
            conn.close()
            return err("Document not found", 404)

        conn.execute("DELETE FROM chunks     WHERE doc_id=?",     (doc_id,))
        conn.execute("DELETE FROM entities   WHERE doc_id=?",     (doc_id,))
        conn.execute("DELETE FROM ingest_jobs WHERE filepath=?",  (doc["filepath"],))
        conn.execute("DELETE FROM documents  WHERE id=?",         (doc_id,))
        conn.commit()
        conn.close()

        # Remove vectors from Qdrant
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            qdrant = QdrantClient(path=str(BASE_DIR / "db" / "qdrant"))
            qdrant.delete(
                collection_name="done_docs",
                points_selector=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                ),
            )
        except Exception:
            pass  # Qdrant may not have this doc; not fatal

        return ok({"deleted": doc_id, "filename": doc["filename"]})
    except Exception as e:
        return err(str(e), 500)


# ── DYNAMIC SUGGESTIONS ───────────────────────────────────────────

@app.route("/api/suggestions", methods=["GET"])
def api_suggestions():
    """
    GET /api/suggestions
    Returns up to 6 contextual question suggestions based on what's indexed.
    Uses entity names, document types, and filenames to generate relevant prompts.
    Falls back to static defaults when the library is empty.
    """
    try:
        conn = get_conn()

        docs = conn.execute(
            "SELECT filename, file_type FROM documents WHERE status='indexed' ORDER BY date_indexed DESC LIMIT 10"
        ).fetchall()

        if not docs:
            conn.close()
            return ok({"suggestions": [
                "What are the key terms in this document?",
                "Who are the main parties involved?",
                "What are the important dates?",
                "Summarise the main points",
            ]})

        # Pull top entities for context
        people = conn.execute(
            "SELECT DISTINCT value FROM entities WHERE entity_type IN ('PERSON','NAME') "
            "ORDER BY id DESC LIMIT 5"
        ).fetchall()
        orgs = conn.execute(
            "SELECT DISTINCT value FROM entities WHERE entity_type IN ('ORG','ORGANIZATION','COMPANY') "
            "ORDER BY id DESC LIMIT 3"
        ).fetchall()
        skills = conn.execute(
            "SELECT DISTINCT value FROM entities WHERE entity_type IN ('SKILL','TECHNOLOGY') "
            "ORDER BY id DESC LIMIT 3"
        ).fetchall()
        conn.close()

        suggestions = []
        filenames = [d["filename"] for d in docs]
        name = people[0]["value"] if people else None
        org  = orgs[0]["value"]   if orgs   else None

        # Resume-type suggestions
        resume_files = [f for f in filenames if any(k in f.lower() for k in ("resume", "cv", "seller", "dallas"))]
        if resume_files or skills:
            if name:
                suggestions.append(f"What are {name}'s key technical skills?")
                suggestions.append(f"Where has {name} worked and for how long?")
            else:
                suggestions.append("What are the key skills listed?")
                suggestions.append("Summarise the work history")

        # Contract/legal suggestions
        contract_files = [f for f in filenames if any(k in f.lower() for k in ("contract", "agreement", "terms", "inc", "legal", "invisalign"))]
        if contract_files:
            suggestions.append("What are the key obligations and terms?")
            if org:
                suggestions.append(f"What are {org}'s responsibilities?")
            else:
                suggestions.append("What are the payment terms?")

        # Generic fallbacks to fill to 4
        fallbacks = [
            "What important dates are mentioned?",
            "Who are the key people or organizations?",
            "What are the main points of this document?",
            "Are there any financial amounts mentioned?",
        ]
        for fb in fallbacks:
            if len(suggestions) >= 4:
                break
            if fb not in suggestions:
                suggestions.append(fb)

        return ok({"suggestions": suggestions[:4]})
    except Exception:
        return ok({"suggestions": [
            "What are the key terms in this document?",
            "Who are the main parties involved?",
            "What are the important dates?",
            "Summarise the main points",
        ]})


# ── WATCH FOLDER ──────────────────────────────────────────────────

def _enqueue_file(filepath: Path):
    """Queue a single file for ingestion. Safe to call from any thread."""
    try:
        if filepath.suffix.lower() not in SUPPORTED:
            return
        conn = get_conn()
        already = conn.execute(
            "SELECT id FROM documents WHERE filepath=?", (str(filepath),)
        ).fetchone()
        if already:
            conn.close()
            return
        queued = conn.execute(
            "SELECT id FROM ingest_jobs WHERE filepath=? AND status IN ('pending','processing')",
            (str(filepath),)
        ).fetchone()
        if queued:
            conn.close()
            return
        est = estimate_job(filepath)
        if "error" in est:
            conn.close()
            return
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("""
            INSERT INTO ingest_jobs
            (filepath, filename, status, priority, page_count, file_size_mb, estimated_secs, created_at)
            VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)
        """, (str(filepath), filepath.name, est["priority"], est["page_count"],
              est["size_mb"], est["estimated_secs"], now))
        conn.commit()
        conn.close()
        print(f"[watch] Queued: {filepath.name}")
    except Exception as e:
        print(f"[watch] Enqueue error: {e}")


def _start_watch_folders():
    """Start watchdog observer for configured folders. Called at startup."""
    try:
        import yaml
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        config_path = BASE_DIR / "config" / "config.yaml"
        if not config_path.exists():
            return

        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}

        folders = cfg.get("watch", {}).get("folders", [])
        if not folders:
            return

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if event.is_directory:
                    return
                path = Path(event.src_path)
                # Debounce — wait 2s for file write to complete
                time.sleep(2)
                _enqueue_file(path)

        observer = Observer()
        active = 0
        for folder in folders:
            p = Path(folder).expanduser()
            if p.exists() and p.is_dir():
                observer.schedule(_Handler(), str(p), recursive=True)
                active += 1
                print(f"[watch] Watching: {p}")

        if active:
            observer.daemon = True
            observer.start()
            print(f"[watch] Observer started ({active} folder{'s' if active != 1 else ''})")

    except ImportError:
        print("[watch] watchdog not installed — folder watching disabled")
    except Exception as e:
        print(f"[watch] Startup error: {e}")


# ── DEV HELPERS ───────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def api_health():
    """Quick health check."""
    db_ok = (BASE_DIR / "db" / "done.db").exists()
    return ok({
        "status":  "ok",
        "db":      db_ok,
        "worker":  _worker_active,
    })


# ── MAIN ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n{'═'*50}")
    print(f"  done — Document Intelligence")
    print(f"{'═'*50}")
    print(f"  http://localhost:5000")
    print(f"  Ctrl+C to stop")
    print(f"{'═'*50}\n")

    # Ensure DB exists
    conn = init_db()
    conn.close()

    # Start watch folder observer
    _start_watch_folders()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,  # debug=True breaks background threads
        threaded=True,
    )