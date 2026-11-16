"""The real LLMClient: Claude through the official Anthropic SDK.

- Steps with a JSON reply (sort, checks, review) are sent their schema as a
  structured output, so Claude's reply is held to it. The pipeline still checks
  every reply in code, because a refusal or error can still produce no JSON.
- Server-side refusal fallback is on: if Claude declines for safety reasons,
  the API re-runs the request on a fallback model within the same call.
- The API key is read by the SDK from ANTHROPIC_API_KEY; it never appears in code.
"""

from collections.abc import Mapping

import anthropic

from app.llm.client import LLMResponse

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLM:
    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        schemas: Mapping[str, dict] | None = None,
        client: anthropic.AsyncAnthropic | None = None,
        max_tokens: int = 16000,
    ):
        self.model = model
        self._schemas = dict(schemas or {})
        self._client = client or anthropic.AsyncAnthropic()
        self._max_tokens = max_tokens

    async def complete(self, *, purpose: str, system: str, prompt: str) -> LLMResponse:
        extra = {}
        if schema := self._schemas.get(purpose):
            extra["output_config"] = {"format": {"type": "json_schema", "schema": schema}}

        response = await self._client.beta.messages.create(
            model=self.model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            betas=[FALLBACK_BETA],
            fallbacks="default",
            **extra,
        )

        # Thinking blocks are skipped; on a refusal there may be no text at all,
        # which the pipeline treats as an unusable reply and falls back safely.
        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResponse(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            # The model that actually answered (a fallback model is priced as itself).
            model=response.model,
        )
