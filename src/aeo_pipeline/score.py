"""Citation-worthiness scorer: grade a Markdown page 0 to 100.

The score is the sum of eight checks. Each check starts at its weight and
loses points per deduction, never going below zero. Every deduction names the
line it is about (or ``None`` when the problem is something missing from the
whole page) and a reason a writer can act on.

This is a heuristic. It measures whether a page has the structure answer
engines tend to cite; it does not ask a real answer engine anything.
"""

import json
from dataclasses import dataclass
from datetime import date

from .brief import Brief
from .page import Page, Table
from .rules import (
    COMPARISON_H2,
    DEFINITIONS_H2,
    FAQ_H2,
    FRESHNESS,
    PLACEHOLDER_ANSWER,
    Status,
    claim_lines,
    definition_entries,
    definition_problem,
    faq_entries,
    jsonld_blocks,
    loose_questions,
    questions_match,
    schema_types,
    superlative_lines,
)

# (key, label, weight). Weights sum to 100.
RUBRIC: tuple[tuple[str, str, int], ...] = (
    ("definitions", "Entity definitions", 20),
    ("claims", "Claim-to-source binding", 20),
    ("faq", "FAQ coverage", 20),
    ("comparison", "Comparison table", 10),
    ("freshness", "Freshness date", 5),
    ("headings", "Heading structure", 10),
    ("superlatives", "Sourced superlatives", 10),
    ("schema", "Structured data", 5),
)
WEIGHTS = {key: weight for key, _, weight in RUBRIC}

# Per-deduction penalties. A whole missing section costs the check's full weight.
DEF_NOT_CRISP = 4
DEF_MISSING_ENTITY = 5
CLAIM_UNSOURCED = 5
CLAIM_PLACEHOLDER = 2
FAQ_LOOSE = 2
FAQ_NO_ANSWER = 4
FAQ_PLACEHOLDER = 3
FAQ_NOT_DIRECT = 2
CMP_NO_COMPETITOR = 5
CMP_NO_ROWS = 3
CMP_MISSING_RIVAL = 2
FRESH_BAD_DATE = 3
HEAD_H1 = 4
HEAD_SKIP = 2
HEAD_EMPTY = 2
SUPER_UNSOURCED = 5
SUPER_PLACEHOLDER = 2
SCHEMA_MISSING_TYPE = 2

_Raw = tuple[int | None, int, str]  # (line, points, reason)


@dataclass(frozen=True)
class Deduction:
    check: str
    line: int | None
    points: int
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {"check": self.check, "line": self.line, "points": self.points, "reason": self.reason}


@dataclass(frozen=True)
class CheckResult:
    key: str
    label: str
    weight: int
    deductions: tuple[Deduction, ...]

    @property
    def earned(self) -> int:
        return self.weight - sum(d.points for d in self.deductions)


@dataclass(frozen=True)
class ScoreReport:
    checks: tuple[CheckResult, ...]
    used_brief: bool

    @property
    def score(self) -> int:
        return sum(c.earned for c in self.checks)

    @property
    def deductions(self) -> tuple[Deduction, ...]:
        return tuple(d for c in self.checks for d in c.deductions)

    def check(self, key: str) -> CheckResult:
        for c in self.checks:
            if c.key == key:
                return c
        raise KeyError(key)

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "used_brief": self.used_brief,
            "checks": [
                {"key": c.key, "label": c.label, "weight": c.weight, "earned": c.earned}
                for c in self.checks
            ],
            "deductions": [d.to_dict() for d in self.deductions],
        }


def score_page(text: str, brief: Brief | None = None) -> ScoreReport:
    """Score a page. With a brief, FAQ and entity coverage are checked against it."""
    page = Page(text)
    raw: dict[str, list[_Raw]] = {
        "definitions": _check_definitions(page, brief),
        "claims": _check_claims(page),
        "faq": _check_faq(page, brief),
        "comparison": _check_comparison(page, brief),
        "freshness": _check_freshness(page),
        "headings": _check_headings(page),
        "superlatives": _check_superlatives(page),
        "schema": _check_schema(page),
    }
    checks = tuple(
        CheckResult(key, label, weight, _clip(key, weight, raw[key])) for key, label, weight in RUBRIC
    )
    return ScoreReport(checks, used_brief=brief is not None)


