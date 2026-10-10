"""One deterministic improvement pass over a page.

The reviser fixes what the scorer flags, using the same detection rules
(``rules.py``), so a revision can only move the score up. It never invents
facts: real sources, definitions, and answers come only from the brief, or
from sentences already on the page. Where neither has the data it leaves a
visible placeholder ("source needed", "Answer needed") that the scorer still
charges for, at a lower rate than a silent gap.

Passes, in order:

1. heading levels: demote extra H1s, close skipped levels (H2 to H4 becomes H3)
2. sources: bind each unsourced claim or superlative to the matching brief
   claim's source, else to a "source needed" placeholder
3. definitions: trim multi-sentence definitions to their first sentence, then
   add missing entities (from the brief, or "X is a ..." sentences on the page)
4. FAQ: move ``Q: ...?`` / ``**...?**`` text into H3 questions, then add brief
   questions the page does not answer
5. freshness date, comparison table (brief only), and JSON-LD, when missing
"""

import re
from dataclasses import dataclass, field
from datetime import date

from .brief import Brief
from .generate import (
    answer_for,
    build_jsonld,
    comparison_section,
    definition_line,
    schema_section,
    source_note,
)
from .page import Page
from .rules import (
    DEFINITIONS_H2,
    FAQ_H2,
    FRESHNESS,
    PLACEHOLDER_ANSWER,
    PLACEHOLDER_SOURCE,
    SCHEMA_H2,
    SOURCE_MARKER,
    STAT,
    SUPERLATIVE,
    Status,
    claim_lines,
    definition_entries,
    definition_problem,
    faq_entries,
    jsonld_blocks,
    loose_question_text,
    loose_questions,
    normalize_question,
    questions_match,
    superlative_lines,
)

_FENCE = re.compile(r"^\s*(```|~~~)")
_FIRST_SENTENCE = re.compile(r"^(.+?[.!?])(?=\s|$)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_DEF_SENTENCE = re.compile(
    r"^((?:[A-Z][\w-]*)(?:\s+[A-Z][\w-]*){0,3})\s+(?:is|are)\s+(?:an?|the)\s+\S"
)
_PRONOUNS = {"it", "this", "that", "these", "those", "they", "there", "here", "we", "our", "you"}


@dataclass(frozen=True)
class Revision:
    text: str
    changes: tuple[str, ...]


@dataclass
class _Block:
    """An H2 heading line and its body lines (the preamble has heading "")."""

    heading: str
    body: list[str] = field(default_factory=list)


def revise_page(text: str, brief: Brief | None = None, updated: date | None = None) -> Revision:
    """Apply one improvement pass. Same inputs always give the same output.

    ``updated`` is the freshness date to add if the page has none; it falls
    back to the brief's date, then to today.
    """
    changes: list[str] = []
    lines = text.splitlines()

    _fix_headings(Page(text), lines, changes)
    page = _reparse(lines)
    _bind_sources(page, lines, brief, changes)
    page = _reparse(lines)
    _trim_definitions(page, lines, changes)
    page = _reparse(lines)

    stamp = _stamp(page, brief, updated)
    pairs, removed = _pull_loose_questions(page)
    preamble, blocks = _split(page, removed)

    _ensure_freshness(page, preamble, stamp, changes)
    _ensure_definitions(page, blocks, brief, changes)
    _ensure_faq(page, blocks, pairs, brief, changes)
    _ensure_comparison(page, blocks, brief, changes)

    revised = _render(preamble, blocks)
    final = Page(revised)
    if not jsonld_blocks(final):
        pairs_now = [(e.question, e.answer) for e in faq_entries(final) if e.answer_line is not None]
        title = next((h.text for h in final.headings if h.level == 1), "")
        jsonld = build_jsonld(brief, pairs_now, stamp, product=title)
        blocks.append(_block_from(schema_section(jsonld)))
        changes.append("added a schema.org JSON-LD block (Product + FAQPage)")
    revised = _render(preamble, blocks)
    return Revision(revised, tuple(changes))


def _reparse(lines: list[str]) -> Page:
    return Page("\n".join(lines) + "\n")


def _fix_headings(page: Page, lines: list[str], changes: list[str]) -> None:
    prev = 0
    seen_h1 = False
    for h in page.headings:
        level = h.level
        if level == 1:
            if seen_h1:
                level = 2
            seen_h1 = True
        if prev and level > prev + 1:
            level = prev + 1
        if level != h.level:
            lines[h.line - 1] = "#" * level + " " + h.text
            why = "only one H1 per page" if h.level == 1 else "no skipped levels"
            changes.append(f"line {h.line}: heading {h.text!r} H{h.level} -> H{level} ({why})")
        prev = level


