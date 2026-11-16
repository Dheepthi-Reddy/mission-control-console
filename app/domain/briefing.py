"""A saved briefing and the request a person sends to approve it."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.report import ShortText

BriefingStatus = Literal["pending", "approved"]


class Briefing(BaseModel):
    report_id: int
    text: str
    status: BriefingStatus
    rounds: int
    reviewer_accepted: bool
    approved_by: str | None
    approved_at: datetime | None


class ApprovalIn(BaseModel):
    # forbid: the caller names who approves; it cannot send a status or anything else.
    model_config = ConfigDict(extra="forbid")

    approved_by: ShortText
