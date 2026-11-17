# Mission Control: Go/No-Go Launch Console

Engineers file free-text anomaly reports before a launch. Mission Control Console sorts each report with a model, checks the readings against the launch limits **in plain code**, runs three safety checks on the note, and drafts a short briefing that **only a person** (the Flight Director) can approve. The console shows every report's verdict, brief-by time, briefing, cost, and a trace card for each step.

Why each tool was chosen: [TOOL_CHOICES.md](TOOL_CHOICES.md).

## Requirements

- uv (install with `brew install uv`)
- Python 3.12 and all dependencies are installed by uv on the first run
- An Anthropic API key (optional);
## Start the app

```bash
uv run uvicorn app.main:app
```

Open **http://127.0.0.1:8000/**. Click **＋ New report**, fill in the form, and the report appears
in the list. Open it to see the verdict, the brief-by countdown, the briefing (with the approve
button), the cost and the trace. The API is documented at http://127.0.0.1:8000/docs.

Reports are saved in SQLite at `data/mission_control.db`, and still exist
after a restart.

### Using Claude

The app works without an API key, in **demo mode**:

- Every step still runs.
- Model steps return pre-written replies instead of calling Claude, and cost $0.
- The header shows an amber **Demo mode** badge.

**To switch to Claude:**

1. Create your settings file:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and paste your key after `ANTHROPIC_API_KEY=`.
3. Restart the app. The header badge turns green and shows `claude-opus-5-5`.

The app reads `.env` only when it starts, so restart it after any change. `.env` is git-ignored;
we never commit a key.

**Optional settings in `.env`:**

| Setting | What it does |
|---|---|
| `MISSION_CONTROL_MODEL` | Which Claude model to use. Must be one with a price in the app. Default: `claude-opus-5-5` |
| `MISSION_CONTROL_LLM` | Force `demo` or `anthropic` mode, whether or not a key is set |
| `MISSION_CONTROL_DB` | Where reports are saved. Default: `data/mission_control.db` |

## Run the tests

```bash
uv run pytest
```

The whole suite finishes in a few seconds. The tests need **no network and no API key**: every model call
goes through one interface, `LLMClient` ([app/llm/client.py](app/llm/client.py)). The tests use
`FakeLLM` ([app/llm/fake.py](app/llm/fake.py)), and [tests/conftest.py](tests/conftest.py) forces
them off the real API even if a key is in `.env`. CI runs the same command on every push
([.github/workflows/ci.yaml](.github/workflows/ci.yaml)).

## How a report is processed

| Step | Done by | Where |
|---|---|---|
| Validate and save the report | code | [app/domain/report.py](app/domain/report.py), [app/db.py](app/db.py) |
| Sort by subsystem and severity | model, reply checked in code | [app/pipeline/classify.py](app/pipeline/classify.py) |
| Three note checks, **at the same time**: hidden instructions, missing details, panic | model ×3, plus a code backstop for hidden instructions | [app/pipeline/checks.py](app/pipeline/checks.py) |
| Check launch limits and set the verdict | **code only** | [app/domain/limits.py](app/domain/limits.py) |
| Set the brief-by time (high 5, medium 15, low 30 min; any violation counts as high) | **code only** | [app/domain/brief_by.py](app/domain/brief_by.py) |
| Draft the briefing, review it, redraft with the feedback (up to 3 rounds) | model ×2 per round | [app/pipeline/briefing.py](app/pipeline/briefing.py) |
| Cost per step and per report, from token counts | **code only** | [app/domain/cost.py](app/domain/cost.py) |
| Approve the briefing | **a person only** | `POST /reports/{id}/approve` |

Sorting and the three checks run together; the draft/review loop runs after them
([app/pipeline/runner.py](app/pipeline/runner.py)). The note is treated as untrusted data
throughout: it can never change the verdict, and the console shows it as plain text.

**Launch limits:** wind 25 knots or less, temperature 4 °C or more, fuel 98 to 100 percent. Any
reading outside its limit makes the verdict `no_go`.

## Where each requirement is met

| Requirement | Code | Tests |
|---|---|---|
| One command to start, one to test | this README | CI on every push |
| Tool choices explained | [TOOL_CHOICES.md](TOOL_CHOICES.md) | — |
| Filing reports, clear errors, survives a restart | [app/static/](app/static/), [app/main.py](app/main.py), [app/db.py](app/db.py) | [test_reports.py](tests/test_reports.py), [test_persistence_restart.py](tests/test_persistence_restart.py), [test_console.py](tests/test_console.py) |
| Launch limits in plain code, exact at each limit | [app/domain/limits.py](app/domain/limits.py) | [test_limits.py](tests/test_limits.py) |
| Brief-by time from severity; a violation counts as high | [app/domain/brief_by.py](app/domain/brief_by.py) | [test_brief_by.py](tests/test_brief_by.py) |
| Sorting with a schema, checked in code, safe fallback | [app/pipeline/classify.py](app/pipeline/classify.py) | [test_classify.py](tests/test_classify.py) |
| Three checks at once; hidden instructions flagged, sent to review, verdict unchanged | [app/pipeline/checks.py](app/pipeline/checks.py) | [test_checks.py](tests/test_checks.py), [test_pipeline.py](tests/test_pipeline.py) |
| Draft/review stops at 3 rounds, feedback goes forward, only a person approves | [app/pipeline/briefing.py](app/pipeline/briefing.py), [app/db.py](app/db.py) | [test_briefing_loop.py](tests/test_briefing_loop.py), [test_approval.py](tests/test_approval.py) |
| One trace card per step with tokens; cost calculated in code | [app/static/app.js](app/static/app.js), [app/domain/cost.py](app/domain/cost.py) | [test_cost.py](tests/test_cost.py), [test_pipeline.py](tests/test_pipeline.py), [test_console.py](tests/test_console.py) |
| Tests offline through one model interface with a fake | [app/llm/client.py](app/llm/client.py), [app/llm/fake.py](app/llm/fake.py) | [conftest.py](tests/conftest.py), the whole suite |

## Project layout

```
app/
  main.py            routes, background pipeline, error messages
  config.py          picks Claude or demo mode from the environment
  db.py              SQLite storage: reports, analyses, trace steps, briefings
  domain/            plain-code rules: report, limits, brief_by, cost, briefing, analysis
  llm/               client.py (the one interface), anthropic_client.py, fake.py, demo.py
  pipeline/          classify, checks, briefing (draft/review), runner, prompting
  static/            the console: index.html, app.js, styles.css
tests/               the test suite; no network or key needed
TOOL_CHOICES.md      why each tool was chosen
```
