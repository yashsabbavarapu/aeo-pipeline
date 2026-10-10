from datetime import date

import pytest

from aeo_pipeline.brief import Brief, BriefError, parse_brief
from aeo_pipeline.yamlish import YamlError, loads


def test_example_brief_parses(devtool: Brief) -> None:
    assert devtool.product == "Spanlens"
    assert devtool.updated == date(2026, 10, 1)
    assert [c.name for c in devtool.competitors] == ["Spantrail Cloud", "Ochre APM"]
    assert dict(devtool.product_attributes)["Data leaves your machine"] == "No"
    assert devtool.slug == "spanlens"
    assert len(devtool.sha) == 12


@pytest.mark.parametrize("missing", ["product", "description", "entities", "claims", "faq"])
def test_required_fields(missing: str) -> None:
    fields = {
        "product": "product: X",
        "description": "description: X is a thing.",
        "audience": "audience: People",
        "entities": "entities:\n  - name: X\n    definition: X is a thing.",
        "claims": "claims:\n  - text: X works.\n    source: Docs",
        "faq": "faq:\n  - question: What is X?",
    }
    del fields[missing]
    with pytest.raises(BriefError):
        parse_brief("\n".join(fields.values()) + "\n")


def test_bad_date_is_rejected(devtool: Brief) -> None:
    text = devtool.source_text.replace("updated: 2026-10-01", "updated: yesterday")
    with pytest.raises(BriefError, match="YYYY-MM-DD"):
        parse_brief(text)


def test_yamlish_nested_structures() -> None:
    data = loads("a:\n  - name: x\n    tags:\n      - one\n      - 'two # not a comment'\nb: \"q\\n\"\n")
    assert data == {"a": [{"name": "x", "tags": ["one", "two # not a comment"]}], "b": "q\n"}


@pytest.mark.parametrize("text", ["a: [1, 2]\n", "a: &x 1\n", "a: |\n  text\n", "a: 1\na: 2\n"])
def test_yamlish_rejects_unsupported_syntax(text: str) -> None:
    with pytest.raises(YamlError):
        loads(text)
