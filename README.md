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

Then open **http://127.0.0.1:8000/** for the console: file a report, then see its verdict,
brief-by time, briefing (with the approve button), cost, and one trace card per step.
The API is documented at http://127.0.0.1:8000/docs.

Reports are saved in SQLite at `data/mission_control.db` (git-ignored), so they are still there
after a restart. Set `MISSION_CONTROL_DB` to use a different file.

### Using Claude

With no API key the app runs in **demo mode**: every step runs, but model steps return canned
replies and cost $0. To use Claude, copy `.env.example` to `.env` (git-ignored) and set
`ANTHROPIC_API_KEY`. Every step uses `claude-opus-5-5` unless `MISSION_CONTROL_MODEL` says
otherwise. `GET /health` shows which one is in use.

## Run the tests

```bash
uv run pytest
```

Tests need no network and no API key: every model call goes through the `LLMClient`
interface ([app/llm/client.py](app/llm/client.py)), and tests use `FakeLLM`
([app/llm/fake.py](app/llm/fake.py)).
