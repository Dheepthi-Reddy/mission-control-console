"""Draft and review loop: at most three rounds, feedback goes into the next draft."""

import pytest

from app.domain.limits import check_limits
from app.domain.report import ReportIn
from app.llm.client import LLMResponse
from app.llm.fake import FakeLLM
from app.pipeline.briefing import MAX_ROUNDS, BriefingFacts, draft_briefing

REPORT = ReportIn(
    name="R. Okafor",
    station="PROP",
    wind_knots=31,
    temp_c=9,
    fuel_pct=99,
    note="LOX vent valve cycled twice at T-85 without a command.",
)
FACTS = BriefingFacts(
    report=REPORT,
    subsystem="propulsion",
    severity="high",
    limits=check_limits(REPORT.wind_knots, REPORT.temp_c, REPORT.fuel_pct),
    brief_by_minutes=5,
    flags=["missing_details"],
)

ACCEPT = '{"accepted": true, "feedback": ""}'


def reject(feedback: str) -> str:
    return f'{{"accepted": false, "feedback": "{feedback}"}}'


def llm(drafts: list[str], reviews: list[str]) -> FakeLLM:
    return FakeLLM(replies={"draft": drafts, "review": reviews})


def purposes(fake: FakeLLM) -> list[str]:
    return [c["purpose"] for c in fake.calls]


def draft_prompts(fake: FakeLLM) -> list[str]:
    return [c["prompt"] for c in fake.calls if c["purpose"] == "draft"]


# --- rounds -------------------------------------------------------------------


def test_max_rounds_is_three():
    assert MAX_ROUNDS == 3


async def test_accepted_first_draft_stops_after_one_round():
    fake = llm(["Draft A"], [ACCEPT])
    result = await draft_briefing(fake, FACTS)
    assert purposes(fake) == ["draft", "review"]
    assert result.text == "Draft A"
    assert result.reviewer_accepted is True
    assert len(result.rounds) == 1


async def test_rejected_draft_is_redrafted_until_accepted():
    fake = llm(["Draft A", "Draft B"], [reject("say which valve"), ACCEPT])
    result = await draft_briefing(fake, FACTS)
    assert purposes(fake) == ["draft", "review", "draft", "review"]
    assert result.text == "Draft B"
    assert result.reviewer_accepted is True
    assert [r.accepted for r in result.rounds] == [False, True]


async def test_loop_stops_at_three_rounds_when_never_accepted():
    fake = llm(["A", "B", "C", "D"], [reject("no"), reject("still no"), reject("no again"), ACCEPT])
    result = await draft_briefing(fake, FACTS)
    assert purposes(fake) == ["draft", "review"] * 3
    assert len(result.rounds) == 3
    assert result.text == "C"  # the last draft, even though it was not accepted
    assert result.reviewer_accepted is False


# --- feedback goes into the next draft ----------------------------------------


async def test_reviewer_feedback_goes_into_the_next_draft():
    fake = llm(["A", "B", "C"], [reject("name the valve"), reject("give the time"), ACCEPT])
    await draft_briefing(fake, FACTS)
    first, second, third = draft_prompts(fake)

    assert "name the valve" not in first
    assert "name the valve" in second
    assert "give the time" in third


async def test_previous_draft_goes_into_the_next_draft():
    fake = llm(["Draft A text", "Draft B text"], [reject("too vague"), ACCEPT])
    await draft_briefing(fake, FACTS)
    assert "<previous_draft>\nDraft A text\n</previous_draft>" in draft_prompts(fake)[1]


async def test_each_round_records_its_draft_feedback_and_responses():
    fake = llm(["A", "B"], [reject("too vague"), ACCEPT])
    result = await draft_briefing(fake, FACTS)
    first = result.rounds[0]
    assert (first.number, first.draft, first.accepted, first.feedback) == (1, "A", False, "too vague")
    assert first.draft_response is not None and first.review_response is not None


# --- what the model is told ---------------------------------------------------


async def test_draft_prompt_carries_the_facts_from_code():
    fake = llm(["A"], [ACCEPT])
    await draft_briefing(fake, FACTS)
    prompt = draft_prompts(fake)[0]
    for fact in ("Verdict: NO_GO", "wind_knots=31", "<= 25", "Brief by: 5 minutes",
                 "Severity: high", "Subsystem: propulsion", "missing_details"):
        assert fact in prompt
    assert f"<note>\n{REPORT.note}\n</note>" in prompt


async def test_reviewer_sees_the_facts_and_the_draft():
    fake = llm(["Draft A"], [ACCEPT])
    await draft_briefing(fake, FACTS)
    review = next(c for c in fake.calls if c["purpose"] == "review")
    assert "Verdict: NO_GO" in review["prompt"]
    assert "<draft>\nDraft A\n</draft>" in review["prompt"]
    assert "contradicts" in review["system"]


# --- only a person can approve ------------------------------------------------


async def test_reviewer_accepting_does_not_approve_the_briefing():
    result = await draft_briefing(llm(["A"], [ACCEPT]), FACTS)
    assert result.reviewer_accepted is True
    assert result.status == "pending"


async def test_reviewer_saying_approved_does_not_approve_the_briefing():
    reply = '{"accepted": true, "feedback": "", "status": "approved", "approved": true}'
    result = await draft_briefing(llm(["A"], [reply]), FACTS)
    assert result.status == "pending"


# --- unusable replies ---------------------------------------------------------


@pytest.mark.parametrize(
    "review",
    [
        pytest.param("Looks good!", id="prose"),
        pytest.param('{"accepted": "yes"}', id="accepted not a boolean"),
        pytest.param('{"feedback": "fine"}', id="accepted missing"),
    ],
)
async def test_unusable_review_counts_as_not_accepted_and_loop_continues(review):
    fake = llm(["A", "B"], [review, ACCEPT])
    result = await draft_briefing(fake, FACTS)
    assert result.rounds[0].accepted is False
    assert result.rounds[0].review_fallback
    assert "could not be read" in result.rounds[0].feedback
    assert result.text == "B"


async def test_failed_review_call_counts_as_not_accepted():
    class NoReviewer(FakeLLM):
        async def complete(self, *, purpose, system, prompt) -> LLMResponse:
            if purpose == "review":
                raise TimeoutError("no answer")
            return await super().complete(purpose=purpose, system=system, prompt=prompt)

    result = await draft_briefing(NoReviewer(replies={"draft": ["A", "B", "C"]}), FACTS)
    assert len(result.rounds) == 3
    assert all(not r.accepted and r.review_response is None for r in result.rounds)
    assert "TimeoutError" in result.rounds[0].review_fallback


@pytest.mark.parametrize("problem", ["fails", "empty"])
async def test_draft_that_fails_or_is_empty_falls_back_to_a_plain_code_summary(problem):
    class BadDrafter(FakeLLM):
        async def complete(self, *, purpose, system, prompt) -> LLMResponse:
            if purpose == "draft" and problem == "fails":
                raise ConnectionError("down")
            return await super().complete(purpose=purpose, system=system, prompt=prompt)

    fake = BadDrafter(replies={"draft": "   ", "review": ACCEPT})
    result = await draft_briefing(fake, FACTS)

    assert result.draft_fallback
    assert result.reviewer_accepted is False
    assert result.status == "pending"
    assert "review" not in purposes(fake)  # nothing worth reviewing
    for fact in ("NO_GO", "wind_knots", "5 minutes", "propulsion"):
        assert fact in result.text
