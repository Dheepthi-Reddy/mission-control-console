# Tool choices

Mission Control has one job: turn free-text anomaly reports into a short, trustworthy briefing
for a Flight Director 90 minutes before launch. Three constraints shaped every choice below:

- **Safety decisions stay in plain code.** The go/no-go verdict, the brief-by time and the cost
  are computed in code. A model never decides them.
- **One command to start, one command to test,** with no network and no API key for the tests.
- **Small and auditable.** A reviewer should be able to read the whole thing in an afternoon.

| Layer | Choice | Rejected alternative |
|---|---|---|
| Back end | Python 3.12 + FastAPI, run with uv | Node.js + Express |
| Front end | Plain HTML, CSS and JavaScript, served by FastAPI | React + Vite |
| Database | SQLite (Python's built-in `sqlite3`) | PostgreSQL |
| Model | Claude Opus 5.5 (`claude-opus-5-5`) through the official Anthropic SDK | Two tiers: Claude Haiku 5.5 for sorting and checks, Claude Sonnet 5.5 for drafting and review |

---

## Back end: Python 3.12 + FastAPI

**Why**
- **Clear validation.** Pydantic rejects bad reports with a message per field, and checks every
  model reply before it is used.
- **Checks run in parallel.** The three note checks run at the same time with one line of code
  (`asyncio.gather`).
- **Exact costs.** Python's `Decimal` keeps money totals exact.
- **Easy setup.** The official Anthropic SDK is built for Python, and uv installs everything with
  one command.

**Rejected: Node.js + Express.** It would work, but it needs extra libraries for validation and
exact money maths. Python has both built in.

**Customer concern:** *"If the model is slow, will engineers have to wait to file a report?"*
No. A report is saved straight away and the model steps run in the background. The console shows
*Analysing* and updates itself when the result is ready.

---

## Front end: plain HTML, CSS and JavaScript

**Why**
- **One screen, no framework needed.** The console is a form, a list and a detail view.
- **Still one start command.** FastAPI serves the files, so there is no Node, `npm install` or
  build step.
- **Tested with everything else** in the same `pytest` run.

**Rejected: React + Vite.** Better for a large UI, but it adds Node, a build step and a second
process. Too much for one screen.

**Customer concern:** *"Could a malicious note run code in the Flight Director's browser?"*
No. The note is always shown as plain text, never as HTML, and a test fails if the code ever
changes that.

---

## Database: SQLite

**Why**
- **Zero setup.** One file, built into Python, no server to run.
- **Survives restarts.** A test reopens the database and checks the reports are still there.
- **Safe by design.**
  - Each report's results are saved all at once, never half-way.
  - A briefing can only be approved once.
  - A newly saved briefing is always *pending*.

**Rejected: PostgreSQL.** Great for many users on many machines, but it needs a running server,
which breaks the one-command start.

**Customer concern:** *"What if we add more consoles and more reports?"*
SQLite easily handles a launch team's volume. If it ever doesn't, all database code is in one
class (`ReportStore`), so switching to PostgreSQL means changing only that class. Backing up is
copying one file.

---

## Model: Claude Opus 5.5

**What the model does.** It reads the note: it sorts the report, runs the three checks, and drafts
and reviews the briefing. Code decides the verdict, the brief-by time and the cost. Only a person
approves.

**Why**
- **Strongest at catching tricks.** The hidden-instruction check is aimed at the model itself, so
  it should run on the strongest one. It caught every injection attempt in our live runs.
- **Accurate briefings.** Most briefings were accepted by the reviewer in the first round.
- **Reliable answers.** Replies are held to a JSON schema and still checked in code.
- **Affordable.** About **$0.03 per report** ($0.021–$0.044 across 13 live reports).

**Rejected: a cheaper two-model setup** (Haiku 5.5 for sorting and checks, Sonnet 5.5 for
briefings). It costs about a third as much, but puts the injection check on the weakest model to
save two cents a report. Worth revisiting only at thousands of reports a day; the model is one
setting.

**Customer concern:** *"Where do our notes go, and what will it cost?"*
- Notes go only to the Anthropic API, using your own key from a private `.env` file. Without a
  key, the app runs in demo mode, and the tests never call the API.
- Cost is calculated in code from real token counts and shown per step and per report.
