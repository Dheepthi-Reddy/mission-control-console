"""The real Claude client, tested against a stand-in for the SDK: no network, no key."""

from types import SimpleNamespace

import pytest

from app.config import choose_llm
from app.llm.anthropic_client import FALLBACK_BETA, AnthropicLLM
from app.llm.client import LLMClient
from app.llm.demo import DemoLLM
from app.pipeline.runner import REPLY_SCHEMAS


class StubMessages:
    def __init__(self, content, model="claude-opus-5-5"):
        self.content = content
        self.model = model
        self.sent: list[dict] = []

    async def create(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(
            content=self.content,
            usage=SimpleNamespace(input_tokens=321, output_tokens=12),
            model=self.model,
            stop_reason="end_turn",
        )


def stub_client(content, **kw):
    messages = StubMessages(content, **kw)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def text(t):
    return SimpleNamespace(type="text", text=t)


THINKING = SimpleNamespace(type="thinking", thinking="")


def llm_with(content, **kw):
    client, messages = stub_client(content, **kw)
    return AnthropicLLM(model="claude-opus-5-5", schemas=REPLY_SCHEMAS, client=client), messages


def test_satisfies_the_one_model_interface():
    llm, _ = llm_with([text("x")])
    assert isinstance(llm, LLMClient)


async def test_sends_model_system_prompt_and_refusal_fallback():
    llm, messages = llm_with([text("ok")])
    await llm.complete(purpose="draft", system="SYS", prompt="PROMPT")
    [sent] = messages.sent
    assert sent["model"] == "claude-opus-5-5"
    assert sent["system"] == "SYS"
    assert sent["messages"] == [{"role": "user", "content": "PROMPT"}]
    assert sent["betas"] == [FALLBACK_BETA]
    assert sent["fallbacks"] == "default"


@pytest.mark.parametrize("purpose", ["classify", "check_injection", "check_missing_details", "check_panic", "review"])
async def test_json_steps_are_sent_their_schema_as_structured_output(purpose):
    llm, messages = llm_with([text("{}")])
    await llm.complete(purpose=purpose, system="s", prompt="p")
    fmt = messages.sent[0]["output_config"]["format"]
    assert fmt == {"type": "json_schema", "schema": REPLY_SCHEMAS[purpose]}
    assert fmt["schema"]["additionalProperties"] is False


async def test_draft_is_free_text_with_no_schema():
    llm, messages = llm_with([text("A briefing.")])
    await llm.complete(purpose="draft", system="s", prompt="p")
    assert "output_config" not in messages.sent[0]


async def test_reply_text_tokens_and_answering_model_are_returned():
    llm, _ = llm_with([THINKING, text('{"flagged": '), text("false}")], model="claude-opus-4-8")
    r = await llm.complete(purpose="check_panic", system="s", prompt="p")
    assert r.text == '{"flagged": false}'  # thinking skipped, text blocks joined
    assert (r.input_tokens, r.output_tokens) == (321, 12)
    assert r.model == "claude-opus-4-8"  # priced as the model that actually answered


async def test_refusal_with_no_text_returns_empty_text_for_the_pipeline_to_fall_back_on():
    llm, _ = llm_with([])
    r = await llm.complete(purpose="classify", system="s", prompt="p")
    assert r.text == ""


# --- choosing a client --------------------------------------------------------


def test_no_key_means_demo_mode():
    llm, label = choose_llm({})
    assert isinstance(llm, DemoLLM) and label == "demo"


def test_key_means_claude_with_the_default_model():
    llm, label = choose_llm({"ANTHROPIC_API_KEY": "sk-ant-test-not-real"})
    assert isinstance(llm, AnthropicLLM)
    assert label == llm.model == "claude-opus-5-5"


def test_model_can_be_changed():
    llm, _ = choose_llm({"ANTHROPIC_API_KEY": "k", "MISSION_CONTROL_MODEL": "claude-haiku-5-5"})
    assert llm.model == "claude-haiku-5-5"


def test_demo_can_be_forced_even_with_a_key():
    llm, _ = choose_llm({"ANTHROPIC_API_KEY": "k", "MISSION_CONTROL_LLM": "demo"})
    assert isinstance(llm, DemoLLM)


@pytest.mark.parametrize(
    "env, message",
    [
        ({"ANTHROPIC_API_KEY": "k", "MISSION_CONTROL_MODEL": "claude-unpriced-1"}, "has no price"),
        ({"MISSION_CONTROL_LLM": "openai"}, "must be 'anthropic' or 'demo'"),
    ],
)
def test_bad_settings_stop_the_app_from_starting(env, message):
    with pytest.raises(ValueError, match=message):
        choose_llm(env)