def _source_for(text: str, brief: Brief | None) -> tuple[str, bool]:
    """The source marker for a line, and whether it came from the brief."""
    if brief is not None:
        needle = normalize_question(SOURCE_MARKER.sub("", text))
        for claim in brief.claims:
            target = normalize_question(claim.text)
            if target and (target in needle or needle in target):
                return source_note(claim.source, claim.url), True
    return source_note(PLACEHOLDER_SOURCE), False


def _bind_sources(page: Page, lines: list[str], brief: Brief | None, changes: list[str]) -> None:
    todo: dict[int, str] = {}
    for c in claim_lines(page):
        if c.status == Status.MISSING:
            todo.setdefault(c.line.number, "claim")
    for s in superlative_lines(page):
        if s.status == Status.MISSING:
            todo.setdefault(s.line.number, f"superlative {s.word!r}")
    for number in sorted(todo):
        current = lines[number - 1].rstrip()
        marker, from_brief = _source_for(current, brief)
        lines[number - 1] = f"{current} {marker}"
        how = "bound to the brief's source" if from_brief else f"marked '{PLACEHOLDER_SOURCE}'"
        changes.append(f"line {number}: {todo[number]} {how}")


def _trim_definitions(page: Page, lines: list[str], changes: list[str]) -> None:
    for e in definition_entries(page):
        if definition_problem(e.term, e.definition) != "definition runs longer than one sentence":
            continue
        m = _FIRST_SENTENCE.match(e.definition)
        if m:
            lines[e.line - 1] = definition_line(e.term, m.group(1))
            changes.append(f"line {e.line}: trimmed the definition of {e.term!r} to one sentence")


def _stamp(page: Page, brief: Brief | None, updated: date | None) -> str:
    if updated is not None:
        return updated.isoformat()
    for ln in page.prose_lines():
        m = FRESHNESS.match(ln.text.strip())
        if m:
            try:
                return date.fromisoformat(m.group(2).strip("*.,")).isoformat()
            except ValueError:
                break
    if brief is not None and brief.updated is not None:
        return brief.updated.isoformat()
    return date.today().isoformat()


def _pull_loose_questions(page: Page) -> tuple[list[tuple[str, str]], set[int]]:
    """Collect plain-text Q and A pairs, and the line numbers they occupied."""
    pairs: list[tuple[str, str]] = []
    removed: set[int] = set()
    heading_lines = {h.line for h in page.headings}
    loose = {ln.number for ln in loose_questions(page)}
    for number in sorted(loose):
        question = loose_question_text(page.line(number).text)
        removed.add(number)
        answer: list[str] = []
        n = number + 1
        while n <= len(page.lines):
            ln = page.line(n)
            if not ln.text.strip() or ln.in_code or n in heading_lines or n in loose:
                break
            answer.append(ln.text.strip())
            removed.add(n)
            n += 1
        pairs.append((question, " ".join(answer)))
    return pairs, removed


def _split(page: Page, removed: set[int]) -> tuple[list[str], list[_Block]]:
    h2_lines = {h.line for h in page.headings if h.level == 2}
    preamble: list[str] = []
    blocks: list[_Block] = []
    for ln in page.lines:
        if ln.number in removed:
            continue
        if ln.number in h2_lines:
            blocks.append(_Block(ln.text))
        elif blocks:
            blocks[-1].body.append(ln.text)
        else:
            preamble.append(ln.text)
    return preamble, blocks


def _block_from(section: str) -> _Block:
    head, *body = section.rstrip("\n").splitlines()
    return _Block(head, body)


def _find(blocks: list[_Block], pattern: re.Pattern[str]) -> int | None:
    for i, b in enumerate(blocks):
        if pattern.search(b.heading.lstrip("#")):
            return i
    return None


def _append(block: _Block, new_lines: list[str]) -> None:
    while block.body and not block.body[-1].strip():
        block.body.pop()
    continues_list = bool(block.body) and block.body[-1].lstrip().startswith(("- ", "* "))
    if not (continues_list and new_lines[0].startswith("- ")):
        block.body.append("")
    block.body += new_lines
    block.body.append("")


