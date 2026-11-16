"""What an engineer files: who, where, three readings, and a free-text note.

Validation here only rejects input that cannot be a real report (missing,
blank, not a number, physically impossible). Readings outside the launch
limits are still valid reports; check_limits judges those.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
NoteText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]

# strict: "12" and true are rejected rather than quietly turned into numbers.
# allow_inf_nan=False: NaN would slip past every limit comparison.
Reading = Annotated[float, Field(strict=True, allow_inf_nan=False)]

ABSOLUTE_ZERO_C = -273.15


class ReportIn(BaseModel):
    # forbid: a client cannot slip in its own verdict, status, or id.
    model_config = ConfigDict(extra="forbid")

    name: ShortText
    station: ShortText
    wind_knots: Annotated[Reading, Field(ge=0)]
    temp_c: Annotated[Reading, Field(ge=ABSOLUTE_ZERO_C)]
    fuel_pct: Annotated[Reading, Field(ge=0)]
    note: NoteText


class Report(ReportIn):
    id: int
    created_at: datetime
