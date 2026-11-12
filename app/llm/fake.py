"""Offline LLMClient for tests: scripted replies, recorded calls, no network."""

from collections.abc import Mapping, Sequence

from app.llm.client import LLMResponse


def _estimate_tokens(text: str) -> int:
    # Rough but deterministic; at least 1 so cost math is always exercised.
    return max(1, len(text.split()))


class FakeLLM:
    """Returns scripted replies keyed by `purpose`.

    A reply may be a string (returned every time) or a list of strings
    (returned in order, last one repeated) for multi-round steps like draft/review.
    """

    def __init__(self, replies: Mapping[str, str | Sequence[str]]):
        self._replies = dict(replies)
        self._counts: dict[str, int] = {}
        self.calls: list[dict[str, str]] = []

    async def complete(self, *, purpose: str, system: str, prompt: str) -> LLMResponse:
        self.calls.append({"purpose": purpose, "system": system, "prompt": prompt})
        if purpose not in self._replies:
            raise KeyError(f"FakeLLM has no scripted reply for purpose={purpose!r}")

        scripted = self._replies[purpose]
        if isinstance(scripted, str):
            text = scripted
        else:
            i = self._counts.get(purpose, 0)
            text = scripted[min(i, len(scripted) - 1)]
            self._counts[purpose] = i + 1

        return LLMResponse(
            text=text,
            input_tokens=_estimate_tokens(system + " " + prompt),
            output_tokens=_estimate_tokens(text),
            model="fake",
        )
