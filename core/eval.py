"""
DONE · core/eval.py
────────────────────
Ground truth evaluation engine. The differentiator.

Automatically builds an eval set from your own documents,
runs every question through the query pipeline, scores the
answers, and produces a single trust score (0.0 - 1.0).

Three eval mechanisms:
  1. Span grounding   — did the answer come from the right source
  2. Entity match     — does the answer contain the known entity value
  3. Counterfactual   — if we change a fact, does the answer change

Usage:
  python core/eval.py                        # run full eval
  python core/eval.py --build-only           # just build question set
  python core/eval.py --show                 # show existing eval results
  python core/eval.py --counterfactual       # run counterfactual tests
  python core/eval.py --doc-id 1             # eval one document only
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

try:
    import ollama
except ImportError:
    print("[eval] ERROR: pip install ollama")
    sys.exit(1)

# ── CONFIG ────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent.parent
DB_PATH      = BASE_DIR / "db" / "done.db"
REASON_MODEL = "qwen2.5:14b"

# Entity types worth generating eval questions for
EVAL_ENTITY_TYPES = {
    "PERSON", "ORG", "LOCATION", "CONTACT",
    "AMOUNT", "DATE", "SKILL", "CLAUSE"
}

# ── DATABASE ──────────────────────────────────────────────────────

def get_conn():
    if not DB_PATH.exists():
        print("[eval] No database found. Run ingest.py first.")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Create eval tables if not exist
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS eval_questions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id          INTEGER REFERENCES documents(id),
            entity_id       INTEGER REFERENCES entities(id),
            question        TEXT NOT NULL,
            expected_answer TEXT NOT NULL,
            expected_source TEXT,
            entity_type     TEXT,
            created_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS eval_results (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id         INTEGER REFERENCES eval_questions(id),
            actual_answer       TEXT,
            actual_source       TEXT,
            actual_span         TEXT,
            confidence_given    REAL,
            entity_match_score  REAL,
            source_match_score  REAL,
            grounding_score     REAL,
            counterfactual_pass INTEGER DEFAULT -1,
            verdict             TEXT,
            elapsed             REAL,
            run_at              TEXT
        );
    """)
    conn.commit()
    return conn

# ── QUESTION GENERATION ───────────────────────────────────────────

QUESTION_GEN_PROMPT = """Given this extracted fact from a document, generate ONE clear question that:
1. Has this fact as the correct answer
2. Can be answered by reading the document
3. Is specific enough that only this fact answers it correctly

Entity type: {entity_type}
Entity value: {value}
Context: {context}
Document: {filename}

Return ONLY valid JSON, no other text:
{{
  "question": "your specific question here",
  "expected_answer": "{value}"
}}"""

def generate_question(entity, conn):
    """Generate a question from an entity that has a known answer."""
    prompt = QUESTION_GEN_PROMPT.format(
        entity_type=entity["entity_type"],
        value=entity["value"],
        context=entity["context"],
        filename=entity["filename"]
    )

    try:
        response = ollama.chat(
            model=REASON_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.3, "num_ctx": 2048}
        )
        raw = response["message"]["content"].strip()
        raw = re.sub(r'```(?:json)?\s*', '', raw).strip()

        start = raw.find('{')
        end   = raw.rfind('}')
        if start == -1 or end == -1:
            return None

        parsed = json.loads(raw[start:end+1])
        if "question" not in parsed:
            return None

        return {
            "question":        parsed["question"],
            "expected_answer": str(entity["value"]),
            "expected_source": entity["filename"],
            "entity_type":     entity["entity_type"],
        }

    except Exception as e:
        return None


