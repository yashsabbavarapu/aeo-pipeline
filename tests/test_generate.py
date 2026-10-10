import json
import re

import pytest

from aeo_pipeline.brief import Brief, parse_brief
from aeo_pipeline.generate import NOT_STATED, generate_page
from aeo_pipeline.page import Page
from aeo_pipeline.rules import (
    CLAIMS_H2,
    COMPARISON_H2,
    DEFINITIONS_H2,
    FAQ_H2,
    PLACEHOLDER_ANSWER,
    Status,
    claim_lines,
    definition_entries,
    definition_problem,
    faq_entries,
    jsonld_blocks,
    schema_types,
)
from aeo_pipeline.score import score_page

from .conftest import EXAMPLES

BRIEFS = ["devtool", "fintech"]


@pytest.fixture(params=BRIEFS)
def brief(request: pytest.FixtureRequest) -> Brief:
    path = EXAMPLES / "briefs" / f"{request.param}.yaml"
    return parse_brief(path.read_text(encoding="utf-8"))


def test_every_required_section_is_present(brief: Brief) -> None:
    page = Page(generate_page(brief))
    assert [h.text for h in page.headings if h.level == 1] == [brief.product]
    for pattern in (DEFINITIONS_H2, CLAIMS_H2, COMPARISON_H2, FAQ_H2):
        assert page.find_section(pattern) is not None, pattern.pattern
    assert re.search(r"(?m)^Last updated: \d{4}-\d{2}-\d{2}$", page.text)
    assert len(jsonld_blocks(page)) == 1


def test_each_entity_defined_in_one_crisp_sentence(brief: Brief) -> None:
    entries = definition_entries(Page(generate_page(brief)))
    assert [e.term for e in entries] == [e.name for e in brief.entities]
    for e in entries:
        assert definition_problem(e.term, e.definition) is None, e


def test_every_claim_is_followed_by_its_source(brief: Brief) -> None:
    page = Page(generate_page(brief))
    found = claim_lines(page)
    assert len(found) >= len(brief.claims)
    assert all(c.status == Status.SOURCED for c in found)
    for claim in brief.claims:
        line = next(ln.text for ln in page.lines if claim.text.rstrip(".") in ln.text)
        assert line.endswith(")") and f"(Source: {claim.source}" in line


def test_faq_has_an_h3_per_question_with_the_answer_first(brief: Brief) -> None:
    entries = faq_entries(Page(generate_page(brief)))
    assert len(entries) == len(brief.faq)
    for entry, seed in zip(entries, brief.faq):
        assert entry.question.rstrip("?") == seed.question.rstrip("?")
        assert entry.answer_is_prose
        if seed.answer:
            assert entry.answer == seed.answer


def test_comparison_table_uses_only_brief_attributes(brief: Brief) -> None:
    page = Page(generate_page(brief))
    table = page.tables[0]
    assert table.header == ("Attribute", brief.product, *(c.name for c in brief.competitors))
    stated = {name for name, _ in brief.product_attributes}
    for c in brief.competitors:
        stated |= {name for name, _ in c.attributes}
    assert {row[0] for _, row in table.rows} == stated
    columns = [dict(brief.product_attributes)] + [dict(c.attributes) for c in brief.competitors]
    for _, row in table.rows:
        for cell, attrs in zip(row[1:], columns):
            assert cell == attrs.get(row[0], NOT_STATED)


def test_jsonld_has_product_and_faqpage(brief: Brief) -> None:
    block = jsonld_blocks(Page(generate_page(brief)))[0]
    assert block.lang == "json"
    data = json.loads(block.content)
    assert {"Product", "FAQPage"} <= schema_types(data)
    faq = next(n for n in data["@graph"] if n["@type"] == "FAQPage")
    assert len(faq["mainEntity"]) == len(brief.faq)


def test_generated_example_pages_score_100(brief: Brief) -> None:
    report = score_page(generate_page(brief), brief)
    assert report.score == 100, report.deductions


def test_brief_without_competitors_still_gets_a_comparison_section(minimal: Brief) -> None:
    page = Page(generate_page(minimal))
    assert page.find_section(COMPARISON_H2) is not None
    assert page.tables[0].header == ("Attribute", "Tinyform")
    report = score_page(page.text, minimal)
    assert report.check("comparison").earned < report.check("comparison").weight


def test_unanswered_question_gets_placeholder_not_invented_answer(minimal: Brief) -> None:
    text = generate_page(minimal)
    entries = faq_entries(Page(text))
    assert entries[1].answer.startswith(PLACEHOLDER_ANSWER)
    data = json.loads(jsonld_blocks(Page(text))[0].content)
    faq = next(n for n in data["@graph"] if n["@type"] == "FAQPage")
    assert [q["name"] for q in faq["mainEntity"]] == ["What is Tinyform?"]


def test_generation_is_deterministic(brief: Brief) -> None:
    again = parse_brief(brief.source_text)
    assert generate_page(brief) == generate_page(brief) == generate_page(again)


@pytest.mark.parametrize(("name", "page"), [("devtool", "spanlens"), ("fintech", "clearpond")])
def test_example_pages_match_generator_output(name: str, page: str) -> None:
    brief = parse_brief((EXAMPLES / "briefs" / f"{name}.yaml").read_text(encoding="utf-8"))
    golden = (EXAMPLES / "pages" / f"{page}.md").read_text(encoding="utf-8")
    assert generate_page(brief) == golden


def test_updated_argument_overrides_brief_date(brief: Brief) -> None:
    from datetime import date

    text = generate_page(brief, updated=date(2030, 1, 2))
    assert "Last updated: 2030-01-02" in text
    assert '"dateModified": "2030-01-02"' in text


def test_output_has_no_em_or_en_dashes(brief: Brief) -> None:
    text = generate_page(brief)
    assert "\u2014" not in text and "\u2013" not in text