def _ensure_freshness(page: Page, preamble: list[str], stamp: str, changes: list[str]) -> None:
    if any(FRESHNESS.match(ln.text.strip()) for ln in page.prose_lines()):
        return
    at = next((i + 1 for i, t in enumerate(preamble) if t.startswith("# ")), 0)
    preamble[at:at] = ["", f"Last updated: {stamp}", ""]
    changes.append(f"added a freshness date: 'Last updated: {stamp}'")


def _page_definitions(page: Page, defined: set[str]) -> list[tuple[str, str]]:
    """``Term is a ...`` sentences already on the page, crisp and claim-free."""
    found: list[tuple[str, str]] = []
    for ln in page.prose_lines():
        text = SOURCE_MARKER.sub("", ln.text).strip().lstrip(">-* ").strip()
        for sentence in _SENTENCE_SPLIT.split(text):
            m = _DEF_SENTENCE.match(sentence)
            if not m:
                continue
            term = m.group(1)
            if (
                term.lower() in _PRONOUNS
                or term.lower() in defined
                or SUPERLATIVE.search(sentence)
                or STAT.search(sentence)
                or definition_problem(term, sentence) is not None
            ):
                continue
            defined.add(term.lower())
            found.append((term, sentence))
    return found


def _ensure_definitions(
    page: Page, blocks: list[_Block], brief: Brief | None, changes: list[str]
) -> None:
    defined = {e.term.lower() for e in definition_entries(page)}
    if brief is not None:
        new = [(e.name, e.definition) for e in brief.entities if e.name.lower() not in defined]
        origin = "from the brief"
    else:
        new = _page_definitions(page, set(defined))
        origin = "from sentences already on the page"
    if not new:
        return
    entries = [definition_line(term, definition) for term, definition in new]
    names = ", ".join(term for term, _ in new)
    index = _find(blocks, DEFINITIONS_H2)
    if index is None:
        blocks.insert(0, _Block("## Definitions", ["", *entries, ""]))
        changes.append(f"added a Definitions section {origin}: {names}")
    else:
        _append(blocks[index], entries)
        changes.append(f"added missing definitions {origin}: {names}")


def _faq_block(question: str, answer: str) -> list[str]:
    q = " ".join(question.split())
    q = q if q.endswith("?") else q + "?"
    body = answer or f"{PLACEHOLDER_ANSWER}: add a direct answer to this question."
    return [f"### {q}", "", body, ""]


def _ensure_faq(
    page: Page,
    blocks: list[_Block],
    pairs: list[tuple[str, str]],
    brief: Brief | None,
    changes: list[str],
) -> None:
    asked = [e.question for e in faq_entries(page)]
    new: list[str] = []
    for question, answer in pairs:
        new += _faq_block(question, answer)
        asked.append(question)
    if pairs:
        changes.append(f"turned {len(pairs)} plain-text question(s) into H3 FAQ entries")
    added = 0
    if brief is not None:
        for seed in brief.faq:
            if not any(questions_match(seed.question, q) for q in asked):
                new += _faq_block(seed.question, answer_for(brief, seed.question))
                asked.append(seed.question)
                added += 1
    if added:
        changes.append(f"added {added} FAQ question(s) from the brief")
    if not new:
        return
    index = _find(blocks, FAQ_H2)
    if index is None:
        at = _find(blocks, SCHEMA_H2)
        blocks.insert(len(blocks) if at is None else at, _Block("## FAQ", ["", *new]))
        changes.append("added an FAQ section")
    else:
        _append(blocks[index], new)


def _ensure_comparison(
    page: Page, blocks: list[_Block], brief: Brief | None, changes: list[str]
) -> None:
    if page.tables or brief is None or not brief.competitors:
        return
    at = _find(blocks, FAQ_H2)
    if at is None:
        at = _find(blocks, SCHEMA_H2)
    blocks.insert(len(blocks) if at is None else at, _block_from(comparison_section(brief)))
    names = ", ".join(c.name for c in brief.competitors)
    changes.append(f"added a comparison table from the brief vs {names}")


def _render(preamble: list[str], blocks: list[_Block]) -> str:
    out = list(preamble)
    for b in blocks:
        out += ["", b.heading, *b.body]
    return _tidy(out)


def _tidy(lines: list[str]) -> str:
    """Collapse runs of blank lines outside code blocks and trim the ends."""
    out: list[str] = []
    in_code = False
    for text in lines:
        if _FENCE.match(text):
            in_code = not in_code
        if not in_code and not text.strip() and (not out or not out[-1].strip()):
            continue
        out.append(text.rstrip() if not in_code else text)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + "\n"