def build_eval_set(conn, doc_id=None, max_per_doc=10):
    """
    Build ground truth question set from extracted entities.
    Each entity becomes a (question, expected_answer) pair.
    """
    # Get entities from DB
    if doc_id:
        query = """
            SELECT e.id, e.entity_type, e.value, e.context,
                   e.doc_id, d.filename
            FROM entities e
            JOIN documents d ON e.doc_id = d.id
            WHERE e.doc_id = ? AND e.entity_type IN ({})
            ORDER BY e.id
        """.format(','.join('?' * len(EVAL_ENTITY_TYPES)))
        params = [doc_id] + list(EVAL_ENTITY_TYPES)
        entities = conn.execute(query, params).fetchall()
    else:
        query = """
            SELECT e.id, e.entity_type, e.value, e.context,
                   e.doc_id, d.filename
            FROM entities e
            JOIN documents d ON e.doc_id = d.id
            WHERE e.entity_type IN ({})
            ORDER BY e.doc_id, e.id
        """.format(','.join('?' * len(EVAL_ENTITY_TYPES)))
        entities = conn.execute(query, list(EVAL_ENTITY_TYPES)).fetchall()

    entities = [dict(e) for e in entities]

    if not entities:
        print("[eval] No entities found. Run ingest.py first.")
        return 0

    print(f"[eval] Found {len(entities)} entities across documents")
    print(f"[eval] Generating eval questions...\n")

    # Group by doc, limit per doc
    by_doc = {}
    for e in entities:
        by_doc.setdefault(e["doc_id"], []).append(e)

    total = 0
    for did, ents in by_doc.items():
        # Prioritise variety of entity types
        seen_types = set()
        selected = []
        for e in ents:
            if len(selected) >= max_per_doc:
                break
            if e["entity_type"] not in seen_types or len(selected) < 4:
                selected.append(e)
                seen_types.add(e["entity_type"])

        print(f"[eval] Doc {did}: generating {len(selected)} questions...")

        for e in selected:
            # Skip if question already exists for this entity
            existing = conn.execute(
                "SELECT id FROM eval_questions WHERE entity_id = ?",
                (e["id"],)
            ).fetchone()
            if existing:
                continue

            q = generate_question(e, conn)
            if not q:
                continue

            now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute("""
                INSERT INTO eval_questions
                (doc_id, entity_id, question, expected_answer,
                 expected_source, entity_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                e["doc_id"], e["id"],
                q["question"], q["expected_answer"],
                q["expected_source"], q["entity_type"], now
            ))
            conn.commit()
            total += 1
            print(f"  [{e['entity_type']}] Q: {q['question'][:70]}")
            print(f"         A: {q['expected_answer']}")

    print(f"\n[eval] Built {total} eval questions")
    return total

# ── SCORING ───────────────────────────────────────────────────────

def score_entity_match(expected, actual):
    """
    How well does the actual answer contain the expected value?
    Returns 0.0 - 1.0
    """
    if not expected or not actual:
        return 0.0

    exp = expected.lower().strip()
    act = actual.lower().strip()

    # Exact match
    if exp == act:
        return 1.0

    # Contains match
    if exp in act:
        return 0.9

    # Partial word overlap
    exp_words = set(exp.split())
    act_words = set(act.split())
    if not exp_words:
        return 0.0

    overlap = len(exp_words & act_words) / len(exp_words)
    return round(overlap, 3)


def score_source_match(expected_source, actual_source):
    """Did the answer come from the right document?"""
    if not expected_source or not actual_source:
        return 0.0
    if expected_source.lower() in actual_source.lower():
        return 1.0
    if actual_source.lower() in expected_source.lower():
        return 1.0
    return 0.0


def score_grounding(expected_answer, source_span):
    """Is the expected answer actually present in the cited span?"""
    if not source_span or not expected_answer:
        return 0.0
    if expected_answer.lower() in source_span.lower():
        return 1.0
    # Partial
    words = set(expected_answer.lower().split())
    span_words = set(source_span.lower().split())
    if not words:
        return 0.0
    return round(len(words & span_words) / len(words), 3)


def overall_verdict(entity_score, source_score, grounding_score, confidence):
    """Combine scores into a single verdict."""
    # Weighted average
    combined = (
        entity_score    * 0.40 +
        source_score    * 0.25 +
        grounding_score * 0.25 +
        confidence      * 0.10
    )
    if combined >= 0.80: return "PASS",   combined
    if combined >= 0.50: return "PARTIAL", combined
    return "FAIL", combined

# ── RUN EVAL ──────────────────────────────────────────────────────

def run_eval(conn, doc_id=None, verbose=True):
    """
    Run all eval questions through the query pipeline and score results.
    """
    # Import query pipeline
    sys.path.insert(0, str(BASE_DIR / "core"))
    from query import ask

    # Get questions
    if doc_id:
        questions = conn.execute(
            "SELECT * FROM eval_questions WHERE doc_id = ?", (doc_id,)
        ).fetchall()
    else:
        questions = conn.execute(
            "SELECT * FROM eval_questions"
        ).fetchall()

    questions = [dict(q) for q in questions]

    if not questions:
        print("[eval] No eval questions found. Run with --build-only first.")
        return None

    print(f"\n[eval] Running {len(questions)} eval questions...\n")

    results = []
    passes = 0
    partials = 0
    fails = 0

    for i, q in enumerate(questions):
        print(f"[{i+1}/{len(questions)}] [{q['entity_type']}] {q['question'][:60]}...")

        # Ask through query pipeline
        t0     = time.time()
        result = ask(q["question"], top_k=5)
        elapsed = time.time() - t0

        actual_answer = result.get("answer", "")
        actual_source = result.get("source_file", "")
        actual_span   = result.get("source_span", "")
        confidence    = result.get("confidence", 0.0)

        # Score
        entity_score    = score_entity_match(q["expected_answer"], actual_answer)
        source_score    = score_source_match(q["expected_source"], actual_source)
        grounding_score = score_grounding(q["expected_answer"], actual_span)
        verdict, combined = overall_verdict(
            entity_score, source_score, grounding_score, confidence
        )

        # Icon
        icon = "✓" if verdict == "PASS" else "~" if verdict == "PARTIAL" else "✗"
        print(f"  {icon} {verdict}  entity={entity_score:.2f}  "
              f"source={source_score:.2f}  grounding={grounding_score:.2f}  "
              f"combined={combined:.2f}")

        if verbose and verdict != "PASS":
            print(f"  Expected: {q['expected_answer']}")
            print(f"  Got:      {actual_answer[:100]}")

        # Store result
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("""
            INSERT INTO eval_results
            (question_id, actual_answer, actual_source, actual_span,
             confidence_given, entity_match_score, source_match_score,
             grounding_score, verdict, elapsed, run_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            q["id"], actual_answer[:1000], actual_source,
            actual_span[:500], confidence,
            entity_score, source_score, grounding_score,
            verdict, elapsed, now
        ))
        conn.commit()

        results.append({
            "question":      q["question"],
            "expected":      q["expected_answer"],
            "actual":        actual_answer,
            "verdict":       verdict,
            "combined":      combined,
            "entity_score":  entity_score,
        })

        if verdict == "PASS":    passes += 1
        elif verdict == "PARTIAL": partials += 1
        else: fails += 1

    # Summary
    total       = len(questions)
    trust_score = (passes + partials * 0.5) / total if total > 0 else 0.0
    avg_entity  = sum(r["entity_score"] for r in results) / total if total else 0.0

    print(f"\n{'═'*60}")
    print(f"  DONE Eval Results")
    print(f"{'═'*60}")
    print(f"  Questions:   {total}")
    print(f"  Pass:        {passes}  ({passes/total*100:.0f}%)")
    print(f"  Partial:     {partials}  ({partials/total*100:.0f}%)")
    print(f"  Fail:        {fails}  ({fails/total*100:.0f}%)")
    print(f"{'─'*60}")
    print(f"  Trust score: {trust_score*100:.1f}%")
    print(f"  Avg entity match: {avg_entity*100:.1f}%")
    print(f"{'═'*60}\n")

    return {
        "total":       total,
        "passes":      passes,
        "partials":    partials,
        "fails":       fails,
        "trust_score": round(trust_score, 4),
        "avg_entity":  round(avg_entity, 4),
    }

