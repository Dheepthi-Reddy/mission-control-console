"""Reports saved in a SQLite file, so they survive a restart.

Each call opens its own connection: FastAPI runs sync routes on a thread pool,
and a short-lived connection per call avoids sharing one across threads.
"""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.domain.analysis import AnalysisOut
from app.domain.briefing import Briefing
from app.domain.report import Report, ReportIn

if TYPE_CHECKING:
    from app.pipeline.runner import Analysis

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    station     TEXT    NOT NULL,
    wind_knots  REAL    NOT NULL,
    temp_c      REAL    NOT NULL,
    fuel_pct    REAL    NOT NULL,
    note        TEXT    NOT NULL
);

-- One briefing per report. status is only ever set to 'approved' by approve().
CREATE TABLE IF NOT EXISTS briefings (
    report_id          INTEGER PRIMARY KEY REFERENCES reports(id),
    text               TEXT    NOT NULL,
    status             TEXT    NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved')),
    rounds             INTEGER NOT NULL,
    reviewer_accepted  INTEGER NOT NULL,
    approved_by        TEXT,
    approved_at        TEXT
);

-- What the pipeline decided for a report. Lists are stored as JSON text.
CREATE TABLE IF NOT EXISTS analyses (
    report_id           INTEGER PRIMARY KEY REFERENCES reports(id),
    status              TEXT    NOT NULL CHECK (status IN ('processing', 'ready', 'failed')),
    error               TEXT,
    subsystem           TEXT,
    severity            TEXT,
    effective_severity  TEXT,
    verdict             TEXT,
    violations          TEXT    NOT NULL DEFAULT '[]',
    brief_by_minutes    INTEGER,
    flags               TEXT    NOT NULL DEFAULT '[]',
    needs_review        INTEGER,
    review_reasons      TEXT    NOT NULL DEFAULT '[]',
    total_cost_usd      TEXT,
    cost_complete       INTEGER,
    updated_at          TEXT    NOT NULL
);

