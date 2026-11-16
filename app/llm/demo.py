"""Demo LLMClient for running the app with no API key.

Canned, clearly labelled replies so every pipeline step runs and shows in the
console. It is not a model: sorting always says "other / medium" and every
check comes back clear (the plain-code hidden-instruction backstop still runs).
"""

from app.llm.client import LLMResponse

DEMO_NOTICE = "Demo mode: no API key is set, so these are canned replies, not Claude."

_REPLIES = {
    "classify": '{"subsystem": "other", "severity": "medium"}',
    "check_injection": '{"flagged": false, "reason": "demo mode: not checked by a model"}',
    "check_missing_details": '{"flagged": false, "reason": "demo mode: not checked by a model"}',
    "check_panic": '{"flagged": false, "reason": "demo mode: not checked by a model"}',
    "review": '{"accepted": true, "feedback": ""}',
}


def _tokens(text: str) -> int:
    return max(1, len(text.split()))


class DemoLLM:
    async def complete(self, *, purpose: str, system: str, prompt: str) -> LLMResponse:
        if purpose == "draft":
            facts = prompt.split("Station:")[0].strip()
            text = f"{DEMO_NOTICE}\n{facts}"
        else:
            text = _REPLIES[purpose]
        return LLMResponse(
            text=text,
            input_tokens=_tokens(system + " " + prompt),
            output_tokens=_tokens(text),
            model="demo",
        )
