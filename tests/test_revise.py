from datetime import date

from aeo_pipeline.brief import Brief
from aeo_pipeline.generate import generate_page
from aeo_pipeline.page import Page
from aeo_pipeline.revise import revise_page
from aeo_pipeline.rules import PLACEHOLDER_SOURCE, definition_entries, faq_entries
from aeo_pipeline.score import score_page

DAY = date(2026, 10, 10)


def test_revise_raises_sloppy_score_without_brief(sloppy: str) -> None:
    before = score_page(sloppy).score
    after = score_page(revise_page(sloppy, updated=DAY).text).score
    assert (before, after) == (16, 80)


def test_revise_with_brief_raises_score_further(sloppy: str, fintech: Brief) -> None:
    before = score_page(sloppy, fintech).score
    after = score_page(revise_page(sloppy, fintech, DAY).text, fintech).score
    assert (before, after) == (16, 94)


def test_every_check_is_at_least_as_good_after_revision(sloppy: str, fintech: Brief) -> None:
    for brief in (None, fintech):
        before = score_page(sloppy, brief)
        after = score_page(revise_page(sloppy, brief, DAY).text, brief)
        for b, a in zip(before.checks, after.checks):
            assert a.earned >= b.earned, a.key


def test_loose_claims_get_placeholders_without_brief(sloppy: str) -> None:
    text = revise_page(sloppy, updated=DAY).text
    for needle in ("92% of bank transactions", "6 days faster", "the best reconciliation"):
        line = next(ln for ln in text.splitlines() if needle in ln)
        assert line.endswith(f"(Source: {PLACEHOLDER_SOURCE})")


def test_loose_claims_bind_to_brief_sources(sloppy: str, fintech: Brief) -> None:
    text = revise_page(sloppy, fintech, DAY).text
    line = next(ln for ln in text.splitlines() if "92% of bank transactions" in ln)
    assert line.endswith("(Source: Clearpond customer data, Q2 2026, 140 companies)")


def test_missing_definitions_are_added(sloppy: str, fintech: Brief) -> None:
    page_only = definition_entries(Page(revise_page(sloppy, updated=DAY).text))
    assert [e.term for e in page_only] == ["Clearpond"]
    from_brief = definition_entries(Page(revise_page(sloppy, fintech, DAY).text))
    assert [e.term for e in from_brief] == [e.name for e in fintech.entities]


def test_loose_text_becomes_faq_h3s(sloppy: str) -> None:
    text = revise_page(sloppy, updated=DAY).text
    entries = faq_entries(Page(text))
    assert [e.question for e in entries] == [
        "Which accounting systems does Clearpond work with?",
        "How long does setup take?",
    ]
    assert entries[0].answer == "Clearpond works with QuickBooks Online and Xero today."
    assert "Q:" not in text


def test_skipped_heading_level_is_closed(sloppy: str) -> None:
    text = revise_page(sloppy, updated=DAY).text
    assert "### Security" in text and "#### Security" not in text


def test_freshness_date_comes_from_argument_then_brief(sloppy: str, fintech: Brief) -> None:
    assert "Last updated: 2026-10-10" in revise_page(sloppy, updated=DAY).text
    assert "Last updated: 2026-09-15" in revise_page(sloppy, fintech).text


def test_changes_are_reported(sloppy: str) -> None:
    changes = revise_page(sloppy, updated=DAY).changes
    assert "line 12: heading 'Security' H4 -> H3 (no skipped levels)" in changes
    assert any("Definitions section" in c for c in changes)
    assert any("JSON-LD" in c for c in changes)


def test_revise_is_deterministic_and_idempotent(sloppy: str, fintech: Brief) -> None:
    for brief in (None, fintech):
        once = revise_page(sloppy, brief, DAY)
        assert once == revise_page(sloppy, brief, DAY)
        twice = revise_page(once.text, brief, DAY)
        assert twice.text == once.text
        assert twice.changes == ()


def test_revise_leaves_a_perfect_page_alone(devtool: Brief, perfect: str) -> None:
    generated = generate_page(devtool)
    assert revise_page(generated, devtool) == revise_page(generated, devtool)
    assert revise_page(generated, devtool).text == generated
    assert revise_page(perfect).text == perfect
    assert revise_page(perfect).changes == ()


def test_revise_does_not_touch_code_blocks() -> None:
    page = "# X\n\nLast updated: 2026-01-01\n\n```text\nthe best 90% ever\n\n\nQ: in code?\n```\n"
    text = revise_page(page, updated=DAY).text
    assert "the best 90% ever\n\n\nQ: in code?\n" in text
