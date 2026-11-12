from app.llm.client import LLMClient, LLMResponse
from app.llm.fake import FakeLLM


async def test_fake_llm_returns_scripted_reply_and_records_call():
    fake = FakeLLM(replies={"classify": '{"subsystem": "propulsion", "severity": "high"}'})

    # FakeLLM must satisfy the same protocol the real adapter does.
    assert isinstance(fake, LLMClient)

    resp = await fake.complete(purpose="classify", system="sys", prompt="valve stuck")

    assert isinstance(resp, LLMResponse)
    assert resp.text == '{"subsystem": "propulsion", "severity": "high"}'
    assert resp.model == "fake"
    assert resp.input_tokens > 0 and resp.output_tokens > 0
    assert fake.calls == [{"purpose": "classify", "system": "sys", "prompt": "valve stuck"}]
