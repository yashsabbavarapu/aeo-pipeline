"""A small, strict YAML subset loader (stdlib only).

Briefs are hand-written config, so we support the block-style subset that
config files actually use and reject everything else loudly:

- mappings (``key: value``) and nested mappings
- sequences (``- item``), including sequences of mappings
- plain, single-quoted, and double-quoted scalars
- ``#`` comments and blank lines

Not supported (raises YamlError): flow collections (``[a, b]``, ``{a: b}``),
anchors and aliases, block scalars (``|``, ``>``), multi-document streams,
tags. All scalars load as strings; the brief layer decides what they mean.
"""

from dataclasses import dataclass

YamlValue = str | list["YamlValue"] | dict[str, "YamlValue"]


class YamlError(ValueError):
    """Raised for malformed or unsupported input, with a line number."""


@dataclass(frozen=True)
class _Line:
    number: int
    indent: int
    text: str


def loads(source: str) -> YamlValue:
    """Parse a YAML-subset document into nested dicts, lists, and strings."""
    lines = _tokenize(source)
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0].indent)
    if index != len(lines):
        extra = lines[index]
        raise YamlError(f"line {extra.number}: unexpected indentation")
    return value


def _tokenize(source: str) -> list[_Line]:
    out: list[_Line] = []
    for number, raw in enumerate(source.splitlines(), start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError(f"line {number}: tabs are not allowed for indentation")
        text = _strip_comment(raw).rstrip()
        if not text.strip():
            continue
        stripped = text.lstrip()
        if stripped in ("---", "..."):
            if out:
                raise YamlError(f"line {number}: multi-document streams are not supported")
            continue
        out.append(_Line(number, len(text) - len(stripped), stripped))
    return out


def _strip_comment(raw: str) -> str:
    quote: str | None = None
    for i, ch in enumerate(raw):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i]
    return raw


def _parse_block(lines: list[_Line], index: int, indent: int) -> tuple[YamlValue, int]:
    if lines[index].text.startswith("- ") or lines[index].text == "-":
        return _parse_sequence(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_sequence(lines: list[_Line], index: int, indent: int) -> tuple[YamlValue, int]:
    items: list[YamlValue] = []
    while index < len(lines) and lines[index].indent == indent:
        line = lines[index]
        if not (line.text.startswith("- ") or line.text == "-"):
            raise YamlError(f"line {line.number}: expected a '- ' sequence item")
        rest = line.text[1:].lstrip()
        if not rest:
            index += 1
            if index >= len(lines) or lines[index].indent <= indent:
                raise YamlError(f"line {line.number}: empty sequence item")
            value, index = _parse_block(lines, index, lines[index].indent)
            items.append(value)
            continue
        if _split_key(rest, line.number) is not None:
            # "- key: value" starts an inline mapping; its siblings sit at
            # the column where "key" begins.
            child_indent = indent + (len(line.text) - len(rest))
            synthetic = [_Line(line.number, child_indent, rest)]
            tail = index + 1
            while tail < len(lines) and lines[tail].indent > indent:
                synthetic.append(lines[tail])
                tail += 1
            value, used = _parse_mapping(synthetic, 0, child_indent)
            if used != len(synthetic):
                bad = synthetic[used]
                raise YamlError(f"line {bad.number}: unexpected indentation")
            items.append(value)
            index = tail
            continue
        items.append(_scalar(rest, line.number))
        index += 1
    if index < len(lines) and lines[index].indent > indent:
        raise YamlError(f"line {lines[index].number}: unexpected indentation")
    return items, index


def _parse_mapping(lines: list[_Line], index: int, indent: int) -> tuple[YamlValue, int]:
    mapping: dict[str, YamlValue] = {}
    while index < len(lines) and lines[index].indent == indent:
        line = lines[index]
        split = _split_key(line.text, line.number)
        if split is None:
            raise YamlError(f"line {line.number}: expected 'key: value'")
        key, rest = split
        if key in mapping:
            raise YamlError(f"line {line.number}: duplicate key {key!r}")
        index += 1
        if rest:
            mapping[key] = _scalar(rest, line.number)
            continue
        if index < len(lines) and lines[index].indent > indent:
            mapping[key], index = _parse_block(lines, index, lines[index].indent)
        elif (
            index < len(lines)
            and lines[index].indent == indent
            and lines[index].text.startswith("-")
        ):
            # Sequences may sit at the same indent as their parent key.
            mapping[key], index = _parse_sequence(lines, index, indent)
        else:
            mapping[key] = ""
    if index < len(lines) and lines[index].indent > indent:
        raise YamlError(f"line {lines[index].number}: unexpected indentation")
    return mapping, index


def _split_key(text: str, number: int) -> tuple[str, str] | None:
    """Split 'key: rest' into its parts, or None if this is not a mapping line."""
    if text[0] in ("'", '"'):
        quote = text[0]
        end = text.find(quote, 1)
        if end == -1:
            raise YamlError(f"line {number}: unterminated quoted key")
        after = text[end + 1 :]
        if after == ":" or after.startswith(": "):
            return text[1:end], after[1:].strip()
        return None
    for i, ch in enumerate(text):
        if ch == ":" and (i + 1 == len(text) or text[i + 1] == " "):
            key = text[:i].strip()
            if not key:
                raise YamlError(f"line {number}: empty key")
            return key, text[i + 1 :].strip()
        if ch in ("'", '"'):
            return None
    return None


def _scalar(text: str, number: int) -> str:
    if text[0] in ("[", "{"):
        raise YamlError(f"line {number}: flow collections are not supported")
    if text[0] in ("&", "*", "!"):
        raise YamlError(f"line {number}: anchors, aliases, and tags are not supported")
    if text in ("|", ">") or text[:2] in ("|-", "|+", ">-", ">+"):
        raise YamlError(f"line {number}: block scalars are not supported")
    if text[0] == '"':
        if len(text) < 2 or not text.endswith('"'):
            raise YamlError(f"line {number}: unterminated double-quoted string")
        return _unescape_double(text[1:-1], number)
    if text[0] == "'":
        if len(text) < 2 or not text.endswith("'"):
            raise YamlError(f"line {number}: unterminated single-quoted string")
        return text[1:-1].replace("''", "'")
    return text


_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/"}


def _unescape_double(body: str, number: int) -> str:
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            if i + 1 >= len(body) or body[i + 1] not in _ESCAPES:
                raise YamlError(f"line {number}: unsupported escape in string")
            out.append(_ESCAPES[body[i + 1]])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)
