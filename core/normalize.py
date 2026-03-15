"""
DONE · core/normalize.py
─────────────────────────
Normalization rules for extracted entity values.

Takes a raw entity value and entity type, returns a clean
normalized value suitable for cross-document comparison,
export, and downstream analytics.

Also handles:
  - Character offset verification (find exact position in text)
  - Sensitivity detection from entity values and context
  - Category hints from entity patterns

Public API:
  normalize(value, entity_type)        → normalized string
  find_offsets(value, text)            → (char_start, char_end)
  detect_sensitivity(text)             → sensitivity label
  detect_category_hints(entities)      → category label
"""

import re
import unicodedata
from typing import Optional

# ── NORMALIZATION ─────────────────────────────────────────────────

def normalize(value: str, entity_type: str) -> str:
    """
    Normalize an entity value based on its type.
    Returns a clean, consistent string for storage and comparison.
    """
    if not value or not isinstance(value, str):
        return ""

    value = value.strip()

    normalizers = {
        "AMOUNT":   _normalize_amount,
        "DATE":     _normalize_date,
        "CONTACT":  _normalize_contact,
        "PERSON":   _normalize_name,
        "ORG":      _normalize_name,
        "LOCATION": _normalize_name,
        "SKILL":    _normalize_skill,
        "CLAUSE":   _normalize_text,
    }

    fn = normalizers.get(entity_type, _normalize_text)
    try:
        return fn(value)
    except Exception:
        return value.strip()


def _normalize_amount(value: str) -> str:
    """
    Normalize dollar amounts and quantities to numeric strings.
    "$7 million" → "7000000"
    "$4,500.00"  → "4500"
    "50%"        → "0.5" (percentage)
    """
    v = value.lower().strip()

    # Remove currency symbols and whitespace
    v = re.sub(r'[$£€¥]', '', v)
    v = re.sub(r'\s+', ' ', v).strip()

    # Handle percentages
    pct = re.search(r'([\d,.]+)\s*%', v)
    if pct:
        try:
            return str(round(float(pct.group(1).replace(',', '')) / 100, 4))
        except ValueError:
            pass

    # Handle multipliers
    multipliers = {
        'trillion': 1_000_000_000_000,
        'billion':  1_000_000_000,
        'million':  1_000_000,
        'thousand': 1_000,
        'k':        1_000,
        'm':        1_000_000,
        'b':        1_000_000_000,
    }

    for word, mult in multipliers.items():
        pattern = rf'([\d,.]+)\s*{word}'
        match = re.search(pattern, v)
        if match:
            try:
                num = float(match.group(1).replace(',', ''))
                return str(int(num * mult))
            except ValueError:
                pass

    # Plain number — strip commas, round to int if whole
    digits = re.sub(r'[^\d.]', '', v)
    if digits:
        try:
            f = float(digits)
            return str(int(f)) if f == int(f) else str(round(f, 2))
        except ValueError:
            pass

    return value.strip()


def _normalize_date(value: str) -> str:
    """
    Normalize dates to ISO 8601 format where possible.
    "January 2024"           → "2024-01"
    "January 2024 - Present" → "2024-01/"
    "April 2023 – Jan 2024"  → "2023-04/2024-01"
    "2024"                   → "2024"
    """
    MONTHS = {
        'january': '01', 'february': '02', 'march': '03',
        'april': '04',   'may': '05',      'june': '06',
        'july': '07',    'august': '08',   'september': '09',
        'october': '10', 'november': '11', 'december': '12',
        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
        'jun': '06', 'jul': '07', 'aug': '08', 'sep': '09',
        'oct': '10', 'nov': '11', 'dec': '12',
    }

    v = value.lower().strip()

    # Date range with "present"
    range_present = re.search(
        r'(\w+)\s+(\d{4})\s*[–\-—to]+\s*present', v
    )
    if range_present:
        month = MONTHS.get(range_present.group(1), '01')
        year  = range_present.group(2)
        return f"{year}-{month}/"

    # Date range month year – month year
    range_match = re.search(
        r'(\w+)\s+(\d{4})\s*[–\-—to]+\s*(\w+)\s+(\d{4})', v
    )
    if range_match:
        m1 = MONTHS.get(range_match.group(1), '01')
        y1 = range_match.group(2)
        m2 = MONTHS.get(range_match.group(3), '01')
        y2 = range_match.group(4)
        return f"{y1}-{m1}/{y2}-{m2}"

    # Month Year
    month_year = re.search(r'(\w+)\s+(\d{4})', v)
    if month_year:
        month = MONTHS.get(month_year.group(1))
        if month:
            return f"{month_year.group(2)}-{month}"

    # Just year
    year_only = re.search(r'\b(19|20)\d{2}\b', v)
    if year_only:
        return year_only.group(0)

    # Full date MM/DD/YYYY or similar
    full = re.search(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})', v)
    if full:
        return f"{full.group(3)}-{full.group(1).zfill(2)}-{full.group(2).zfill(2)}"

    return value.strip()


