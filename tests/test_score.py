import json

import pytest

from aeo_pipeline.brief import Brief
from aeo_pipeline.score import RUBRIC, ScoreReport, render_report, score_page


def lines_for(report: ScoreReport, check: str) -> list[int | None]:
    return [d.line for d in report.check(check).deductions]


def test_rubric_weights_sum_to_100() -> None:
    assert sum(weight for _, _, weight in RUBRIC) == 100


def test_perfect_fixture_scores_100(perfect: str) -> None:
    report = score_page(perfect)
    assert report.score == 100
    assert report.deductions == ()


def test_sloppy_page_scores_low(sloppy: str) -> None:
    report = score_page(sloppy)
    assert report.score == 16
    assert report.score < 40


def test_sloppy_deductions_point_at_the_right_lines(sloppy: str) -> None:
    report = score_page(sloppy)
    assert lines_for(report, "superlatives") == [3, 7]
    assert lines_for(report, "claims") == [9, 10]
    assert lines_for(report, "headings") == [12, 24]
    assert lines_for(report, "faq")[:2] == [18, 21]
    for check in ("definitions", "comparison", "freshness", "schema"):
        assert lines_for(report, check) == [None]
    reasons = {d.line: d.reason for d in report.deductions if d.line is not None}
    assert "'best'" in reasons[3]
    assert "'leading'" in reasons[7]
    assert "H2 to H4" in reasons[12]
    assert "'Pricing' is empty" in reasons[24]


def test_sloppy_with_brief_lists_each_unanswered_question(sloppy: str, fintech: Brief) -> None:
    report = score_page(sloppy, fintech)
    missing = [d.reason for d in report.check("faq").deductions if "brief question" in d.reason]
    assert len(missing) == len(fintech.faq)
    assert report.check("faq").earned == 0


def test_check_never_goes_below_zero(sloppy: str, fintech: Brief) -> None:
    report = score_page(sloppy, fintech)
    for c in report.checks:
        assert 0 <= c.earned <= c.weight
    capped = [d for d in report.deductions if d.points == 0]
    assert capped, "over-cap deductions are still listed, at 0 points"


def test_sourced_superlative_is_not_flagged() -> None:
    page = "# X\n\nX is the fastest option. (Source: Example benchmark)\n"
    assert score_page(page).check("superlatives").deductions == ()


def test_placeholder_source_costs_less_than_none() -> None:
    bare = score_page("# X\n\nX is the best tool.\n")
    held = score_page("# X\n\nX is the best tool. (Source: source needed)\n")
    assert bare.check("superlatives").earned < held.check("superlatives").earned < 10


def test_superlative_in_question_heading_is_exempt() -> None:
    page = "# X\n\n## FAQ\n\n### What is the best way to start?\n\nInstall X.\n"
    assert score_page(page).check("superlatives").deductions == ()


def test_statistic_outside_claims_section_needs_source() -> None:
    report = score_page("# X\n\nX cuts review time by 40%.\n")
    assert lines_for(report, "claims") == [3]


def test_superlative_inside_code_block_is_ignored() -> None:
    page = "# X\n\n```text\nthe best ever\n```\n"
    assert score_page(page).check("superlatives").deductions == ()


@pytest.mark.parametrize(
    ("definition", "problem"),
    [
        ("X is a tool. It is also a library.", "longer than one sentence"),
        ("X is " + "very " * 30 + "long.", "words"),
        ("A tool for doing things.", "does not say what the term is"),
    ],
)
def test_definitions_that_are_not_crisp(definition: str, problem: str) -> None:
    page = f"# X\n\n## Definitions\n\n- **X**: {definition}\n"
    deductions = score_page(page).check("definitions").deductions
    assert len(deductions) == 1
    assert deductions[0].line == 5
    assert problem in deductions[0].reason


def test_definitions_check_brief_entities(devtool: Brief) -> None:
    page = "# Spanlens\n\n## Definitions\n\n- **Spanlens**: Spanlens is a debugger.\n"
    reasons = [d.reason for d in score_page(page, devtool).check("definitions").deductions]
    assert any("'OpenTelemetry'" in r for r in reasons)
    assert not any("'Spanlens'" in r for r in reasons)


def test_faq_answer_placeholder_and_missing_answer() -> None:
    page = (
        "# X\n\n## FAQ\n\n### Is it free?\n\nAnswer needed: add one.\n\n"
        "### Does it scale?\n\n### Who is it for?\n\n- teams\n"
    )
    reasons = [d.reason for d in score_page(page).check("faq").deductions]
    assert any("placeholder" in r for r in reasons)
    assert any("no answer" in r for r in reasons)
    assert any("direct sentence" in r for r in reasons)


def test_faq_questions_match_loosely(fintech: Brief) -> None:
    page = "# Clearpond\n\n## FAQ\n\n### Which accounting systems does Clearpond work with\n\nXero.\n"
    reasons = [d.reason for d in score_page(page, fintech).check("faq").deductions]
    assert not any("Which accounting systems" in r for r in reasons)


def test_comparison_needs_a_competitor_column() -> None:
    page = "# X\n\n## Comparison\n\n| Attribute | X |\n|---|---|\n| Price | Free |\n"
    deductions = score_page(page).check("comparison").deductions
    assert [d.line for d in deductions] == [5]
    assert "competitor column" in deductions[0].reason


def test_comparison_names_every_brief_competitor(fintech: Brief) -> None:
    page = "# C\n\n| Attribute | Clearpond | Tallyforge |\n|---|---|---|\n| Price | 1 | 2 |\n"
    reasons = [d.reason for d in score_page(page, fintech).check("comparison").deductions]
    assert reasons == ["competitor 'Recontra' from the brief is not in the table"]


def test_freshness_date_must_be_iso() -> None:
    report = score_page("# X\n\nLast updated: 10/01/2026\n")
    assert lines_for(report, "freshness") == [3]
    assert score_page("# X\n\nLast updated: 2026-10-01\n").check("freshness").deductions == ()


def test_heading_structure_rules() -> None:
    report = score_page("## No title\n\nText.\n\n# One\n\n# Two\n\nText.\n")
    reasons = [d.reason for d in report.check("headings").deductions]
    assert "page has no H1 title" not in reasons
    assert any("more than one H1" in r for r in reasons)
    assert any("'One' is empty" in r for r in reasons)
    assert score_page("Plain text.\n").check("headings").deductions[0].reason == (
        "page has no H1 title"
    )


def test_schema_block_must_parse_and_have_both_types() -> None:
    broken = score_page("# X\n\n```json\n{not json\n```\n")
    assert broken.check("schema").earned == 0
    assert "does not parse" in broken.check("schema").deductions[0].reason
    partial = score_page('# X\n\n```json\n{"@context": "https://schema.org", "@type": "Product"}\n```\n')
    assert [d.reason for d in partial.check("schema").deductions] == ["JSON-LD has no FAQPage node"]


def test_report_is_json_serializable(sloppy: str) -> None:
    data = json.loads(json.dumps(score_page(sloppy).to_dict()))
    assert data["score"] == 16
    assert len(data["checks"]) == len(RUBRIC)
    assert all({"check", "line", "points", "reason"} <= set(d) for d in data["deductions"])


def test_render_report_lists_every_deduction(sloppy: str) -> None:
    report = score_page(sloppy)
    text = render_report(report, "sloppy.md")
    assert text.startswith("Citation-worthiness: 16/100  (sloppy.md)")
    assert "line 3 " in text and "line 24 " in text
    assert text.count("\n  line ") + text.count("\n  page ") == len(report.deductions)