def _clip(key: str, weight: int, items: list[_Raw]) -> tuple[Deduction, ...]:
    """Charge deductions in order until the check's weight is used up.

    Later deductions are still listed (at 0 points) so the report stays complete.
    """
    left = weight
    out: list[Deduction] = []
    for line, points, reason in items:
        charged = min(points, left)
        left -= charged
        out.append(Deduction(key, line, charged, reason))
    return tuple(out)


def _check_definitions(page: Page, brief: Brief | None) -> list[_Raw]:
    section = page.find_section(DEFINITIONS_H2)
    if section is None:
        return [(None, WEIGHTS["definitions"],
                 "no Definitions section: add '## Definitions' with one "
                 "'- **Term**: Term is ...' bullet per key entity")]
    entries = definition_entries(page)
    if not entries:
        return [(section.heading.line, WEIGHTS["definitions"],
                 "Definitions section has no '- **Term**: definition' entries")]
    out: list[_Raw] = []
    for e in entries:
        problem = definition_problem(e.term, e.definition)
        if problem:
            out.append((e.line, DEF_NOT_CRISP, f"definition of {e.term!r} is not crisp: {problem}"))
    if brief is not None:
        defined = {e.term.lower() for e in entries}
        for entity in brief.entities:
            if entity.name.lower() not in defined:
                out.append((section.heading.line, DEF_MISSING_ENTITY,
                            f"brief entity {entity.name!r} is not defined"))
    return out


def _check_claims(page: Page) -> list[_Raw]:
    out: list[_Raw] = []
    for c in claim_lines(page):
        if c.status == Status.MISSING:
            out.append((c.line.number, CLAIM_UNSOURCED,
                        f"claim has no source ({c.why}): add '(Source: ...)' on the same line"))
        elif c.status == Status.PLACEHOLDER:
            out.append((c.line.number, CLAIM_PLACEHOLDER,
                        f"claim source is a placeholder ({c.why}): replace 'source needed'"))
    return out


def _check_faq(page: Page, brief: Brief | None) -> list[_Raw]:
    out: list[_Raw] = [
        (ln.number, FAQ_LOOSE, "question is plain text: make it an H3 ('### ...?') with the "
         "answer directly below")
        for ln in loose_questions(page)
    ]
    faq = page.find_section(FAQ_H2)
    entries = faq_entries(page)
    if faq is None:
        out.append((None, WEIGHTS["faq"], "no FAQ section: add '## FAQ' with each question as an H3"))
        return out
    for e in entries:
        if e.answer_line is None:
            out.append((e.line, FAQ_NO_ANSWER, f"question {e.question!r} has no answer below it"))
        elif e.answer.startswith(PLACEHOLDER_ANSWER):
            out.append((e.answer_line, FAQ_PLACEHOLDER, f"answer to {e.question!r} is a placeholder"))
        elif not e.answer_is_prose:
            out.append((e.answer_line, FAQ_NOT_DIRECT,
                        f"answer to {e.question!r} does not open with a direct sentence"))
    if brief is not None and brief.faq:
        per_question = max(1, round(WEIGHTS["faq"] / len(brief.faq)))
        for seed in brief.faq:
            if not any(questions_match(seed.question, e.question) for e in entries):
                out.append((faq.heading.line, per_question,
                            f"brief question not answered as an H3: {seed.question!r}"))
    elif not entries:
        out.append((faq.heading.line, WEIGHTS["faq"], "FAQ section has no H3 questions"))
    return out


def _comparison_table(page: Page) -> Table | None:
    if not page.tables:
        return None
    section = page.find_section(COMPARISON_H2)
    if section is not None:
        numbers = {ln.number for ln in section.lines}
        inside = [t for t in page.tables if t.start in numbers]
        if inside:
            return max(inside, key=lambda t: len(t.header))
    return max(page.tables, key=lambda t: len(t.header))


def _check_comparison(page: Page, brief: Brief | None) -> list[_Raw]:
    table = _comparison_table(page)
    if table is None:
        return [(None, WEIGHTS["comparison"],
                 "no comparison table: add a table of attributes vs named competitors")]
    out: list[_Raw] = []
    if len(table.header) < 3:
        out.append((table.start, CMP_NO_COMPETITOR,
                    "comparison table has no competitor column (needs attribute, product, rival)"))
    if not table.rows:
        out.append((table.start, CMP_NO_ROWS, "comparison table has no rows"))
    if brief is not None:
        header = {cell.lower() for cell in table.header}
        for rival in brief.competitors:
            if rival.name.lower() not in header:
                out.append((table.start, CMP_MISSING_RIVAL,
                            f"competitor {rival.name!r} from the brief is not in the table"))
    return out


