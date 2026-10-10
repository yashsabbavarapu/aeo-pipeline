"""Command line: generate, score, revise, history.

    python -m aeo_pipeline generate --brief brief.yaml --output page.md
    python -m aeo_pipeline score --page page.md
    python -m aeo_pipeline revise --page page.md --output page-v2.md
    python -m aeo_pipeline history --page page.md

Every command records what it did in a SQLite file (``--db``, default
``aeo-pipeline.db`` or ``$AEO_PIPELINE_DB``). ``--no-db`` skips storage.
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from . import __version__
from .brief import Brief, BriefError, load_brief
from .generate import generate_page
from .revise import revise_page
from .score import format_deduction, render_report, score_page
from .storage import Store
from .yamlish import YamlError

DEFAULT_DB = "aeo-pipeline.db"


def _iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {text!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--db",
        default=os.environ.get("AEO_PIPELINE_DB", DEFAULT_DB),
        help=f"SQLite file for briefs, pages, and score history (default: {DEFAULT_DB})",
    )
    common.add_argument("--no-db", action="store_true", help="do not read or write the database")

    parser = argparse.ArgumentParser(
        prog="aeo-pipeline",
        description="Brief in, citable page out, scored for citation-worthiness.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", parents=[common], help="render a page from a brief")
    gen.add_argument("--brief", required=True, help="brief YAML file")
    gen.add_argument("--output", required=True, help="where to write the Markdown page")
    gen.add_argument("--updated", type=_iso_date, help="freshness date (overrides the brief)")

    sc = sub.add_parser("score", parents=[common], help="grade a page 0 to 100")
    sc.add_argument("--page", required=True, help="Markdown page to score")
    sc.add_argument("--brief", help="brief to check FAQ and entity coverage against")
    sc.add_argument("--json", action="store_true", help="print the report as JSON")
    sc.add_argument("--min-score", type=int, help="exit 1 if the score is below this")

    rv = sub.add_parser("revise", parents=[common], help="score, apply one fix pass, re-score")
    rv.add_argument("--page", required=True, help="Markdown page to revise")
    rv.add_argument("--output", required=True, help="where to write the revised page")
    rv.add_argument("--brief", help="brief to pull sources, definitions, and answers from")
    rv.add_argument("--updated", type=_iso_date, help="freshness date to add if missing")

    hist = sub.add_parser("history", parents=[common], help="score history for a page")
    hist.add_argument("--page", required=True, help="page path as used with score or revise")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = None if args.no_db else Store(args.db)
    try:
        if args.command == "generate":
            return _generate(args, store)
        if args.command == "score":
            return _score(args, store)
        if args.command == "revise":
            return _revise(args, store)
        return _history(args, store)
    except (BriefError, YamlError) as exc:
        print(f"error: invalid brief: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()


def _resolve_brief(arg: str | None, page: str, store: Store | None) -> tuple[Brief | None, int | None]:
    if arg:
        brief = load_brief(arg)
        return brief, store.save_brief(brief, arg) if store else None
    if store is None:
        return None, None
    return store.brief_for_page(page), store.brief_id_for_page(page)


def _write(path: str, text: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def _generate(args: argparse.Namespace, store: Store | None) -> int:
    brief = load_brief(args.brief)
    text = generate_page(brief, updated=args.updated)
    _write(args.output, text)
    report = score_page(text, brief)
    if store is not None:
        brief_id = store.save_brief(brief, args.brief)
        page_id = store.save_page(text, args.output, "generated", brief_id=brief_id)
        store.save_score(page_id, report)
    lines = len(text.splitlines())
    print(f"Wrote {args.output} ({lines} lines) from {args.brief}")
    print(f"Citation-worthiness: {report.score}/100")
    return 0


def _score(args: argparse.Namespace, store: Store | None) -> int:
    text = Path(args.page).read_text(encoding="utf-8")
    brief, brief_id = _resolve_brief(args.brief, args.page, store)
    report = score_page(text, brief)
    if store is not None:
        page_id = store.save_page(text, args.page, "external", brief_id=brief_id)
        store.save_score(page_id, report)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_report(report, args.page), end="")
    if args.min_score is not None and report.score < args.min_score:
        print(f"score {report.score} is below --min-score {args.min_score}", file=sys.stderr)
        return 1
    return 0


def _revise(args: argparse.Namespace, store: Store | None) -> int:
    text = Path(args.page).read_text(encoding="utf-8")
    brief, brief_id = _resolve_brief(args.brief, args.page, store)
    before = score_page(text, brief)
    revision = revise_page(text, brief, updated=args.updated)
    after = score_page(revision.text, brief)
    _write(args.output, revision.text)
    if store is not None:
        parent = store.save_page(text, args.page, "external", brief_id=brief_id)
        store.save_score(parent, before)
        child = store.save_page(
            revision.text, args.output, "revised", brief_id=brief_id, parent_id=parent
        )
        store.save_score(child, after)

    delta = after.score - before.score
    print(f"Revised {args.page} -> {args.output}")
    print(f"Citation-worthiness: {before.score} -> {after.score} ({delta:+d})")
    if brief is None:
        print("No brief: definitions and sources come from the page or become placeholders.")
    print()
    if revision.changes:
        print(f"Changes applied ({len(revision.changes)}):")
        for change in revision.changes:
            print(f"  - {change}")
    else:
        print("Changes applied: none (nothing the reviser can fix)")
    print()
    if after.deductions:
        print(f"Remaining deductions ({len(after.deductions)}), for a human to fix:")
        for d in after.deductions:
            print(f"  {format_deduction(d)}")
    else:
        print("Remaining deductions: none")
    return 0


def _history(args: argparse.Namespace, store: Store | None) -> int:
    if store is None:
        print("error: history needs the database (drop --no-db)", file=sys.stderr)
        return 2
    rows = store.history(args.page)
    if not rows:
        print(f"No scores recorded for {args.page} in {store.path}")
        return 0
    print(f"Score history for {args.page}:")
    for row in rows:
        print(f"  {row.created_at}  {row.score:>3}/100  {row.kind:<9}  page {row.page_sha}")
    return 0
