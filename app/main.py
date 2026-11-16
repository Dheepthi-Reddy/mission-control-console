import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import choose_llm
from app.db import AlreadyApproved, NoBriefing, ReportStore
from app.domain.analysis import AnalysisOut
from app.domain.briefing import ApprovalIn, Briefing
from app.domain.report import Report, ReportIn
from app.llm.client import LLMClient
from app.pipeline.runner import analyse

DEFAULT_DB_PATH = "data/mission_control.db"

log = logging.getLogger("mission_control")


async def run_pipeline(llm: LLMClient, store: ReportStore, report: Report) -> None:
    """Analyse a filed report. A crash marks the analysis failed; the report itself stays saved."""
    try:
        store.save_analysis(report.id, await analyse(llm, report))
    except Exception as exc:
        log.exception("pipeline failed for report %s", report.id)
        store.fail_analysis(report.id, f"{type(exc).__name__}: {exc}")


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


def create_app(db_path: str | Path | None = None, llm: LLMClient | None = None) -> FastAPI:
    """Build the app. Settings are read on startup, so importing this module touches no files.

    Pass `llm` to choose the model client (tests pass FakeLLM); otherwise it is
    chosen from the environment and a git-ignored .env file (see app/config.py).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        load_dotenv(override=False)  # real environment variables win over .env
        app.state.store = ReportStore(db_path or os.environ.get("MISSION_CONTROL_DB", DEFAULT_DB_PATH))
        if llm is None:
            app.state.llm, app.state.llm_label = choose_llm(os.environ)
        else:
            app.state.llm, app.state.llm_label = llm, "injected"
        log.warning("model client: %s", app.state.llm_label)
        yield

    app = FastAPI(title="Mission Control: Go/No-Go Launch Console", lifespan=lifespan)
    app.add_exception_handler(RequestValidationError, _validation_error)

    @app.get("/health")
    def health(request: Request) -> dict[str, str]:
        return {"status": "ok", "llm": request.app.state.llm_label}

    @app.post("/reports", status_code=201)
    def file_report(report: ReportIn, request: Request, background: BackgroundTasks) -> Report:
        store: ReportStore = request.app.state.store
        saved = store.add(report)
        store.start_analysis(saved.id)
        background.add_task(run_pipeline, request.app.state.llm, store, saved)
        return saved

    @app.get("/reports/{report_id}/analysis", response_model=AnalysisOut)
    def get_analysis(report_id: int, request: Request):
        analysis = request.app.state.store.get_analysis(report_id)
        if analysis is None:
            return JSONResponse(status_code=404, content={"message": f"No analysis for report {report_id}"})
        return analysis

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
