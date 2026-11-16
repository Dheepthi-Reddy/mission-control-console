"""Reports saved in a SQLite file, so they survive a restart.

Each call opens its own connection: FastAPI runs sync routes on a thread pool,
and a short-lived connection per call avoids sharing one across threads.
"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

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
)
"""

COLUMNS = ("id", "created_at", "name", "station", "wind_knots", "temp_c", "fuel_pct", "note")


class ReportStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
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
