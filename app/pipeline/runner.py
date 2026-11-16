"""Run every step for one report and record a trace card per step.

Order: sort and the three note checks run at the same time (all model calls),
then the launch limits and brief-by time (plain code), then the draft/review
loop. Each step becomes a TraceStep with its tokens and cost; code steps cost 0.
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.domain.brief_by import Severity, brief_by_minutes, effective_severity
from app.domain.cost import step_cost
from app.domain.limits import LimitCheck, check_limits
from app.domain.report import ReportIn
from app.llm.client import LLMClient, LLMResponse
from app.pipeline import briefing, checks, classify
from app.pipeline.briefing import BriefingFacts, BriefingResult, draft_briefing
from app.pipeline.checks import CHECKS, run_checks
from app.pipeline.classify import ClassifyResult

# Which purposes get a structured-output schema on the real model.
REPLY_SCHEMAS: dict[str, dict] = {
    "classify": classify.REPLY_SCHEMA,
    **{f"check_{name}": checks.REPLY_SCHEMA for name in CHECKS},
    "review": briefing.REVIEW_SCHEMA,
}

CHECK_TITLES = {
    "injection": "Check: hidden instructions",
    "missing_details": "Check: missing details",
    "panic": "Check: panic in tone",
}


@dataclass(frozen=True)
class TraceStep:
    name: str
    kind: Literal["model", "code"]
    model: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None  # None only if the answering model has no price
    summary: str


@dataclass(frozen=True)
class Analysis:
    subsystem: str
    severity: Severity  # what the model said (or its fallback)
    effective_severity: Severity  # after "any violation counts as high"
    limits: LimitCheck
    brief_by_minutes: int
    flags: list[str]
    needs_review: bool
    review_reasons: list[str]
    briefing: BriefingResult
    steps: list[TraceStep]

    @property
    def total_cost_usd(self) -> Decimal:
        return sum((s.cost_usd for s in self.steps if s.cost_usd is not None), start=Decimal("0"))

    @property
    def cost_complete(self) -> bool:
        return all(s.cost_usd is not None for s in self.steps)


def model_step(name: str, response: LLMResponse | None, summary: str) -> TraceStep:
    if response is None:  # the call failed; nothing was billed
        return TraceStep(name, "model", None, 0, 0, Decimal("0"), summary)
    try:
        cost = step_cost(response.model, response.input_tokens, response.output_tokens)
    except ValueError:
        cost, summary = None, f"{summary} (no price for {response.model})"
    return TraceStep(name, "model", response.model, response.input_tokens, response.output_tokens, cost, summary)


def code_step(name: str, summary: str) -> TraceStep:
    return TraceStep(name, "code", None, 0, 0, Decimal("0"), summary)


def _with_fallbacks(summary: str, fallbacks) -> str:
    return summary + "".join(f"; fell back on {f.field}: {f.reason}" for f in fallbacks)


async def analyse(llm: LLMClient, report: ReportIn) -> Analysis:
    sorted_, checked = await asyncio.gather(classify.classify(llm, report), run_checks(llm, report))
    sorted_: ClassifyResult

    # Plain code from here on decides the verdict and brief-by time.
    limits = check_limits(report.wind_knots, report.temp_c, report.fuel_pct)
    has_violation = bool(limits.violations)
    severity = effective_severity(sorted_.severity, has_violation)
    minutes = brief_by_minutes(sorted_.severity, has_violation)
    flags = [name for name, c in checked.checks.items() if c.flagged]

    result = await draft_briefing(
        llm,
        BriefingFacts(
            report=report,
            subsystem=sorted_.subsystem,
            severity=severity,
            limits=limits,
            brief_by_minutes=minutes,
            flags=flags,
        ),
    )

    steps = [
        model_step(
            "Sort: subsystem and severity",
            sorted_.response,
            _with_fallbacks(f"{sorted_.subsystem} / {sorted_.severity}", sorted_.fallbacks),
        ),
        *(
            model_step(
                CHECK_TITLES[name],
                c.response,
                ("flagged" if c.flagged else "clear")
                + (f": {c.reason}" if c.reason else "")
                + (f" (phrases: {', '.join(c.matched_phrases)})" if c.matched_phrases else "")
                + (f" (fallback: {c.fallback_reason})" if c.fallback_reason else ""),
            )
            for name, c in checked.checks.items()
        ),
        code_step(
            "Check launch limits",
            f"{limits.verdict}"
            + "".join(f"; {v.reading}={v.value:g} outside {v.limit}" for v in limits.violations),
        ),
        code_step(
            "Set brief-by time",
            f"{minutes} minutes (severity {severity}"
            + (", raised to high by a limit violation" if severity != sorted_.severity else "")
            + ")",
        ),
    ]
    for r in result.rounds:
        steps.append(model_step(f"Draft briefing, round {r.number}", r.draft_response, f"{len(r.draft.split())} words"))
        steps.append(
            model_step(
                f"Review briefing, round {r.number}",
                r.review_response,
                ("accepted" if r.accepted else f"changes requested: {r.feedback}")
                + (f" (fallback: {r.review_fallback})" if r.review_fallback else ""),
            )
        )
    if result.draft_fallback:
        steps.append(code_step("Briefing from code", f"model draft unavailable: {result.draft_fallback}"))

    review_reasons = list(checked.review_reasons)
    if sorted_.fallbacks:
        review_reasons.append("sorting reply was unusable; used safe fallback")
    if result.draft_fallback:
        review_reasons.append("briefing written from code; model draft unavailable")
    elif not result.reviewer_accepted:
        review_reasons.append(f"reviewer did not accept the briefing after {len(result.rounds)} rounds")

    return Analysis(
        subsystem=sorted_.subsystem,
        severity=sorted_.severity,
        effective_severity=severity,
        limits=limits,
        brief_by_minutes=minutes,
        flags=flags,
        needs_review=bool(review_reasons),
        review_reasons=review_reasons,
        briefing=result,
        steps=steps,
    )
