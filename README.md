# Mission Control: Go/No-Go Launch Console

Engineers file anomaly reports; a pipeline classifies them, checks launch limits in plain code,
and drafts a briefing that only the Flight Director can approve.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (`brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)

uv creates the virtual environment and installs dependencies on first run. No other setup is needed.

## Start the app

```bash
uv run uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/health.

## Run the tests

```bash
uv run pytest
```

Tests need no network and no API key: every model call goes through the `LLMClient`
interface ([app/llm/client.py](app/llm/client.py)), and tests use `FakeLLM`
([app/llm/fake.py](app/llm/fake.py)).