# ── COUNTERFACTUAL TEST ───────────────────────────────────────────

def run_counterfactual(conn):
    """
    Counterfactual test: change a known fact in a document,
    re-ask the question, check if the answer changes.
    Measures: is the system reading the document or hallucinating?
    """
    print("\n[eval] Running counterfactual tests...")
    print("[eval] This modifies documents temporarily then restores them.\n")

    sys.path.insert(0, str(BASE_DIR / "core"))
    from query import ask

    # Get AMOUNT and DATE entities — easiest to swap
    entities = conn.execute("""
        SELECT e.id, e.entity_type, e.value, e.context,
               e.doc_id, d.filename, d.filepath, d.raw_text
        FROM entities e
        JOIN documents d ON e.doc_id = d.id
        WHERE e.entity_type IN ('AMOUNT', 'DATE', 'CONTACT')
        LIMIT 5
    """).fetchall()

    if not entities:
        print("[eval] No suitable entities for counterfactual test")
        return

    passed = 0
    total  = 0

    import chromadb as _chromadb
    _chroma_client = _chromadb.PersistentClient(path=str(BASE_DIR / "db" / "chroma"))
    try:
        _collection = _chroma_client.get_collection("done_docs")
    except Exception:
        print("[eval] ChromaDB collection not found")
        return

    for e in entities:
        e = dict(e)
        original_value = e["value"]
        raw_text       = e["raw_text"] or ""

        if original_value not in raw_text:
            continue

        # Generate counterfactual value
        cf_map = {
            "AMOUNT":  lambda v: v.replace("7", "3").replace("50", "75"),
            "DATE":    lambda v: v.replace("2024", "2019").replace("2023", "2018"),
            "CONTACT": lambda v: v.replace("@", "_noemail_"),
        }
        cf_fn = cf_map.get(e["entity_type"])
        if not cf_fn:
            continue

        cf_value = cf_fn(original_value)
        if cf_value == original_value:
            continue

        total += 1

        # Get question
        questions = conn.execute(
            "SELECT question FROM eval_questions WHERE entity_id = ?",
            (e["id"],)
        ).fetchone()
        q_text = questions["question"] if questions else (
            f"What is the {e['entity_type'].lower()}: {original_value[:30]}?"
        )

        # Baseline answer from original chunks
        baseline = ask(q_text, top_k=5)
        baseline_answer = baseline.get("answer", "")

        # Patch ChromaDB chunks for this doc
        patched_text = raw_text.replace(original_value, cf_value)
        doc_chunks = conn.execute(
            "SELECT chroma_id, text FROM chunks WHERE doc_id = ?",
            (e["doc_id"],)
        ).fetchall()

        # Update chunks in ChromaDB with patched text
        for chunk in doc_chunks:
            patched_chunk = chunk["text"].replace(original_value, cf_value)
            if patched_chunk != chunk["text"]:
                try:
                    _collection.update(
                        ids=[chunk["chroma_id"]],
                        documents=[patched_chunk]
                    )
                except Exception:
                    pass

        # Also patch SQLite raw_text
        conn.execute(
            "UPDATE documents SET raw_text = ? WHERE id = ?",
            (patched_text, e["doc_id"])
        )
        conn.commit()

        # Ask with patched content
        cf_result = ask(q_text, top_k=5)
        cf_answer = cf_result.get("answer", "")

        # Restore ChromaDB chunks
        for chunk in doc_chunks:
            try:
                _collection.update(
                    ids=[chunk["chroma_id"]],
                    documents=[chunk["text"]]
                )
            except Exception:
                pass

        # Restore SQLite
        conn.execute(
            "UPDATE documents SET raw_text = ? WHERE id = ?",
            (raw_text, e["doc_id"])
        )
        conn.commit()

        # Did answer change?
        answer_changed = cf_answer.lower() != baseline_answer.lower()
        result_icon    = "✓" if answer_changed else "✗"
        if answer_changed:
            passed += 1

        print(f"  {result_icon} [{e['entity_type']}] {original_value} → {cf_value}")
        print(f"    Q: {q_text[:60]}")
        print(f"    Before: {baseline_answer[:80]}")
        print(f"    After:  {cf_answer[:80]}")
        print(f"    Answer changed: {answer_changed}\n")

    if total > 0:
        rate = passed / total * 100
        print(f"[eval] Counterfactual: {passed}/{total} tests passed ({rate:.0f}%)")
        print(f"[eval] {'System is reading documents ✓' if rate >= 60 else 'System may be hallucinating ✗'}")

