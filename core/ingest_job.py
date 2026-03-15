"""
DONE · core/ingest_job.py
──────────────────────────
Standalone ingestion script. Run as a subprocess by app.py worker.
Has its own SQLite connection — no conflict with Flask threads.

Usage (internal):
  python core/ingest_job.py --job-id 42 --filepath /path/to/file.pdf
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path
import warnings
warnings.filterwarnings("ignore", message=".*FloatObject.*")
warnings.filterwarnings("ignore", message=".*could not convert.*")

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent
DB_PATH  = BASE_DIR / "db" / "done.db"

sys.path.insert(0, str(BASE_DIR / 'core'))

from ingest import ingest_file


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=60, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--job-id",   required=True, type=int)
    p.add_argument("--filepath", required=True)
    args = p.parse_args()

    conn = get_conn()

    try:
        result = ingest_file(args.filepath, conn, job_id=args.job_id)
        conn.close()

        if result.get("success"):
            sys.exit(0)
        else:
            print(f"[ingest_job] Failed: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(f"[ingest_job] Exception: {e}", file=sys.stderr)
        try:
            conn.close()
        except Exception:
            pass
        sys.exit(1)