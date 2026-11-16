"""Every test runs with no network and no API key.

Even if a developer's shell or .env has ANTHROPIC_API_KEY, the app under test
is forced into demo mode, and tests that need model replies inject FakeLLM.
"""

import pytest


@pytest.fixture(autouse=True)
def never_call_a_real_model(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Set before the app loads .env, and .env never overrides an existing variable.
    monkeypatch.setenv("MISSION_CONTROL_LLM", "demo")