# ── SHOW RESULTS ──────────────────────────────────────────────────

def show_results(conn):
    """Display the most recent eval results."""
    rows = conn.execute("""
        SELECT eq.question, eq.expected_answer, eq.entity_type,
               er.actual_answer, er.verdict, er.grounding_score,
               er.entity_match_score, er.run_at
        FROM eval_results er
        JOIN eval_questions eq ON er.question_id = eq.id
        ORDER BY er.id DESC
        LIMIT 20
    """).fetchall()

    if not rows:
        print("[eval] No eval results yet. Run eval first.")
        return

    # Summary stats
    all_results = conn.execute("""
        SELECT verdict, grounding_score, entity_match_score
        FROM eval_results
        ORDER BY id DESC
        LIMIT 100
    """).fetchall()

    passes   = sum(1 for r in all_results if r["verdict"] == "PASS")
    partials = sum(1 for r in all_results if r["verdict"] == "PARTIAL")
    fails    = sum(1 for r in all_results if r["verdict"] == "FAIL")
    total    = len(all_results)
    trust    = (passes + partials * 0.5) / total * 100 if total else 0

    print(f"\n{'═'*60}")
    print(f"  Trust Score: {trust:.1f}%  "
          f"({passes} pass / {partials} partial / {fails} fail)")
    print(f"{'═'*60}")

    for r in rows:
        icon = "✓" if r["verdict"] == "PASS" else "~" if r["verdict"] == "PARTIAL" else "✗"
        print(f"\n  {icon} [{r['entity_type']}] {r['question'][:55]}")
        print(f"    Expected: {r['expected_answer'][:60]}")
        print(f"    Got:      {r['actual_answer'][:60] if r['actual_answer'] else 'nothing'}")
        print(f"    Scores:   entity={r['entity_match_score']:.2f}  "
              f"grounding={r['grounding_score']:.2f}")

    print(f"\n{'═'*60}")


