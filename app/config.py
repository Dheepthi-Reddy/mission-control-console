"""Choose which LLMClient the app uses, from environment variables.

MISSION_CONTROL_LLM   "anthropic" or "demo". If unset: "anthropic" when
                      ANTHROPIC_API_KEY is set, otherwise "demo".
MISSION_CONTROL_MODEL Claude model for every step (default claude-opus-5-5).

The app refuses to start with a model that has no price, so a report's cost is
never silently wrong.
"""

from collections.abc import Mapping

from app.domain.cost import PRICES_PER_MTOK
from app.llm.anthropic_client import DEFAULT_MODEL, AnthropicLLM
from app.llm.client import LLMClient
from app.llm.demo import DemoLLM
from app.pipeline.runner import REPLY_SCHEMAS


def choose_llm(environ: Mapping[str, str]) -> tuple[LLMClient, str]:
    """Return the client and a short label for it (shown by /health and the console)."""
    mode = environ.get("MISSION_CONTROL_LLM") or ("anthropic" if environ.get("ANTHROPIC_API_KEY") else "demo")

    if mode == "demo":
        return DemoLLM(), "demo"
    if mode == "anthropic":
        model = environ.get("MISSION_CONTROL_MODEL") or DEFAULT_MODEL
        if model not in PRICES_PER_MTOK:
            raise ValueError(f"MISSION_CONTROL_MODEL={model!r} has no price in app/domain/cost.py")
        return AnthropicLLM(model=model, schemas=REPLY_SCHEMAS), model
    raise ValueError(f"MISSION_CONTROL_LLM must be 'anthropic' or 'demo', got {mode!r}")
