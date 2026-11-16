"""Filing reports: every field is accepted, bad input is rejected with a clear message."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

VALID = {
    "name": "R. Okafor",
    "station": "PROP",
    "wind_knots": 12.5,
    "temp_c": 9,
    "fuel_pct": 99.2,
    "note": "LOX vent valve cycled twice without a command.",
}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "reports.db")) as c:
        yield c


def file(client, **changes):
    body = {**VALID, **changes}
    return client.post("/reports", json={k: v for k, v in body.items() if v is not ...})


def field_errors(response) -> dict[str, str]:
    assert response.status_code == 422, response.text
    return {e["field"]: e["message"] for e in response.json()["errors"]}


# --- accepted ---------------------------------------------------------------


def test_valid_report_is_saved_with_every_field(client):
    r = file(client)
    assert r.status_code == 201
    saved = r.json()
    assert isinstance(saved["id"], int)
    assert saved["created_at"]
    for key, value in VALID.items():
        assert saved[key] == value


def test_saved_report_can_be_fetched_and_listed(client):
    saved = file(client).json()
    assert client.get(f"/reports/{saved['id']}").json() == saved
    assert client.get("/reports").json() == [saved]


def test_reports_are_listed_newest_first(client):
    first = file(client, name="First").json()
    second = file(client, name="Second").json()
    assert [r["id"] for r in client.get("/reports").json()] == [second["id"], first["id"]]


def test_text_fields_are_trimmed(client):
    saved = file(client, name="  R. Okafor ", station=" PROP\n").json()
    assert saved["name"] == "R. Okafor"
    assert saved["station"] == "PROP"


def test_readings_outside_launch_limits_are_still_filed(client):
    # Filing records what the engineer saw; judging go/no_go is the limit check's job.
    r = file(client, wind_knots=40, temp_c=-5, fuel_pct=100.5)
    assert r.status_code == 201


def test_whole_number_readings_are_accepted(client):
    assert file(client, wind_knots=0, temp_c=-10, fuel_pct=100).status_code == 201


# --- rejected -----------------------------------------------------------------


@pytest.mark.parametrize("missing", list(VALID))
def test_missing_field_is_rejected(client, missing):
    assert field_errors(file(client, **{missing: ...})) == {missing: "is required"}


@pytest.mark.parametrize("reading", ["wind_knots", "temp_c", "fuel_pct"])
@pytest.mark.parametrize("bad", ["windy", "12", None, True])
def test_reading_that_is_not_a_number_is_rejected(client, reading, bad):
    assert field_errors(file(client, **{reading: bad})) == {reading: "must be a number"}


@pytest.mark.parametrize(
    "reading, value, message",
    [
        ("wind_knots", -0.1, "must be at least 0"),
        ("fuel_pct", -1, "must be at least 0"),
        ("temp_c", -273.2, "must be at least -273.15"),
    ],
)
def test_physically_impossible_reading_is_rejected(client, reading, value, message):
    assert field_errors(file(client, **{reading: value})) == {reading: message}


@pytest.mark.parametrize("field", ["name", "station", "note"])
@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_blank_text_is_rejected(client, field, blank):
    assert field_errors(file(client, **{field: blank})) == {field: "must not be blank"}


def test_overlong_note_is_rejected(client):
    errors = field_errors(file(client, note="x" * 4001))
    assert errors == {"note": "must be at most 4000 characters"}


def test_unknown_field_is_rejected(client):
    # A client must not be able to slip in a verdict or status of its own.
    errors = field_errors(file(client, verdict="go"))
    assert errors == {"verdict": "is not an accepted field"}


def test_every_bad_field_is_reported_at_once(client):
    errors = field_errors(file(client, name="", wind_knots="calm", note=...))
    assert errors == {
        "name": "must not be blank",
        "wind_knots": "must be a number",
        "note": "is required",
    }


def test_error_response_has_one_readable_message(client):
    body = file(client, name="", wind_knots="calm").json()
    assert body["message"] == "Report not filed: name must not be blank; wind_knots must be a number"


def test_body_that_is_not_json_is_rejected(client):
    r = client.post("/reports", content="name=R", headers={"content-type": "application/json"})
    assert field_errors(r) == {"body": "is not valid JSON"}


def test_rejected_report_is_not_saved(client):
    file(client, wind_knots="calm")
    assert client.get("/reports").json() == []


def test_unknown_report_is_404(client):
    r = client.get("/reports/999")
    assert r.status_code == 404
    assert r.json() == {"message": "Report 999 not found"}
