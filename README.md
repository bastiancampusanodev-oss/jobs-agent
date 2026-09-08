# agentes v0.1

Reusable personal-agent core plus the first real agent: **Job Agent / Get on Board**.

This version is intentionally **DRY_RUN**. It can:

- analyze a vacancy with the OpenAI Agents SDK;
- return a validated Pydantic decision instead of free-form prose;
- choose one of 10 stable CV IDs;
- draft truthful paste-ready application answers;
- connect to a Brave Chromium session through CDP;
- inspect open tabs and read the current Get on Board page;
- store decisions in SQLite and avoid processing the same URL twice.

It does **not submit applications yet**. Submission is the next layer after selectors and field mapping are validated.

## 1. Install

```bash
cd agentes-v0.1
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e '.[dev]'
```

Because this build attaches to your existing Brave over CDP, you do not need Playwright's bundled Chromium for the first tests.

## 2. API key

```bash
export OPENAI_API_KEY='sk-...'
export AGENT_MODEL='gpt-5.6-terra'
```

Do not commit the key.

## 3. First test: no browser

```bash
python run.py jobs fixture examples/job_34.txt --no-save
```

Expected shape: APPLY / REVIEW / SKIP, a 0-100 score, selected CV ID, gaps, salary (if justified), and application answers.

## 4. Test SQLite

```bash
pytest -q
```

## 5. Brave connection

Important: Chromium remote debugging is enabled when the browser process starts. A normal already-running Brave process cannot retroactively gain the port.

Close the dedicated automation Brave profile if it is already running, then:

```bash
./scripts/launch_brave_debug.sh
```

This uses a separate profile by default:

```text
~/.config/BraveSoftware/Brave-Browser-Agent
```

Log in to Get on Board in that profile once. Then leave the desired vacancy tab open.

In another terminal:

```bash
cd agentes-v0.1
source .venv/bin/activate
export OPENAI_API_KEY='sk-...'
python run.py jobs browser-probe
```

You should see the open URLs.

## 6. Analyze current Get on Board tab

```bash
python run.py jobs current --no-save
```

When the output looks correct:

```bash
python run.py jobs current
python run.py jobs recent
```

## 7. Before we enable form filling

Put the real ten canonical CV PDFs inside:

```text
cvs/
```

Then update `config/cvs.yaml` with the **exact** filenames. The stable IDs should remain `01_ES`, `01_EN`, ..., `09_ES`, `09_EN` unless we intentionally redesign the catalog.

## Architecture

```text
Brave/GetOnBoard
      ↓ CDP
Playwright browser layer
      ↓ visible vacancy text
JobDecision Agent (GPT-5.6 Terra by default)
      ↓ structured Pydantic object
truth validator
      ↓
SQLite state
      ↓
[next: form mapper → uploader → pre-submit verifier → submit]
```

## Safety invariant

The candidate YAML is treated as the source of truth. If the model emits an unsupported claim, the schema forces an `APPLY` result to `REVIEW`. This is not sufficient by itself for production, but it gives us a deterministic first guardrail.

## Next milestone

The next build adds a `GetOnBoardAdapter` with:

1. extraction of the vacancy URL/title/company;
2. detection of application form fields;
3. mapping each field to a structured answer;
4. CV file upload by stable ID;
5. salary conversion/formatting;
6. screenshot + validation before submit;
7. `DRY_RUN=true` and explicit `SUBMIT=true` modes;
8. loop to the next unprocessed vacancy.
