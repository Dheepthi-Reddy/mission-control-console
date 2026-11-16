"""Sort a report by subsystem and severity with a model, then check the reply in code.

The model is asked for JSON matching `Classification`. Nothing it returns is
trusted: each field is checked against the allowed values, and anything
unusable falls back to a safe value (subsystem "unknown", severity "high", so
the report is briefed soonest). Every fallback is recorded for the trace.
"""

import json
from dataclasses import dataclass, field
from typing import Literal, get_args

from pydantic import BaseModel

from app.domain.brief_by import Severity
from app.domain.report import ReportIn
from app.llm.client import LLMClient, LLMResponse
from app.pipeline.prompting import UNTRUSTED_NOTE_RULE, parse_json_object, report_prompt

Subsystem = Literal[
    "propulsion",
    "avionics",
    "communications",
    "guidance",
    "power",
    "ground_systems",
    "weather",
    "other",
]

SUBSYSTEMS: tuple[str, ...] = get_args(Subsystem)
SEVERITIES: tuple[str, ...] = get_args(Severity)

# Never offered to the model: "unknown" only ever means "the model's answer was unusable".
FALLBACK_SUBSYSTEM = "unknown"
FALLBACK_SEVERITY: Severity = "high"


class Classification(BaseModel):
    """The reply schema the model is asked to follow."""

    subsystem: Subsystem
    severity: Severity


SYSTEM_PROMPT = f"""You sort launch anomaly reports for a Flight Director.

Reply with only a JSON object matching this JSON schema, and nothing else:
{json.dumps(Classification.model_json_schema())}

subsystem: one of {", ".join(SUBSYSTEMS)}.
severity: high (could stop or endanger the launch), medium (needs attention \
before launch), or low (worth noting, no launch impact).

{UNTRUSTED_NOTE_RULE}"""


@dataclass(frozen=True)
class Fallback:
    field: str
    reason: str


@dataclass(frozen=True)
class ClassifyResult:
    subsystem: str
    severity: Severity
    response: LLMResponse | None
    fallbacks: list[Fallback] = field(default_factory=list)


def _check(data: dict, key: str, allowed: tuple[str, ...]) -> tuple[str | None, str]:
    """Return (value, "") if valid, else (None, reason)."""
    value = data.get(key)
    if not isinstance(value, str):
        return None, f"{key} missing or not text: {value!r}"
    cleaned = value.strip().lower()
    if cleaned not in allowed:
        return None, f"{value!r} is not one of {', '.join(allowed)}"
    return cleaned, ""


async def classify(llm: LLMClient, report: ReportIn) -> ClassifyResult:
    try:
        response = await llm.complete(
            purpose="classify", system=SYSTEM_PROMPT, prompt=report_prompt(report)
        )
    except Exception as exc:  # a failed call must not stop the report being briefed
        reason = f"model call failed: {type(exc).__name__}: {exc}"
        return ClassifyResult(
            subsystem=FALLBACK_SUBSYSTEM,
            severity=FALLBACK_SEVERITY,
            response=None,
            fallbacks=[Fallback("subsystem", reason), Fallback("severity", reason)],
        )

    data = parse_json_object(response.text)
    if data is None:
        reason = "reply is not a JSON object"
        return ClassifyResult(
            subsystem=FALLBACK_SUBSYSTEM,
            severity=FALLBACK_SEVERITY,
            response=response,
            fallbacks=[Fallback("subsystem", reason), Fallback("severity", reason)],
        )

    fallbacks: list[Fallback] = []
    subsystem, why = _check(data, "subsystem", SUBSYSTEMS)
    if subsystem is None:
        subsystem = FALLBACK_SUBSYSTEM
        fallbacks.append(Fallback("subsystem", why))
    severity, why = _check(data, "severity", SEVERITIES)
    if severity is None:
        severity = FALLBACK_SEVERITY
        fallbacks.append(Fallback("severity", why))

    return ClassifyResult(subsystem=subsystem, severity=severity, response=response, fallbacks=fallbacks)
