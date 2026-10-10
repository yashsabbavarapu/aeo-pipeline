"""Detection rules shared by the scorer and the reviser.

Keeping them in one place means the reviser fixes exactly what the scorer
flags, and the two can never drift apart.
"""

import re
from dataclasses import dataclass

from .page import CodeBlock, Line, Page

# Section names a reader (or an answer engine) would recognize.
DEFINITIONS_H2 = re.compile(r"(?i)\b(definitions?|key terms|glossary)\b")
CLAIMS_H2 = re.compile(r"(?i)\b(key facts|claims|evidence|by the numbers|proof)\b")
FAQ_H2 = re.compile(r"(?i)\b(faq|frequently asked|questions)\b")
COMPARISON_H2 = re.compile(r"(?i)\b(comparison|compared?|versus|vs\.?|alternatives)\b")
SCHEMA_H2 = re.compile(r"(?i)\b(structured data|json-ld|schema)\b")

# "(Source: Name)" or "(Source: Name, <https://...>)". Angle-bracket autolinks
# keep URLs free of parentheses so this stays a simple regex.
SOURCE_MARKER = re.compile(r"\((?:Source|Sources):\s*([^()]+)\)")
PLACEHOLDER_SOURCE = "source needed"
PLACEHOLDER_ANSWER = "Answer needed"

FRESHNESS = re.compile(
    r"(?i)^\W*(last updated|updated|last reviewed|as of)\W*\s*:?\s*\**\s*(\S+?)\**\s*$"
)

# Numbers that read as a factual claim: percentages, multipliers, money,
# and counts of time or people.
STAT = re.compile(
    r"\d+(?:\.\d+)?\s?%"
    r"|\b\d+(?:\.\d+)?x\b"
    r"|\$\s?\d"
    r"|\b\d[\d,]*(?:\.\d+)?\s+(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|weeks?"
    r"|months?|years?|teams?|customers?|companies|users?|engineers?|spans?)\b",
    re.IGNORECASE,
)

SUPERLATIVE = re.compile(
    r"(?i)\b(best|leading|industry[- ]leading|market[- ]leading|fastest|cheapest|"
    r"easiest|greatest|#1|number one|world[- ]class|unmatched|unrivaled|unrivalled|"
    r"unparalleled|premier|revolutionary|ultimate|"
    r"most (?:advanced|powerful|trusted|popular|reliable|secure|accurate|complete))\b"
    r"|#1\b"
)

DEFINITION_ENTRY = re.compile(r"^\s*[-*]\s+\*\*(.+?)\*\*\s*:?\s*(.*)$")
COPULA = re.compile(r"(?i)\b(is|are|refers to|means|describes)\b")
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
MAX_DEFINITION_WORDS = 30

LOOSE_QUESTION = re.compile(r"^\s*(?:(?:Q|Question)\s*[:.]\s*(.+\?)|\*\*(.+\?)\*\*)\s*$")


class Status:
    SOURCED = "sourced"
    PLACEHOLDER = "placeholder"
    MISSING = "missing"


def source_status(text: str) -> str:
    markers = SOURCE_MARKER.findall(text)
    if not markers:
        return Status.MISSING
    if all(m.strip().lower().startswith(PLACEHOLDER_SOURCE) for m in markers):
        return Status.PLACEHOLDER
    return Status.SOURCED


@dataclass(frozen=True)
class ClaimLine:
    line: Line
    status: str
    why: str  # "listed in claims section" or "contains a statistic"


def claim_lines(page: Page) -> list[ClaimLine]:
    """Lines that make a factual claim and therefore need a source.

    Two kinds: every bullet in a claims section, and any prose line elsewhere
    that carries a statistic. Definitions are exempt (they define, not claim)
    and tables are exempt (comparison cells come from the brief's attributes).
    """
    out: list[ClaimLine] = []
    for ln in page.prose_lines():
        h2 = page.h2_of(ln.number)
        stripped = ln.text.strip()
        if h2 is not None and DEFINITIONS_H2.search(h2.text):
            continue
        if FRESHNESS.match(stripped):
            continue
        in_claims = h2 is not None and bool(CLAIMS_H2.search(h2.text))
        if in_claims and re.match(r"^[-*]\s+", stripped):
            out.append(ClaimLine(ln, source_status(stripped), "listed in the claims section"))
        elif STAT.search(stripped):
            out.append(ClaimLine(ln, source_status(stripped), "contains a statistic"))
    return out


@dataclass(frozen=True)
class SuperlativeLine:
    line: Line
    word: str
    status: str


