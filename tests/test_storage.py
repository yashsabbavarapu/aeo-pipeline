from pathlib import Path

from aeo_pipeline.brief import Brief
from aeo_pipeline.generate import generate_page
from aeo_pipeline.score import score_page
from aeo_pipeline.storage import Store


def test_round_trip_brief_page_and_history(tmp_path: Path, fintech: Brief) -> None:
    page_path = tmp_path / "clearpond.md"
    text = generate_page(fintech)
    with Store(tmp_path / "aeo.db") as store:
        brief_id = store.save_brief(fintech, "fintech.yaml")
        assert store.save_brief(fintech, "fintech.yaml") == brief_id
        page_id = store.save_page(text, page_path, "generated", brief_id=brief_id)
        assert store.save_page(text, page_path, "external") == page_id
        store.save_score(page_id, score_page(text, fintech))
        store.save_score(page_id, score_page(text))
        assert store.brief_for_page(page_path) == fintech
        assert store.brief_id_for_page(page_path) == brief_id
        assert [row.score for row in store.history(page_path)] == [100, 100]
    with Store(tmp_path / "aeo.db") as reopened:
        assert len(reopened.history(page_path)) == 2


def test_unknown_page_has_no_brief_or_history(tmp_path: Path) -> None:
    with Store(tmp_path / "aeo.db") as store:
        assert store.brief_for_page(tmp_path / "nope.md") is None
        assert store.history(tmp_path / "nope.md") == []


def test_new_version_of_page_is_a_new_row(tmp_path: Path) -> None:
    with Store(tmp_path / "aeo.db") as store:
        a = store.save_page("# A\n", tmp_path / "p.md", "external")
        b = store.save_page("# B\n", tmp_path / "p.md", "revised", parent_id=a)
        assert a != b