def _normalize_contact(value: str) -> str:
    """
    Normalize contact information.
    Emails → lowercase
    Phones → digits only
    URLs   → lowercase, strip trailing slash
    """
    v = value.strip()

    # Email
    if '@' in v:
        return v.lower().strip()

    # URL
    if any(v.lower().startswith(p) for p in ('http', 'www', 'ftp')):
        return v.lower().rstrip('/')

    # Phone — keep digits only
    digits = re.sub(r'\D', '', v)
    if len(digits) >= 7:
        return digits

    return v


def _normalize_name(value: str) -> str:
    """
    Normalize names, organizations, locations to title case.
    Preserves known acronyms (AWS, SQL, FBI etc.)
    """
    if not value:
        return value

    # Known acronyms to preserve
    ACRONYMS = {
        'aws', 'sql', 'fbi', 'cia', 'nsa', 'irs', 'api',
        'llc', 'inc', 'ltd', 'corp', 'lp', 'llp',
        'hipaa', 'pii', 'gdpr', 'sox', 'pci',
        'tx', 'ca', 'ny', 'fl', 'wa', 'il',
        'usa', 'uk', 'eu', 'un',
    }

    words = value.strip().split()
    result = []
    for word in words:
        clean = re.sub(r'[^\w]', '', word.lower())
        if clean in ACRONYMS:
            result.append(word.upper())
        else:
            result.append(word.capitalize())

    return ' '.join(result)


def _normalize_skill(value: str) -> str:
    """Normalize skill names to lowercase."""
    return value.strip().lower()


def _normalize_text(value: str) -> str:
    """Generic text normalization — clean whitespace."""
    # Normalize unicode
    v = unicodedata.normalize('NFKC', value)
    # Collapse whitespace
    v = re.sub(r'\s+', ' ', v).strip()
    return v


# ── CHARACTER OFFSETS ─────────────────────────────────────────────

def find_offsets(value: str, text: str) -> tuple:
    """
    Find the exact character position of a value within text.
    Returns (char_start, char_end) or (-1, -1) if not found.

    Tries exact match first, then case-insensitive,
    then normalized whitespace match.
    """
    if not value or not text:
        return (-1, -1)

    # Exact match
    idx = text.find(value)
    if idx != -1:
        return (idx, idx + len(value))

    # Case-insensitive match
    idx = text.lower().find(value.lower())
    if idx != -1:
        return (idx, idx + len(value))

    # Normalized whitespace match
    v_norm = re.sub(r'\s+', ' ', value.strip())
    t_norm = re.sub(r'\s+', ' ', text)
    idx = t_norm.lower().find(v_norm.lower())
    if idx != -1:
        return (idx, idx + len(v_norm))

    # Partial match — first 20 chars of value
    if len(value) > 20:
        partial = value[:20]
        idx = text.lower().find(partial.lower())
        if idx != -1:
            return (idx, idx + len(value))

    return (-1, -1)


# ── SENSITIVITY DETECTION ─────────────────────────────────────────

# Sensitivity keywords — ordered by priority (most sensitive first)
SENSITIVITY_RULES = [
    ("HIPAA", [
        "patient", "diagnosis", "medical record", "prescription",
        "phi", "protected health", "clinical", "treatment plan",
        "health information", "medical history", "physician",
        "hospital", "medication", "dosage", "symptoms",
        "mental health", "psychiatric", "therapy session",
    ]),
    ("PRIVILEGED", [
        "attorney-client", "attorney client", "privileged",
        "confidential communication", "legal advice",
        "work product", "counsel", "litigation",
    ]),
    ("PII", [
        "social security", "ssn", "date of birth", "dob",
        "passport", "driver license", "driver's license",
        "bank account", "routing number", "credit card",
        "account number", "tax id", "ein",
        "biometric", "fingerprint",
    ]),
    ("CONFIDENTIAL", [
        "nda", "non-disclosure", "trade secret", "proprietary",
        "do not distribute", "confidential", "internal only",
        "restricted", "not for distribution",
    ]),
]


