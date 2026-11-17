"""The Flight Director's console: served by the app, sends every field, shows the trace safely."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm.fake import FakeLLM
from app.main import create_app

STATIC = Path(__file__).parent.parent / "app" / "static"
FIELDS = ["name", "station", "wind_knots", "temp_c", "fuel_pct", "note"]
REPORT = {
    "name": "R. Okafor",
    "station": "PROP",
    "wind_knots": 31,
    "temp_c": 9,
    "fuel_pct": 99,
    "note": "LOX vent valve cycled twice at T-85 without a command.",
}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "reports.db")) as c:
        yield c


def js() -> str:
    return (STATIC / "app.js").read_text()


def html() -> str:
    return (STATIC / "index.html").read_text()


# --- serving ------------------------------------------------------------------


def test_console_is_served_at_the_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Mission Control" in r.text


@pytest.mark.parametrize("asset", ["app.js", "styles.css"])
def test_console_assets_are_served(client, asset):
    assert client.get(f"/static/{asset}").status_code == 200


# --- the filing form ----------------------------------------------------------


@pytest.mark.parametrize("field", FIELDS)
def test_form_has_an_input_for_every_field(field):
    assert re.search(rf'name="{field}"', html()), f"form has no input named {field}"


def test_form_leaves_validation_to_the_server():
    # novalidate: the browser never blocks a submit, so the server's clear messages always show.
    assert re.search(r'<form id="report-form"[^>]*\bnovalidate\b', html())


@pytest.mark.parametrize("field", FIELDS)
def test_script_sends_every_field(field):
    assert f'"{field}"' in js()


def test_script_posts_reports_and_shows_field_errors():
    source = js()
    assert 'api("/reports", { method: "POST"' in source
    assert "body.errors" in source  # the per-field messages from a 422


# --- the detail view ----------------------------------------------------------


@pytest.mark.parametrize(
    "shown",
    ["verdict", "violations", "brief_by_minutes", "review_reasons", "total_cost_usd", "/briefing"],
)
def test_detail_view_shows_the_flight_directors_facts(shown):
    assert shown in js()


def test_detail_view_has_one_card_per_trace_step_with_its_tokens():
    source = js()
    assert "analysis.trace.map(" in source
    for field in ("input_tokens", "output_tokens", "cost_usd", "model"):
        assert f"step.{field}" in source


def test_only_a_person_can_approve_from_the_console():
    source = js()
    assert "/approve" in source
    assert "approved_by" in source
    # The console only calls approve from the approve form's submit handler.
    assert source.count("/approve") == 1


def test_script_never_inserts_untrusted_text_as_html():
    # The note is typed by an engineer and may contain markup; every value goes in as text.
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in js(), f"app.js uses {sink}"


# --- the list endpoint ----------------------------------------------------------


def test_console_list_summarises_each_report(tmp_path):
    with TestClient(create_app(tmp_path / "reports.db", llm=FakeLLM({
        "classify": '{"subsystem": "propulsion", "severity": "low"}',
        "check_injection": '{"flagged": false, "reason": ""}',
        "check_missing_details": '{"flagged": false, "reason": ""}',
        "check_panic": '{"flagged": false, "reason": ""}',
        "draft": "NO_GO briefing.",
        "review": '{"accepted": true, "feedback": ""}',
    }, model="claude-opus-5-5"))) as client:
        saved = client.post("/reports", json=REPORT).json()
        [row] = client.get("/console/reports").json()

    assert row["id"] == saved["id"]
    assert (row["name"], row["station"]) == ("R. Okafor", "PROP")
    assert row["analysis_status"] == "ready"
    assert row["verdict"] == "no_go"
    assert row["effective_severity"] == "high"
    assert row["brief_by_minutes"] == 5
    assert row["needs_review"] is False
    assert row["briefing_status"] == "pending"
    assert float(row["total_cost_usd"]) > 0


def test_console_list_is_newest_first_and_shows_reports_still_processing(client, tmp_path):
    from app.db import ReportStore
    from app.domain.report import ReportIn

    first = client.post("/reports", json=REPORT).json()
    store = ReportStore(tmp_path / "reports.db")
    waiting = store.add(ReportIn(**REPORT))
    store.start_analysis(waiting.id)

    rows = client.get("/console/reports").json()
    assert [r["id"] for r in rows] == [waiting.id, first["id"]]
    assert rows[0]["analysis_status"] == "processing"
    assert rows[0]["verdict"] is None
    assert rows[0]["briefing_status"] is None


def test_console_list_is_empty_with_no_reports(client):
    assert client.get("/console/reports").json() == []
