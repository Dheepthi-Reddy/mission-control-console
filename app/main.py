import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.db import AlreadyApproved, NoBriefing, ReportStore
from app.domain.briefing import ApprovalIn, Briefing
from app.domain.report import Report, ReportIn

DEFAULT_DB_PATH = "data/mission_control.db"


def _friendly(error: dict) -> str:
    """Turn one Pydantic error into a short message an engineer can act on."""
    kind, ctx = error["type"], error.get("ctx", {})
    match kind:
        case "missing":
            return "is required"
        case "float_type" | "float_parsing" | "finite_number":
            return "must be a number"
        case "string_type":
            return "must be text"
        case "string_too_short":
            return "must not be blank"
        case "string_too_long":
            return f"must be at most {ctx['max_length']} characters"
        case "greater_than_equal":
            return f"must be at least {ctx['ge']:g}"
        case "extra_forbidden":
            return "is not an accepted field"
        case "json_invalid":
            return "is not valid JSON"
        case "model_attributes_type" | "dict_type":
            return "must be a JSON object"
        case _:
            return error["msg"]


def _field(error: dict) -> str:
    # loc is ("body",) for the whole body, ("body", "wind_knots") for a field,
    # or ("body", <char offset>) for a JSON syntax error.
    loc = [part for part in error["loc"][1:] if isinstance(part, str)]
    return ".".join(loc) or "body"


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"field": _field(e), "message": _friendly(e)} for e in exc.errors()]
    summary = "; ".join(f"{e['field']} {e['message']}" for e in errors)
    action = "Briefing not approved" if request.url.path.endswith("/approve") else "Report not filed"
    return JSONResponse(
        status_code=422,
        content={"message": f"{action}: {summary}", "errors": errors},
    )


def create_app(db_path: str | Path | None = None) -> FastAPI:
    """Build the app. The database opens on startup, so importing this module touches no files."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.store = ReportStore(db_path or os.environ.get("MISSION_CONTROL_DB", DEFAULT_DB_PATH))
        yield

    app = FastAPI(title="Mission Control: Go/No-Go Launch Console", lifespan=lifespan)
    app.add_exception_handler(RequestValidationError, _validation_error)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/reports", status_code=201)
    def file_report(report: ReportIn, request: Request) -> Report:
        return request.app.state.store.add(report)

    @app.get("/reports")
    def list_reports(request: Request) -> list[Report]:
        return request.app.state.store.list()

    @app.get("/reports/{report_id}", response_model=Report)
    def get_report(report_id: int, request: Request):
        report = request.app.state.store.get(report_id)
        if report is None:
            return JSONResponse(status_code=404, content={"message": f"Report {report_id} not found"})
        return report

    @app.get("/reports/{report_id}/briefing", response_model=Briefing)
    def get_briefing(report_id: int, request: Request):
        briefing = request.app.state.store.get_briefing(report_id)
        if briefing is None:
            return JSONResponse(status_code=404, content={"message": f"No briefing for report {report_id} yet"})
        return briefing

    # The only route that approves. The pipeline never calls it; a person does, by name.
    @app.post("/reports/{report_id}/approve", response_model=Briefing)
    def approve_briefing(report_id: int, approval: ApprovalIn, request: Request):
        try:
            return request.app.state.store.approve(report_id, approved_by=approval.approved_by)
        except NoBriefing:
            return JSONResponse(status_code=404, content={"message": f"No briefing for report {report_id} yet"})
        except AlreadyApproved:
            return JSONResponse(
                status_code=409,
                content={"message": f"Briefing for report {report_id} is already approved"},
            )

    return app


app = create_app()