def _check_freshness(page: Page) -> list[_Raw]:
    for ln in page.prose_lines():
        m = FRESHNESS.match(ln.text.strip())
        if not m:
            continue
        token = m.group(2).strip("*.,")
        try:
            date.fromisoformat(token)
        except ValueError:
            return [(ln.number, FRESH_BAD_DATE, f"freshness date {token!r} is not YYYY-MM-DD")]
        return []
    return [(None, WEIGHTS["freshness"],
             "no freshness date: add 'Last updated: YYYY-MM-DD' under the title")]


def _check_headings(page: Page) -> list[_Raw]:
    out: list[_Raw] = []
    h1s = [h for h in page.headings if h.level == 1]
    if not h1s:
        out.append((None, HEAD_H1, "page has no H1 title"))
    for extra in h1s[1:]:
        out.append((extra.line, HEAD_H1, "more than one H1: a page should have exactly one title"))
    prev = 0
    for h in page.headings:
        if prev and h.level > prev + 1:
            out.append((h.line, HEAD_SKIP, f"heading jumps from H{prev} to H{h.level}"))
        prev = h.level
    for i, h in enumerate(page.headings):
        nxt = page.headings[i + 1] if i + 1 < len(page.headings) else None
        if nxt is not None and nxt.level > h.level:
            continue
        end = nxt.line if nxt is not None else len(page.lines) + 1
        body = [ln for ln in page.lines[h.line : end - 1] if ln.text.strip()]
        if not body:
            out.append((h.line, HEAD_EMPTY, f"section {h.text!r} is empty"))
    return out


def _check_superlatives(page: Page) -> list[_Raw]:
    out: list[_Raw] = []
    for s in superlative_lines(page):
        if s.status == Status.MISSING:
            out.append((s.line.number, SUPER_UNSOURCED,
                        f"superlative {s.word!r} has no source on the same line"))
        elif s.status == Status.PLACEHOLDER:
            out.append((s.line.number, SUPER_PLACEHOLDER,
                        f"superlative {s.word!r} is backed only by a 'source needed' placeholder"))
    return out


def _check_schema(page: Page) -> list[_Raw]:
    blocks = jsonld_blocks(page)
    if not blocks:
        return [(None, WEIGHTS["schema"],
                 "no schema.org JSON-LD block: add a fenced ```json block with FAQPage and Product")]
    out: list[_Raw] = []
    types: set[str] = set()
    parsed = 0
    for b in blocks:
        try:
            data: object = json.loads(b.content)
        except json.JSONDecodeError as exc:
            out.append((b.start, WEIGHTS["schema"], f"JSON-LD does not parse: {exc.msg} "
                        f"(block line {exc.lineno})"))
            continue
        parsed += 1
        types |= schema_types(data)
    if parsed:
        for needed in ("FAQPage", "Product"):
            if needed not in types:
                out.append((blocks[0].start, SCHEMA_MISSING_TYPE, f"JSON-LD has no {needed} node"))
    return out


def render_report(report: ScoreReport, label: str = "") -> str:
    """Human-readable report: score, per-check table, then every deduction."""
    title = f"Citation-worthiness: {report.score}/100"
    lines = [title + (f"  ({label})" if label else "")]
    if not report.used_brief:
        lines.append("No brief given: FAQ and entity coverage are checked against the page only.")
    lines += ["", "Checks:"]
    width = max(len(c.label) for c in report.checks)
    for c in report.checks:
        lines.append(f"  {c.label.ljust(width)}  {c.earned:>3}/{c.weight}")
    lines.append("")
    if not report.deductions:
        lines.append("Deductions: none")
        return "\n".join(lines) + "\n"
    lines.append(f"Deductions ({len(report.deductions)}):")
    lines += [f"  {format_deduction(d)}" for d in report.deductions]
    return "\n".join(lines) + "\n"


def format_deduction(d: Deduction) -> str:
    where = f"line {d.line}" if d.line is not None else "page"
    note = "" if d.points else " (check already at 0)"
    return f"{where.ljust(9)} {d.check.ljust(12)} {('-' + str(d.points)).ljust(4)} {d.reason}{note}"
