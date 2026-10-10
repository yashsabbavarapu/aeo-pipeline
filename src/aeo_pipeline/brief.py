"""Product briefs: the single input the pipeline turns into a page.

A brief is YAML (see ``examples/briefs/``). Everything the generator says
must trace back to a field here: it never invents specs, sources, or answers.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .yamlish import YamlValue, loads


class BriefError(ValueError):
    """Raised when a brief is missing required fields or has the wrong shape."""


@dataclass(frozen=True)
class Entity:
    name: str
    definition: str


@dataclass(frozen=True)
class Claim:
    text: str
    source: str
    url: str = ""


@dataclass(frozen=True)
class Competitor:
    name: str
    attributes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FaqSeed:
    question: str
    answer: str = ""


@dataclass(frozen=True)
class Brief:
    product: str
    description: str
    audience: str
    entities: tuple[Entity, ...]
    claims: tuple[Claim, ...]
    competitors: tuple[Competitor, ...]
    faq: tuple[FaqSeed, ...]
    product_attributes: tuple[tuple[str, str], ...] = ()
    url: str = ""
    updated: date | None = None
    source_text: str = field(default="", compare=False, repr=False)

    @property
    def slug(self) -> str:
        return "".join(c if c.isalnum() else "-" for c in self.product.lower()).strip("-")

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.source_text.encode("utf-8")).hexdigest()[:12]


def load_brief(path: str | Path) -> Brief:
    """Read and validate a brief from a YAML file."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_brief(text)


def parse_brief(text: str) -> Brief:
    """Validate a YAML-subset string into a Brief."""
    data = loads(text)
    root = _as_map(data, "brief")
    product = _req_str(root, "product")
    entities = tuple(
        Entity(_req_str(m, "name"), _req_str(m, "definition"))
        for m in _maps(root, "entities", required=True)
    )
    claims = tuple(
        Claim(_req_str(m, "text"), _req_str(m, "source"), _opt_str(m, "url"))
        for m in _maps(root, "claims", required=True)
    )
    competitors = tuple(
        Competitor(_req_str(m, "name"), _attrs(m, f"competitor {m.get('name', '?')!r}"))
        for m in _maps(root, "competitors", required=False)
    )
    faq = tuple(
        FaqSeed(_req_str(m, "question"), _opt_str(m, "answer"))
        for m in _maps(root, "faq", required=True)
    )
    updated_raw = _opt_str(root, "updated")
    updated: date | None = None
    if updated_raw:
        try:
            updated = date.fromisoformat(updated_raw)
        except ValueError as exc:
            raise BriefError(f"'updated' must be YYYY-MM-DD, got {updated_raw!r}") from exc
    return Brief(
        product=product,
        description=_req_str(root, "description"),
        audience=_req_str(root, "audience"),
        entities=entities,
        claims=claims,
        competitors=competitors,
        faq=faq,
        product_attributes=_attrs(root, "product"),
        url=_opt_str(root, "url"),
        updated=updated,
        source_text=text,
    )


def _as_map(value: YamlValue, where: str) -> dict[str, YamlValue]:
    if not isinstance(value, dict):
        raise BriefError(f"{where}: expected a mapping")
    return value


def _req_str(m: dict[str, YamlValue], key: str) -> str:
    value = m.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BriefError(f"missing or empty required field {key!r}")
    return value.strip()


def _opt_str(m: dict[str, YamlValue], key: str) -> str:
    value = m.get(key, "")
    if not isinstance(value, str):
        raise BriefError(f"field {key!r} must be a string")
    return value.strip()


def _maps(m: dict[str, YamlValue], key: str, *, required: bool) -> list[dict[str, YamlValue]]:
    value = m.get(key)
    if value is None or value == "":
        if required:
            raise BriefError(f"missing required list {key!r}")
        return []
    if not isinstance(value, list):
        raise BriefError(f"{key!r} must be a list")
    if required and not value:
        raise BriefError(f"{key!r} must not be empty")
    return [_as_map(item, f"{key} item") for item in value]


def _attrs(m: dict[str, YamlValue], where: str) -> tuple[tuple[str, str], ...]:
    value = m.get("attributes")
    if value is None or value == "":
        return ()
    if not isinstance(value, dict):
        raise BriefError(f"{where}: 'attributes' must be a mapping")
    out: list[tuple[str, str]] = []
    for name, raw in value.items():
        if not isinstance(raw, str):
            raise BriefError(f"{where}: attribute {name!r} must be a string")
        out.append((name, raw.strip()))
    return tuple(out)
