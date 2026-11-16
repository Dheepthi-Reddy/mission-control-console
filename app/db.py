"""Reports saved in a SQLite file, so they survive a restart.

Each call opens its own connection: FastAPI runs sync routes on a thread pool,
and a short-lived connection per call avoids sharing one across threads.
"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from app.domain.briefing import Briefing
from app.domain.report import Report, ReportIn

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