def detect_sensitivity(text: str) -> str:
    """
    Detect sensitivity classification from document text.
    Returns highest sensitivity level found.
    Order: HIPAA > PRIVILEGED > PII > CONFIDENTIAL > PUBLIC

    Uses word-boundary matching for short keywords to avoid
    false positives on partial matches.
    """
    if not text:
        return "PUBLIC"

    import re as _re
    text_lower = text.lower()

    # Require minimum keyword hits for HIPAA to reduce false positives
    # Single short words like "patient" need context
    for label, keywords in SENSITIVITY_RULES:
        hits = 0
        for kw in keywords:
            # Multi-word phrases: simple substring match
            if ' ' in kw or '-' in kw:
                if kw in text_lower:
                    return label
            else:
                # Single words: require word boundary
                if _re.search(r'(?<![a-zA-Z])' + _re.escape(kw) + r'(?![a-zA-Z])', text_lower):
                    hits += 1

        # HIPAA requires 2+ single-word hits to avoid false positives
        # Other labels require 1 hit
        threshold = 2 if label == "HIPAA" else 1
        if hits >= threshold:
            return label

    return "PUBLIC"


# ── CATEGORY DETECTION ────────────────────────────────────────────

CATEGORY_RULES = [
    ("MEDICAL", [
        "patient", "diagnosis", "prescription", "clinical",
        "physician", "hospital", "medication", "symptoms",
        "medical record", "health", "treatment",
    ]),
    ("LEGAL", [
        "agreement", "contract", "whereas", "hereby",
        "indemnify", "liability", "jurisdiction", "arbitration",
        "plaintiff", "defendant", "attorney", "counsel",
        "terms and conditions", "breach",
    ]),
    ("FINANCIAL", [
        "invoice", "payment", "balance due", "receipt",
        "budget", "expense", "revenue", "profit", "loss",
        "tax", "accounting", "fiscal", "quarterly",
        "accounts payable", "accounts receivable",
    ]),
    ("INSURANCE", [
        "policy number", "coverage", "premium", "deductible",
        "claim", "beneficiary", "insured", "underwriter",
        "policyholder", "insurance",
    ]),
    ("COMPLIANCE", [
        "regulatory", "compliance", "audit", "certification",
        "hipaa", "gdpr", "sox", "pci", "iso 27001",
        "risk assessment", "control", "violation",
    ]),
    ("HR", [
        "employee", "salary", "compensation", "benefits",
        "performance review", "offer letter", "termination",
        "onboarding", "payroll", "vacation", "pto",
    ]),
    ("REAL_ESTATE", [
        "lease", "tenant", "landlord", "property",
        "mortgage", "deed", "square feet", "rent",
        "premises", "zoning",
    ]),
    ("GOVERNMENT", [
        "permit", "license", "municipal", "federal",
        "regulation", "statute", "ordinance", "agency",
        "department of", "filed with",
    ]),
    ("ACADEMIC", [
        "course", "lecture", "assignment", "semester",
        "syllabus", "university", "college", "professor",
        "student", "grade", "curriculum", "thesis",
        "research", "abstract", "hypothesis",
    ]),
    ("TECHNICAL", [
        "api", "documentation", "installation", "configuration",
        "endpoint", "database", "server", "deployment",
        "version", "release notes", "specifications",
    ]),
    ("PERSONAL", [
        "resume", "curriculum vitae", "cover letter",
        "personal statement", "dear hiring", "references",
        "work experience", "education", "skills",
        "engineer", "developer", "architect",
        "seeking", "objective", "summary",
    ]),
    ("REFERENCE", [
        "guide", "manual", "faq", "how to", "introduction to",
        "overview", "reference", "glossary", "index",
    ]),
]