def superlative_lines(page: Page) -> list[SuperlativeLine]:
    """Lines using a superlative. Question headings are exempt (people ask "best X?")."""
    out: list[SuperlativeLine] = []
    for ln in page.lines:
        if ln.in_code or not ln.text.strip():
            continue
        h = page.heading_at(ln.number)
        if h is not None and h.text.rstrip().endswith("?"):
            continue
        m = SUPERLATIVE.search(ln.text)
        if m:
            out.append(SuperlativeLine(ln, m.group(0), source_status(ln.text)))
    return out


def sentence_count(text: str) -> int:
    body = text.strip()
    if not body:
        return 0
    ends = len(SENTENCE_END.findall(body))
    return ends + (0 if SENTENCE_END.search(body[-1:]) else 1)


def definition_problem(term: str, definition: str) -> str | None:
    """Why a definition is not crisp, or None if it is."""
    if not definition.strip():
        return "definition is empty"
    if sentence_count(definition) > 1:
        return "definition runs longer than one sentence"
    words = len(definition.split())
    if words > MAX_DEFINITION_WORDS:
        return f"definition is {words} words (crisp is {MAX_DEFINITION_WORDS} or fewer)"
    if not COPULA.search(definition):
        return "definition does not say what the term is (no 'is', 'are', 'refers to')"
    return None


def normalize_question(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def questions_match(a: str, b: str) -> bool:
    na, nb = normalize_question(a), normalize_question(b)
    if na == nb:
        return True
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.75


def is_paragraph(text: str) -> bool:
    s = text.lstrip()
    if not s or s.startswith(("|", "#", ">", "```", "~~~")):
        return False
    return not re.match(r"^(?:[-*+]|\d+[.)])\s", s)


@dataclass(frozen=True)
class DefinitionEntry:
    line: int
    term: str
    definition: str


def definition_entries(page: Page) -> list[DefinitionEntry]:
    """``- **Term**: definition`` bullets inside the Definitions section."""
    section = page.find_section(DEFINITIONS_H2)
    if section is None:
        return []
    out: list[DefinitionEntry] = []
    for ln in section.lines:
        m = DEFINITION_ENTRY.match(ln.text) if not ln.in_code else None
        if m:
            term = m.group(1).strip().rstrip(":").strip()
            out.append(DefinitionEntry(ln.number, term, m.group(2).strip()))
    return out


@dataclass(frozen=True)
class FaqEntry:
    question: str
    line: int
    answer: str
    answer_line: int | None
    answer_is_prose: bool


def faq_entries(page: Page) -> list[FaqEntry]:
    """H3 questions inside FAQ sections, each with the first line below it."""
    out: list[FaqEntry] = []
    for h2 in page.headings:
        if h2.level != 2 or not FAQ_H2.search(h2.text):
            continue
        for h in page.headings:
            if h.level != 3 or page.h2_of(h.line) != h2:
                continue
            body = [ln for ln in page.section(h).lines if ln.text.strip()]
            first = body[0] if body else None
            out.append(
                FaqEntry(
                    question=h.text,
                    line=h.line,
                    answer=first.text.strip() if first else "",
                    answer_line=first.number if first else None,
                    answer_is_prose=first is not None
                    and not first.in_code
                    and is_paragraph(first.text),
                )
            )
    return out


def loose_questions(page: Page) -> list[Line]:
    """Questions written as plain text (``Q: ...?`` or ``**...?**``), not as H3s."""
    heading_lines = {h.line for h in page.headings}
    return [
        ln
        for ln in page.lines
        if not ln.in_code and ln.number not in heading_lines and LOOSE_QUESTION.match(ln.text)
    ]


def loose_question_text(text: str) -> str:
    m = LOOSE_QUESTION.match(text)
    if not m:
        return ""
    return (m.group(1) or m.group(2) or "").strip()


JSONLD_LANGS = ("json", "jsonld", "json-ld", "ld+json")


def jsonld_blocks(page: Page) -> list[CodeBlock]:
    return [b for b in page.code_blocks if b.lang in JSONLD_LANGS or "@context" in b.content]


def schema_types(data: object) -> set[str]:
    """Every schema.org ``@type`` found anywhere in a parsed JSON-LD document."""
    found: set[str] = set()
    if isinstance(data, dict):
        kind = data.get("@type")
        if isinstance(kind, str):
            found.add(kind)
        elif isinstance(kind, list):
            found.update(k for k in kind if isinstance(k, str))
        for value in data.values():
            found |= schema_types(value)
    elif isinstance(data, list):
        for item in data:
            found |= schema_types(item)
    return found
