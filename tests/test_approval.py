"""Only a person can approve a pending briefing, through the approve endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.db import AlreadyApproved, ReportStore
from app.domain.report import ReportIn
from app.main import create_app

REPORT = ReportIn(
    name="R. Okafor",
    station="PROP",
    wind_knots=12,
    temp_c=9,
    fuel_pct=99,
    note="LOX vent valve cycled twice at T-85 without a command.",
)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "reports.db"


@pytest.fixture
def report_id(db):
    store = ReportStore(db)
    report = store.add(REPORT)
    store.save_briefing(report.id, text="GO. Vent valve cycled; pressure nominal.", rounds=1, reviewer_accepted=True)
    return report.id


@pytest.fixture
def client(db, report_id):
    with TestClient(create_app(db)) as c:
        yield c


def approve(client, report_id, **body):
    return client.post(f"/reports/{report_id}/approve", json=body)


# --- the store ----------------------------------------------------------------


def test_saved_briefing_is_always_pending(db, report_id):
    briefing = ReportStore(db).get_briefing(report_id)
    assert briefing.status == "pending"
    assert briefing.approved_by is None and briefing.approved_at is None
    assert briefing.reviewer_accepted is True


def test_saving_has_no_way_to_set_a_status(db, report_id):
    with pytest.raises(TypeError):
        ReportStore(db).save_briefing(report_id, text="x", rounds=1, reviewer_accepted=True, status="approved")


def test_redrafting_cannot_overwrite_an_approved_briefing(db, report_id):
    store = ReportStore(db)
    store.approve(report_id, approved_by="Flight Director")
    with pytest.raises(AlreadyApproved):
        store.save_briefing(report_id, text="new text", rounds=1, reviewer_accepted=True)
    assert store.get_briefing(report_id).text.startswith("GO.")


# --- the endpoint -------------------------------------------------------------


def test_briefing_starts_pending(client, report_id):
    body = client.get(f"/reports/{report_id}/briefing").json()
    assert body["status"] == "pending"
    assert body["text"] == "GO. Vent valve cycled; pressure nominal."


def test_person_can_approve_a_pending_briefing(client, report_id):
    r = approve(client, report_id, approved_by="  K. Ito ")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["approved_by"] == "K. Ito"
    assert body["approved_at"]
    assert client.get(f"/reports/{report_id}/briefing").json() == body


def test_approving_twice_is_rejected(client, report_id):
    approve(client, report_id, approved_by="K. Ito")
    r = approve(client, report_id, approved_by="Someone Else")
    assert r.status_code == 409
    assert r.json() == {"message": f"Briefing for report {report_id} is already approved"}
    assert client.get(f"/reports/{report_id}/briefing").json()["approved_by"] == "K. Ito"


@pytest.mark.parametrize(
    "body, message",
    [
        ({}, "approved_by is required"),
        ({"approved_by": "  "}, "approved_by must not be blank"),
        ({"approved_by": "K. Ito", "status": "approved"}, "status is not an accepted field"),
    ],
)
def test_approval_needs_a_named_person(client, report_id, body, message):
    r = approve(client, report_id, **body)
    assert r.status_code == 422
    assert r.json()["message"] == f"Briefing not approved: {message}"
    assert client.get(f"/reports/{report_id}/briefing").json()["status"] == "pending"


def test_report_without_a_briefing_cannot_be_approved(client, db):
    # Added straight to the store, so no pipeline has drafted a briefing for it.
    report = ReportStore(db).add(REPORT)
    r = approve(client, report.id, approved_by="K. Ito")
    assert r.status_code == 404
    assert r.json() == {"message": f"No briefing for report {report.id} yet"}


def test_unknown_report_has_no_briefing(client):
    assert client.get("/reports/999/briefing").status_code == 404
    assert approve(client, 999, approved_by="K. Ito").status_code == 404


def test_approval_survives_a_restart(db, report_id):
    with TestClient(create_app(db)) as before:
        approved = approve(before, report_id, approved_by="K. Ito").json()
    with TestClient(create_app(db)) as after:
        assert after.get(f"/reports/{report_id}/briefing").json() == approved
