"""SQLite storage (stdlib ``sqlite3``) for briefs, pages, and score history.

Storage is a record, not an input: generation and scoring never read from it,
except that ``score`` and ``revise`` look up the brief a page was generated
from when no ``--brief`` is passed. Timestamps live only here, so the pages
themselves stay deterministic.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType

from .brief import Brief, parse_brief
from .score import ScoreReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS briefs (
    id INTEGER PRIMARY KEY,
    sha TEXT NOT NULL UNIQUE,
    product TEXT NOT NULL,
    path TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    sha TEXT NOT NULL,
    text TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('generated', 'revised', 'external')),
    brief_id INTEGER REFERENCES briefs(id),
    parent_id INTEGER REFERENCES pages(id),
    created_at TEXT NOT NULL,
    UNIQUE (path, sha)
);
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    score INTEGER NOT NULL,
    used_brief INTEGER NOT NULL,
    report TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class HistoryRow:
    created_at: str
    score: int
    page_sha: str
    kind: str


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _key(path: str | Path) -> str:
    return str(Path(path).resolve())


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def __enter__(self) -> "Store":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def save_brief(self, brief: Brief, path: str | Path) -> int:
        self.conn.execute(
            "INSERT OR IGNORE INTO briefs (sha, product, path, text, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (brief.sha, brief.product, _key(path), brief.source_text, _now()),
        )
        row = self.conn.execute("SELECT id FROM briefs WHERE sha = ?", (brief.sha,)).fetchone()
        self.conn.commit()
        return int(row[0])

    def save_page(
        self,
        text: str,
        path: str | Path,
        kind: str,
        brief_id: int | None = None,
        parent_id: int | None = None,
    ) -> int:
        """Record a page version. Saving the same text at the same path is a no-op."""
        key, sha = _key(path), text_sha(text)
        row = self.conn.execute(
            "SELECT id FROM pages WHERE path = ? AND sha = ?", (key, sha)
        ).fetchone()
        if row is not None:
            if brief_id is not None:
                self.conn.execute(
                    "UPDATE pages SET brief_id = COALESCE(brief_id, ?) WHERE id = ?",
                    (brief_id, row[0]),
                )
                self.conn.commit()
            return int(row[0])
        cur = self.conn.execute(
            "INSERT INTO pages (path, sha, text, kind, brief_id, parent_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, sha, text, kind, brief_id, parent_id, _now()),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def save_score(self, page_id: int, report: ScoreReport) -> int:
        cur = self.conn.execute(
            "INSERT INTO scores (page_id, score, used_brief, report, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (page_id, report.score, int(report.used_brief), json.dumps(report.to_dict()), _now()),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def brief_for_page(self, path: str | Path) -> Brief | None:
        """The brief most recently linked to any version of the page at ``path``."""
        row = self.conn.execute(
            "SELECT b.text FROM pages p JOIN briefs b ON b.id = p.brief_id "
            "WHERE p.path = ? ORDER BY p.id DESC LIMIT 1",
            (_key(path),),
        ).fetchone()
        return parse_brief(str(row[0])) if row is not None else None

    def brief_id_for_page(self, path: str | Path) -> int | None:
        row = self.conn.execute(
            "SELECT brief_id FROM pages WHERE path = ? AND brief_id IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (_key(path),),
        ).fetchone()
        return int(row[0]) if row is not None else None

    def history(self, path: str | Path) -> list[HistoryRow]:
        rows = self.conn.execute(
            "SELECT s.created_at, s.score, p.sha, p.kind FROM scores s "
            "JOIN pages p ON p.id = s.page_id WHERE p.path = ? ORDER BY s.id",
            (_key(path),),
        ).fetchall()
        return [HistoryRow(str(r[0]), int(r[1]), str(r[2]), str(r[3])) for r in rows]
