"""Reports are saved to disk and are still there after the app restarts."""

from fastapi.testclient import TestClient

from app.main import create_app

REPORT = {
    "name": "J. Alvarez",
    "station": "COMMS",
    "wind_knots": 18,
    "temp_c": 6.5,
    "fuel_pct": 98,
    "note": "S-band telemetry dropped for 4 seconds, then recovered.",
}


def test_reports_survive_a_restart(tmp_path):
    db = tmp_path / "reports.db"

    # First run: file a report, then shut the app down.
    with TestClient(create_app(db)) as before:
        saved = before.post("/reports", json=REPORT).json()

    # Second run: a brand-new app on the same database file.
    with TestClient(create_app(db)) as after:
        assert after.get(f"/reports/{saved['id']}").json() == saved
        assert after.get("/reports").json() == [saved]


def test_ids_keep_counting_after_a_restart(tmp_path):
    db = tmp_path / "reports.db"
    with TestClient(create_app(db)) as before:
        first = before.post("/reports", json=REPORT).json()
    with TestClient(create_app(db)) as after:
        second = after.post("/reports", json=REPORT).json()
    assert second["id"] > first["id"]


def test_database_folder_is_created_if_missing(tmp_path):
    db = tmp_path / "not" / "yet" / "there" / "reports.db"
    with TestClient(create_app(db)) as client:
        assert client.post("/reports", json=REPORT).status_code == 201
    assert db.exists()