# ── CLI ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="DONE eval — ground truth evaluation")
    p.add_argument("--build-only",     action="store_true",
                   help="Only build eval question set, don't run")
    p.add_argument("--show",           action="store_true",
                   help="Show existing eval results")
    p.add_argument("--counterfactual", action="store_true",
                   help="Run counterfactual injection tests")
    p.add_argument("--doc-id",         type=int,
                   help="Eval a specific document only")
    p.add_argument("--max-questions",  type=int, default=10,
                   help="Max questions per document (default 10)")
    p.add_argument("--quiet",          action="store_true",
                   help="Less verbose output")
    args = p.parse_args()

    conn = get_conn()

    if args.show:
        show_results(conn)

    elif args.counterfactual:
        run_counterfactual(conn)

    elif args.build_only:
        n = build_eval_set(conn, doc_id=args.doc_id,
                           max_per_doc=args.max_questions)
        print(f"\n[eval] {n} questions ready. Run eval.py to score them.")

    else:
        # Full eval: build then run
        print("[eval] Phase 1: Building eval question set...")
        n = build_eval_set(conn, doc_id=args.doc_id,
                           max_per_doc=args.max_questions)

        if n == 0:
            # Questions may already exist
            existing = conn.execute(
                "SELECT COUNT(*) as c FROM eval_questions"
            ).fetchone()["c"]
            if existing == 0:
                print("[eval] No questions could be generated.")
                sys.exit(1)
            print(f"[eval] Using {existing} existing questions.")

        print("\n[eval] Phase 2: Running eval questions through query pipeline...")
        results = run_eval(conn, doc_id=args.doc_id,
                           verbose=not args.quiet)

        if results:
            trust = results["trust_score"] * 100
            print(f"[eval] Final trust score: {trust:.1f}%")
            print(f"[eval] Run --show to see detailed results.")
            print(f"[eval] Run --counterfactual to test hallucination resistance.")