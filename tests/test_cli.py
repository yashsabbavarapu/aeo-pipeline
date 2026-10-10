import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aeo_pipeline.cli import main

from .conftest import EXAMPLES, ROOT

DEVTOOL = str(EXAMPLES / "briefs" / "devtool.yaml")
FINTECH = str(EXAMPLES / "briefs" / "fintech.yaml")
SLOPPY = str(EXAMPLES / "pages" / "sloppy.md")


@pytest.fixture
def db(tmp_path: Path) -> list[str]:
    return ["--db", str(tmp_path / "aeo.db")]


def test_generate_writes_page_and_reports_score(
    tmp_path: Path, db: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "nested" / "page.md"
    assert main(["generate", "--brief", DEVTOOL, "--output", str(out), *db]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Spanlens\n")
    assert "Citation-worthiness: 100/100" in capsys.readouterr().out


def test_generate_is_byte_identical_across_runs(tmp_path: Path) -> None:
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    main(["generate", "--brief", FINTECH, "--output", str(a), "--no-db"])
    main(["generate", "--brief", FINTECH, "--output", str(b), "--no-db"])
    assert a.read_bytes() == b.read_bytes()


def test_score_finds_brief_from_database(
    tmp_path: Path, db: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "page.md"
    main(["generate", "--brief", FINTECH, "--output", str(out), *db])
    capsys.readouterr()
    assert main(["score", "--page", str(out), "--json", *db]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["score"] == 100 and data["used_brief"] is True


def test_score_min_score_sets_exit_code(db: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["score", "--page", SLOPPY, "--min-score", "50", *db]) == 1
    assert main(["score", "--page", SLOPPY, "--min-score", "10", *db]) == 0
    out = capsys.readouterr().out
    assert "Citation-worthiness: 16/100" in out
    assert "line 3 " in out


def test_revise_shows_score_moving_up(
    tmp_path: Path, db: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "sloppy-v2.md"
    args = ["revise", "--page", SLOPPY, "--output", str(out), "--brief", FINTECH, "--updated", "2026-10-10"]
    assert main([*args, *db]) == 0
    printed = capsys.readouterr().out
    assert "Citation-worthiness: 16 -> 94 (+78)" in printed
    assert "Changes applied (11):" in printed
    assert main(["score", "--page", str(out), "--json", *db]) == 0
    assert json.loads(capsys.readouterr().out)["score"] == 94
    assert main(["history", "--page", str(out), *db]) == 0
    assert "94/100" in capsys.readouterr().out


def test_history_without_records(db: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["history", "--page", "never-scored.md", *db]) == 0
    assert "No scores recorded" in capsys.readouterr().out


def test_bad_inputs_exit_2(tmp_path: Path, db: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["score", "--page", str(tmp_path / "missing.md"), *db]) == 2
    bad = tmp_path / "bad.yaml"
    bad.write_text("product: X\n", encoding="utf-8")
    assert main(["generate", "--brief", str(bad), "--output", str(tmp_path / "x.md"), *db]) == 2
    assert "invalid brief" in capsys.readouterr().err


def test_bad_date_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["generate", "--brief", DEVTOOL, "--output", str(tmp_path / "x.md"), "--updated", "soon"])
    assert exc.value.code == 2


def test_python_dash_m_entry_point(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "AEO_PIPELINE_DB": str(tmp_path / "a.db")}
    result = subprocess.run(
        [sys.executable, "-m", "aeo_pipeline", "score", "--page", SLOPPY],
        capture_output=True, text=True, env=env, cwd=tmp_path, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Citation-worthiness: 16/100")
    assert (tmp_path / "a.db").exists()