-- One row per pipeline step: the console's trace cards. cost_usd is exact decimal text.
CREATE TABLE IF NOT EXISTS trace_steps (
    report_id      INTEGER NOT NULL REFERENCES reports(id),
    seq            INTEGER NOT NULL,
    name           TEXT    NOT NULL,
    kind           TEXT    NOT NULL CHECK (kind IN ('model', 'code')),
    model          TEXT,
    input_tokens   INTEGER NOT NULL,
    output_tokens  INTEGER NOT NULL,
    cost_usd       TEXT,
    summary        TEXT    NOT NULL,
    PRIMARY KEY (report_id, seq)
);
"""

COLUMNS = ("id", "created_at", "name", "station", "wind_knots", "temp_c", "fuel_pct", "note")
BRIEFING_COLUMNS = (
    "report_id", "text", "status", "rounds", "reviewer_accepted", "approved_by", "approved_at"
)


class NoBriefing(LookupError):
    pass


class AlreadyApproved(Exception):
    pass


class ReportStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def add(self, report: ReportIn) -> Report:
        created_at = datetime.now(UTC).isoformat()
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO reports (created_at, name, station, wind_knots, temp_c, fuel_pct, note)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    created_at,
                    report.name,
                    report.station,
                    report.wind_knots,
                    report.temp_c,
                    report.fuel_pct,
                    report.note,
                ),
            )
            report_id = cur.lastrowid
        return self.get(report_id)

    def get(self, report_id: int) -> Report | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT {', '.join(COLUMNS)} FROM reports WHERE id = ?", (report_id,)
            ).fetchone()
        return Report(**dict(row)) if row else None

    def list(self) -> list[Report]:
        with closing(self._connect()) as conn:
            rows = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM reports ORDER BY id DESC").fetchall()
        return [Report(**dict(row)) for row in rows]

    # --- briefings ------------------------------------------------------------

    def save_briefing(self, report_id: int, *, text: str, rounds: int, reviewer_accepted: bool) -> Briefing:
        """Save or replace a draft briefing. There is deliberately no status argument:
        a saved briefing is always pending, and an approved one cannot be replaced."""
        with closing(self._connect()) as conn, conn:
            _upsert_briefing(conn, report_id, text, rounds, reviewer_accepted)
        return self.get_briefing(report_id)

    def get_briefing(self, report_id: int) -> Briefing | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT {', '.join(BRIEFING_COLUMNS)} FROM briefings WHERE report_id = ?", (report_id,)
            ).fetchone()
        return Briefing(**dict(row)) if row else None

    def approve(self, report_id: int, *, approved_by: str) -> Briefing:
        """The only way a briefing becomes approved. Called from the approve endpoint."""
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE briefings SET status = 'approved', approved_by = ?, approved_at = ?"
                " WHERE report_id = ? AND status = 'pending'",
                (approved_by, datetime.now(UTC).isoformat(), report_id),
            )
        if cur.rowcount == 1:
            return self.get_briefing(report_id)
        if self.get_briefing(report_id) is None:
            raise NoBriefing(report_id)
        raise AlreadyApproved(report_id)

    # --- analysis and trace ---------------------------------------------------

    def start_analysis(self, report_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO analyses (report_id, status, updated_at) VALUES (?, 'processing', ?)"
                " ON CONFLICT (report_id) DO UPDATE SET status = 'processing', error = NULL,"
                "   updated_at = excluded.updated_at",
                (report_id, _now()),
            )

    def fail_analysis(self, report_id: int, error: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE analyses SET status = 'failed', error = ?, updated_at = ? WHERE report_id = ?",
                (error, _now(), report_id),
            )

    def save_analysis(self, report_id: int, analysis: "Analysis") -> None:
        """Save the analysis, its trace, and its (pending) briefing in one transaction."""
        a = analysis
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE analyses SET status = 'ready', error = NULL, subsystem = ?, severity = ?,"
                " effective_severity = ?, verdict = ?, violations = ?, brief_by_minutes = ?,"
                " flags = ?, needs_review = ?, review_reasons = ?, total_cost_usd = ?,"
                " cost_complete = ?, updated_at = ? WHERE report_id = ?",
                (
                    a.subsystem,
                    a.severity,
                    a.effective_severity,
                    a.limits.verdict,
                    json.dumps([asdict(v) for v in a.limits.violations]),
                    a.brief_by_minutes,
                    json.dumps(a.flags),
                    int(a.needs_review),
                    json.dumps(a.review_reasons),
                    str(a.total_cost_usd),
                    int(a.cost_complete),
                    _now(),
                    report_id,
                ),
            )
            conn.execute("DELETE FROM trace_steps WHERE report_id = ?", (report_id,))
            conn.executemany(
                "INSERT INTO trace_steps (report_id, seq, name, kind, model, input_tokens,"
                " output_tokens, cost_usd, summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        report_id, seq, s.name, s.kind, s.model, s.input_tokens, s.output_tokens,
                        None if s.cost_usd is None else str(s.cost_usd), s.summary,
                    )
                    for seq, s in enumerate(a.steps, start=1)
                ],
            )
            _upsert_briefing(
                conn, report_id, a.briefing.text, len(a.briefing.rounds), a.briefing.reviewer_accepted
            )

    def get_analysis(self, report_id: int) -> AnalysisOut | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM analyses WHERE report_id = ?", (report_id,)).fetchone()
            if row is None:
                return None
            steps = conn.execute(
                "SELECT seq, name, kind, model, input_tokens, output_tokens, cost_usd, summary"
                " FROM trace_steps WHERE report_id = ? ORDER BY seq",
                (report_id,),
            ).fetchall()
        data = dict(row)
        for key in ("violations", "flags", "review_reasons"):
            data[key] = json.loads(data[key])
        for key in ("needs_review", "cost_complete"):
            data[key] = None if data[key] is None else bool(data[key])
        return AnalysisOut(**data, trace=[dict(s) for s in steps])


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _upsert_briefing(conn: sqlite3.Connection, report_id: int, text: str, rounds: int, reviewer_accepted: bool) -> None:
    cur = conn.execute(
        "INSERT INTO briefings (report_id, text, rounds, reviewer_accepted) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (report_id) DO UPDATE SET"
        "   text = excluded.text, rounds = excluded.rounds,"
        "   reviewer_accepted = excluded.reviewer_accepted"
        " WHERE briefings.status = 'pending'",
        (report_id, text, rounds, int(reviewer_accepted)),
    )
    if cur.rowcount == 0:
        raise AlreadyApproved(report_id)