def detect_category(text: str, filename: str = "") -> str:
    """
    Detect document category from text content and filename.
    Returns the most likely category.
    Uses word-boundary matching to avoid false positives.
    Requires 2+ keyword hits for most categories.
    """
    import re as _re

    if not text and not filename:
        return "UNKNOWN"

    combined = (text[:2000] + " " + filename).lower()

    # Score each category with word-boundary matching
    scores = {}
    for category, keywords in CATEGORY_RULES:
        score = 0
        for kw in keywords:
            if ' ' in kw:
                # Phrase match
                if kw in combined:
                    score += 2  # phrases worth more
            else:
                if _re.search(r'(?<![a-zA-Z])' + _re.escape(kw) + r'(?![a-zA-Z])', combined):
                    score += 1
        if score >= 2:  # require at least 2 points to classify
            scores[category] = score

    if not scores:
        return "UNKNOWN"

    return max(scores, key=scores.get)


def detect_quality(text: str, page_count: int) -> float:
    """
    Score document quality / usefulness for retrieval (0.0 - 1.0).

    High quality:  structured text, good length, real content
    Low quality:   empty files, package metadata, pure numbers,
                   very short, foreign language fragments
    """
    if not text or len(text.strip()) < 50:
        return 0.0

    score = 0.5  # baseline

    # Length bonus
    words = len(text.split())
    if words > 200:  score += 0.1
    if words > 500:  score += 0.1
    if words > 1000: score += 0.1

    # Structure signals (good)
    if re.search(r'\n\s*\n', text):   score += 0.05  # paragraphs
    if re.search(r'[A-Z][a-z]+', text): score += 0.05  # proper sentences

    # Junk signals (bad)
    # High ratio of non-alpha chars suggests code/data not prose
    alpha_chars = sum(1 for c in text if c.isalpha())
    total_chars = len(text)
    if total_chars > 0:
        alpha_ratio = alpha_chars / total_chars
        if alpha_ratio < 0.3:   score -= 0.3
        elif alpha_ratio < 0.5: score -= 0.1

    # Package/system file signals
    junk_patterns = [
        r'^\s*#\s*\w+\s*$',           # comment-only lines
        r'entry_points',
        r'top_level\.txt',
        r'METADATA\n',
        r'Requires-Python:',
        r'Classifier:',
    ]
    for pattern in junk_patterns:
        if re.search(pattern, text):
            score -= 0.4
            break

    return round(max(0.0, min(1.0, score)), 3)


# ── CLI ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Quick test
    tests = [
        ("AMOUNT",  "$7 million",           "7000000"),
        ("AMOUNT",  "$4,500.00",            "4500"),
        ("AMOUNT",  "50%",                  "0.5"),
        ("DATE",    "January 2024 – Present","2024-01/"),
        ("DATE",    "April 2023",            "2023-04"),
        ("CONTACT", "hey_sellers@icloud.com","hey_sellers@icloud.com"),
        ("CONTACT", "(229) 200-4455",        "2292004455"),
        ("PERSON",  "DALLAS SELLERS",        "Dallas Sellers"),
        ("SKILL",   "LangChain",             "langchain"),
    ]

    print("── Normalization tests ──")
    all_pass = True
    for entity_type, input_val, expected in tests:
        result = normalize(input_val, entity_type)
        status = "✓" if result == expected else "✗"
        if result != expected:
            all_pass = False
        print(f"  {status} [{entity_type}] {input_val!r} → {result!r}"
              f"{'  (expected: ' + repr(expected) + ')' if result != expected else ''}")

    print(f"\n── Offset test ──")
    text   = "Dallas works at Sagis Dx in Houston TX earning $7 million"
    value  = "Sagis Dx"
    start, end = find_offsets(value, text)
    print(f"  '{value}' in text → chars {start}-{end}: '{text[start:end]}'")

    print(f"\n── Sensitivity test ──")
    samples = [
        ("Patient diagnosis report", "HIPAA"),
        ("Attorney-client privileged memo", "PRIVILEGED"),
        ("SSN: 123-45-6789", "PII"),
        ("NDA - Confidential", "CONFIDENTIAL"),
        ("Regular business email", "PUBLIC"),
    ]
    for text_sample, expected_sens in samples:
        result = detect_sensitivity(text_sample)
        status = "✓" if result == expected_sens else "✗"
        print(f"  {status} {text_sample!r} → {result}")

    print(f"\n{'✓ All tests pass' if all_pass else '✗ Some tests failed'}")