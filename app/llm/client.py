"""The single interface every model call goes through.

Pipeline code depends only on LLMClient, so tests swap in FakeLLM and
never touch the network or need an API key.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str

@runtime_checkable
class LLMClient(Protocol):
    async def complete(self, *, purpose: str, system: str, prompt: str) -> LLMResponse:
        """Run one model call.

        `purpose` names the pipeline step (e.g. "classify", "draft"); it labels
        trace cards and lets FakeLLM pick a scripted reply.
        """
        ...
