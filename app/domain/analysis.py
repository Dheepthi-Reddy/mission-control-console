"""What the console reads back for a report: the analysis, its trace, and its cost."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

AnalysisStatus = Literal["processing", "ready", "failed"]


class TraceStepOut(BaseModel):
    seq: int
    name: str
    kind: Literal["model", "code"]
    model: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None
    summary: str


class ViolationOut(BaseModel):
    reading: str
    value: float
    limit: str


class ReportSummary(BaseModel):
    """One row of the console's report list. Analysis fields are empty until it is ready."""

    id: int
    created_at: datetime
    name: str
    station: str
    analysis_status: AnalysisStatus | None
    verdict: Literal["go", "no_go"] | None
    subsystem: str | None
    effective_severity: str | None
    brief_by_minutes: int | None
    needs_review: bool | None
    total_cost_usd: Decimal | None
    briefing_status: Literal["pending", "approved"] | None


class AnalysisOut(BaseModel):
    report_id: int
    status: AnalysisStatus
    error: str | None = None
    subsystem: str | None = None
    severity: str | None = None
    effective_severity: str | None = None
    verdict: Literal["go", "no_go"] | None = None
    violations: list[ViolationOut] = []
    brief_by_minutes: int | None = None
    flags: list[str] = []
    needs_review: bool | None = None
    review_reasons: list[str] = []
    total_cost_usd: Decimal | None = None
    cost_complete: bool | None = None
    updated_at: datetime
    trace: list[TraceStepOut] = []
