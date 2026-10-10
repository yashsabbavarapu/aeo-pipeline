from pathlib import Path

import pytest

from aeo_pipeline.brief import Brief, load_brief

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def devtool() -> Brief:
    return load_brief(EXAMPLES / "briefs" / "devtool.yaml")


@pytest.fixture
def fintech() -> Brief:
    return load_brief(EXAMPLES / "briefs" / "fintech.yaml")


@pytest.fixture
def minimal() -> Brief:
    return load_brief(FIXTURES / "minimal.yaml")


@pytest.fixture
def sloppy() -> str:
    return (EXAMPLES / "pages" / "sloppy.md").read_text(encoding="utf-8")


@pytest.fixture
def perfect() -> str:
    return (FIXTURES / "perfect.md").read_text(encoding="utf-8")
