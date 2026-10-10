"""A minimal Markdown page model: just enough structure for scoring and revision.

We do not need a full CommonMark parser. AEO checks care about headings,
bullets, tables, fenced code blocks, and which H2 section a line lives in.
Line numbers are 1-based so deductions can point at the exact line.
"""

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^(```|~~~)\s*([\w+-]*)\s*$")


@dataclass(frozen=True)
class Line:
    number: int
    text: str
    in_code: bool


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    line: int


@dataclass(frozen=True)
class CodeBlock:
    start: int
    lang: str
    content: str


@dataclass(frozen=True)
class Table:
    start: int
    header: tuple[str, ...]
    rows: tuple[tuple[int, tuple[str, ...]], ...]


@dataclass(frozen=True)
class Section:
    """A heading and every line up to the next heading of the same or higher level."""

    heading: Heading
    lines: tuple[Line, ...]


class Page:
    def __init__(self, text: str) -> None:
        self.text = text
        self.lines: tuple[Line, ...] = tuple(_scan_lines(text))
        self.headings: tuple[Heading, ...] = tuple(
            Heading(len(m.group(1)), m.group(2).strip(), line.number)
            for line in self.lines
            if not line.in_code and (m := _HEADING.match(line.text))
        )
        self.code_blocks: tuple[CodeBlock, ...] = tuple(_scan_code(self.lines))
        self.tables: tuple[Table, ...] = tuple(_scan_tables(self.lines))

    def line(self, number: int) -> Line:
        return self.lines[number - 1]

    def heading_at(self, number: int) -> Heading | None:
        for h in self.headings:
            if h.line == number:
                return h
        return None

    def section(self, heading: Heading) -> Section:
        end = len(self.lines) + 1
        for h in self.headings:
            if h.line > heading.line and h.level <= heading.level:
                end = h.line
                break
        return Section(heading, self.lines[heading.line : end - 1])

    def find_section(self, pattern: re.Pattern[str], level: int = 2) -> Section | None:
        for h in self.headings:
            if h.level == level and pattern.search(h.text):
                return self.section(h)
        return None

    def h2_of(self, number: int) -> Heading | None:
        """The nearest H2 at or above a line, or None if the line is before any H2."""
        current: Heading | None = None
        for h in self.headings:
            if h.line > number:
                break
            if h.level <= 2:
                current = h if h.level == 2 else None
        return current

    def prose_lines(self) -> list[Line]:
        """Non-blank lines outside code blocks, headings, and tables."""
        heading_lines = {h.line for h in self.headings}
        return [
            ln
            for ln in self.lines
            if ln.text.strip()
            and not ln.in_code
            and ln.number not in heading_lines
            and not ln.text.lstrip().startswith("|")
        ]


def _scan_lines(text: str) -> list[Line]:
    out: list[Line] = []
    in_code = False
    for number, raw in enumerate(text.splitlines(), start=1):
        if _FENCE.match(raw.strip()):
            out.append(Line(number, raw, True))
            in_code = not in_code
            continue
        out.append(Line(number, raw, in_code))
    return out


def _scan_code(lines: tuple[Line, ...]) -> list[CodeBlock]:
    blocks: list[CodeBlock] = []
    start: int | None = None
    lang = ""
    body: list[str] = []
    for ln in lines:
        m = _FENCE.match(ln.text.strip()) if ln.in_code else None
        if m and start is None:
            start, lang, body = ln.number, m.group(2).lower(), []
        elif m and start is not None:
            blocks.append(CodeBlock(start, lang, "\n".join(body)))
            start = None
        elif start is not None:
            body.append(ln.text)
    return blocks


def split_row(text: str) -> tuple[str, ...]:
    inner = text.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return tuple(cell.strip() for cell in inner.split("|"))


def _is_separator(cells: tuple[str, ...]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def _scan_tables(lines: tuple[Line, ...]) -> list[Table]:
    tables: list[Table] = []
    i = 0
    while i < len(lines) - 1:
        a, b = lines[i], lines[i + 1]
        if (
            not a.in_code
            and a.text.lstrip().startswith("|")
            and b.text.lstrip().startswith("|")
            and _is_separator(split_row(b.text))
        ):
            rows: list[tuple[int, tuple[str, ...]]] = []
            j = i + 2
            while j < len(lines) and lines[j].text.lstrip().startswith("|"):
                rows.append((lines[j].number, split_row(lines[j].text)))
                j += 1
            tables.append(Table(a.number, split_row(a.text), tuple(rows)))
            i = j
            continue
        i += 1
    return tables
