# Job Agent V1

Job Agent is a lightweight, local-first job-hunting assistant for one user. It discovers jobs, normalizes and deduplicates them, scores relevant roles with a configured AI provider, builds a daily application queue, tracks application state, sends optional Telegram notifications, and keeps scan health visible in a browser dashboard.

M01 Project Foundation through M23 Final System Verification are complete.

## What the project includes

- Multiple active candidate profiles with target roles, synonyms, skills, experience, locations, work modes, salary preference, exclusions, notes, and approval-gated AI suggestions.
- Multiple TXT, PDF, or DOCX resumes per profile, extracted text, and one primary resume.
- A persistent company registry populated from bundled seeds and optional web discovery.
- Supported connectors for Greenhouse, Lever, Ashby, and pragmatic Workday variants.
- Recognition of iCIMS and BambooHR, plus a bounded best-effort generic career-page fallback. Unsupported sources are recorded and skipped safely.
- Canonical job normalization, source/URL/content deduplication, and update-in-place behavior.
- Job lifecycle states: `open`, `possibly_closed`, and `closed`.
- Deterministic qualification before AI scoring.
- Structured AI matching through OpenAI, Anthropic, or Gemini HTTP adapters. AI matching is disabled until explicitly configured.
- A browser dashboard with Apply Today, Strong Matches, New Jobs, Applied, and Scan Health views.
- Filters for profile, role, score, location mode, city, source, lifecycle, user state, salary, remote work, posting date, and discovery date.
- Job details with score breakdown, skills, concerns, explanation, original URL, suggested resume, and Save/Applied/Ignore actions.
- A configurable daily action queue, defaulting to the strongest 10 open and unhandled jobs.
- One in-process scheduler, defaulting to every four hours, plus Search Now and overlap prevention.
- Optional Telegram notifications for high matches, application activity, and scan summaries, with durable duplicate suppression.
- Persistent scan/run health with source failures, counts, error details, and retry counts.
- One portable backup archive containing the database, resume files, and non-secret portable settings.
- A deterministic 21-step final verification workflow.

Job Agent does not auto-apply, fill forms, bypass access controls, run a local LLM, or provide authentication, multi-tenancy, billing, interview CRM, document generation, or SaaS infrastructure.

## How it works

```text
Browser
  -> FastAPI + Jinja2 application
  -> manual Search Now or in-process APScheduler
  -> profile-derived web discovery
  -> ATS detection
  -> Greenhouse / Lever / Ashby / Workday / generic collectors
  -> normalize + deduplicate + lifecycle reconciliation
  -> deterministic qualification
  -> optional structured AI matching
  -> dashboard + daily queue + Telegram + scan history
  -> SQLite database and local resume files
```

The application is one Python process with SQLite. It does not require Redis, Celery, Kafka, a separate database server, Node.js, a browser worker, Docker, or a local model. It is designed for a Linux laptop with 8 GB RAM and approximately 6 GB normally available.

## Requirements

- Python 3.12 or newer
- macOS or Linux
- A modern browser
- Internet access only when using live web search, ATS sources, AI matching, or Telegram
- Optional provider credentials:
  - Brave Search API key for automatic company discovery
  - An OpenAI, Anthropic, or Gemini API key and model name for scoring
  - A Telegram bot token and chat IDs for notifications

The application starts without external credentials. Without AI configuration, jobs can still be collected and reviewed, but they will not receive match scores or enter the scored Apply Today queue.

## Quick start

Run all commands from the repository root.

### 1. Check Python

```bash
python3 --version
```

The version must be 3.12 or newer.

On macOS with Homebrew:

```bash
brew install python@3.12
```

On Debian/Ubuntu, install the distribution packages and confirm their version:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
python3 --version
```

If the distribution provides an older Python, use its supported method to install Python 3.12+ before continuing.

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Activate `.venv` again whenever opening a new terminal for this project.

### 3. Install Job Agent

For normal use:

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

For normal use plus the verification commands in this guide:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

### 4. Create local configuration

```bash
cp .env.example .env
```

The copied defaults are safe to start. `.env` is ignored by Git and must remain private.

If you do not have a Brave Search key, set this in `.env` to avoid a discovery-not-configured warning:

```dotenv
JOB_AGENT_SEARCH_PROVIDER=disabled
```

Seeded and previously known companies still scan when discovery is disabled.

### 5. Start the application

Development mode with automatic reload:

```bash
uvicorn app.main:app --reload
```

Regular local mode:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Stop the process with `Ctrl+C`.

Startup automatically creates the data directories and SQLite database, applies Alembic migrations, imports bundled company seeds idempotently, starts one scheduler, and serves the dashboard.

### 6. Confirm health

Open <http://127.0.0.1:8000/health>, or run:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok","database":"ok"}
```

## First-use walkthrough

1. Open **Profiles** at <http://127.0.0.1:8000/profiles>.
2. Create at least one active profile with target roles, synonyms, skills, experience, and preferred locations.
3. Upload a TXT, PDF, or DOCX resume. The first resume becomes primary automatically.
4. Open **Companies** at <http://127.0.0.1:8000/companies> to review the bundled registry.
5. Configure web discovery and AI matching in `.env` if desired, then restart Job Agent.
6. Click **Search Now**. Known ATS sources still run when web discovery is disabled or unavailable.
7. Follow the run on the dashboard and inspect retained results at <http://127.0.0.1:8000/scans>.
8. Open **Jobs** at <http://127.0.0.1:8000/jobs> and use filters to review roles.
9. Open a job to inspect its description and match explanation. Use **Save**, **Mark Applied**, or **Ignore**. Applied records may include a resume and note.
10. Review **Apply Today** for the highest-scoring open jobs that are not Applied or Ignored.
11. Optionally configure Telegram at <http://127.0.0.1:8000/settings/notifications>.
12. Export a backup at <http://127.0.0.1:8000/settings/backup> after collecting useful data.

## Browser pages

| Page | URL | Purpose |
|---|---|---|
| Dashboard | <http://127.0.0.1:8000/> | Queue, matches, metrics, scheduler, Search Now, and latest scan |
| Jobs | <http://127.0.0.1:8000/jobs> | Paginated job list and all V1 filters |
| Profiles | <http://127.0.0.1:8000/profiles> | Profiles, resumes, and pending AI suggestions |
| Companies | <http://127.0.0.1:8000/companies> | Seeded/discovered registry and source status |
| Scans | <http://127.0.0.1:8000/scans> | Run history, counts, failures, and retry information |
| Telegram | <http://127.0.0.1:8000/settings/notifications> | Three notification destinations |
| Backup & Restore | <http://127.0.0.1:8000/settings/backup> | Download or restore one archive |
| Health | <http://127.0.0.1:8000/health> | Application and database readiness |

## Configuration

Configuration is read from environment variables and the repository-root `.env`. Restart after changing `.env`.

Portable, non-secret settings may also be restored from a backup. Explicit destination environment values take precedence over restored values. Secrets and machine-specific paths always remain local to the destination.

### Core and storage

| Variable | Default | Meaning |
|---|---:|---|
| `JOB_AGENT_APP_NAME` | `Job Agent` | Browser/application title |
| `JOB_AGENT_ENVIRONMENT` | `local` | `local`, `test`, or `production` |
| `JOB_AGENT_DATABASE_URL` | `sqlite:///./data/job_agent.db` | File-backed SQLite URL |
| `JOB_AGENT_LOG_LEVEL` | `INFO` | Python log level |
| `JOB_AGENT_RESUME_STORAGE_PATH` | `./data/resumes` | Controlled resume directory |
| `JOB_AGENT_RESUME_MAX_BYTES` | `5242880` | Per-file limit; range 1 byte–25 MiB |
| `JOB_AGENT_COMPANY_SEED_PATH` | `./data/seeds/companies.json` | Seed JSON imported at startup |
| `JOB_AGENT_DAILY_ACTION_TARGET` | `10` | Apply Today size; range 1–100 |
| `JOB_AGENT_SCAN_INTERVAL_HOURS` | `4` | Scheduler interval; range 0.25–168 hours |

### Web discovery

| Variable | Default | Meaning |
|---|---:|---|
| `JOB_AGENT_SEARCH_PROVIDER` | `brave` | `brave` or `disabled` |
| `JOB_AGENT_BRAVE_SEARCH_API_KEY` | empty | Brave Search credential |
| `JOB_AGENT_SEARCH_COUNTRY` | `IN` | Two-character search country |
| `JOB_AGENT_SEARCH_LANGUAGE` | `en` | Search language, 2–10 characters |
| `JOB_AGENT_SEARCH_RESULTS_PER_QUERY` | `10` | Results per query; range 1–20 |
| `JOB_AGENT_SEARCH_MAX_QUERIES_PER_RUN` | `30` | Queries per scan; range 1–100 |
| `JOB_AGENT_SEARCH_CONCURRENCY` | `3` | Concurrent requests; range 1–5 |
| `JOB_AGENT_SEARCH_TIMEOUT_SECONDS` | `10` | Request timeout; range 1–30 seconds |

Enable discovery with:

```dotenv
JOB_AGENT_SEARCH_PROVIDER=brave
JOB_AGENT_BRAVE_SEARCH_API_KEY=your_private_key
```

Or scan only bundled/already-known sources:

```dotenv
JOB_AGENT_SEARCH_PROVIDER=disabled
JOB_AGENT_BRAVE_SEARCH_API_KEY=
```

### Job sources

| Variable | Default | Meaning |
|---|---:|---|
| `JOB_AGENT_JOB_SOURCE_TIMEOUT_SECONDS` | `15` | Source HTTP timeout; range 1–60 seconds |
| `JOB_AGENT_JOB_SOURCE_CONCURRENCY` | `3` | Concurrent source work; range 1–5 |
| `JOB_AGENT_JOB_SOURCE_MAX_RESPONSE_BYTES` | `8388608` | Response limit; range 1 KiB–25 MiB |
| `JOB_AGENT_JOB_LIFECYCLE_CLOSE_AFTER_MISSING_SCANS` | `3` | Successful absences required to close; range 3–20 |

The application prefers structured public ATS endpoints. Generic HTML collection has strict URL, content-type, timeout, response-size, and link limits and does not execute scripts or bypass access controls.

### AI matching

| Variable | Default | Meaning |
|---|---:|---|
| `JOB_AGENT_AI_PROVIDER` | `disabled` | `disabled`, `openai`, `anthropic`, or `gemini` |
| `JOB_AGENT_AI_MODEL` | empty | Selected provider's model identifier |
| `JOB_AGENT_OPENAI_API_KEY` | empty | OpenAI credential |
| `JOB_AGENT_ANTHROPIC_API_KEY` | empty | Anthropic credential |
| `JOB_AGENT_GEMINI_API_KEY` | empty | Gemini credential |
| `JOB_AGENT_AI_TIMEOUT_SECONDS` | `45` | Request timeout; range 5–120 seconds |
| `JOB_AGENT_AI_CONCURRENCY` | `2` | Concurrent requests; range 1–3 |

Configure one provider, its model, and matching key. Example:

```dotenv
JOB_AGENT_AI_PROVIDER=openai
JOB_AGENT_AI_MODEL=your_provider_model_identifier
JOB_AGENT_OPENAI_API_KEY=your_private_key
JOB_AGENT_ANTHROPIC_API_KEY=
JOB_AGENT_GEMINI_API_KEY=
```

Equivalent settings work for `anthropic` and `gemini`. Obtain a currently supported model identifier from the provider. Job descriptions and resumes are treated as untrusted prompt data.

| Score | Label |
|---:|---|
| 90–100 | Excellent |
| 85–89 | Strong |
| 75–84 | Review |
| Below 75 | Low Priority |

Unchanged jobs are not rescored. Materially changed jobs are updated and rescored while user state is retained.

### Telegram

| Variable | Default | Meaning |
|---|---:|---|
| `JOB_AGENT_TELEGRAM_BOT_TOKEN` | empty | Telegram bot token |
| `JOB_AGENT_TELEGRAM_MATCH_THRESHOLD` | `85` | High-match threshold; range 0–100 |
| `JOB_AGENT_TELEGRAM_TIMEOUT_SECONDS` | `10` | Request timeout; range 1–30 seconds |

Setup:

1. Obtain a bot token through Telegram's official workflow.
2. Put it only in `.env` as `JOB_AGENT_TELEGRAM_BOT_TOKEN`.
3. Restart Job Agent.
4. Open <http://127.0.0.1:8000/settings/notifications>.
5. Configure a numeric chat ID and enable any destination:
   - High-match recommendations
   - Application activity
   - Search/run summaries

The token is never rendered or stored in normal application tables. Delivery records provide duplicate suppression and debugging.

## Job and lifecycle behavior

- Discovery keeps all currently open jobs regardless of posting age.
- Rediscovery updates the existing row and `last_seen_at` instead of creating a duplicate.
- One successful scan absence keeps a job open.
- Multiple absences move it to `possibly_closed`.
- The configured repeated-absence threshold closes it.
- A reappearing job is reopened and its missing counter resets.
- Closed jobs are hidden by default but remain available through the lifecycle filter.
- Saved, Applied, and Ignored state persists through rediscovery, updates, lifecycle changes, backup, and restart.
- Applying may store a timestamp, selected profile-owned resume, and note. Job Agent never submits the application.

## Data and files

| Default path | Contents |
|---|---|
| `data/job_agent.db` | SQLite database |
| `data/job_agent.db-wal` / `data/job_agent.db-shm` | Normal SQLite WAL sidecars while running |
| `data/resumes/` | Uploaded resume files |
| `data/seeds/companies.json` | Bundled company seeds |
| `.env` | Local paths, credentials, and configuration |

The database stores profiles and suggestions; resume metadata and extracted text; companies; normalized jobs and lifecycle counters; AI matches; Saved/Applied/Ignored state and application history; Telegram destinations and delivery logs; scan runs and source results; and portable non-secret settings.

Use one running Job Agent process per database. Do not point multiple instances at the same SQLite file.

## Backup and restore

Open <http://127.0.0.1:8000/settings/backup>.

### Export

**Download backup** creates one ZIP containing:

- a consistent SQLite snapshot;
- all referenced resume files;
- a versioned size/checksum manifest;
- portable non-secret settings.

It excludes API keys, Telegram bot token, `.env`, database/resume paths, seed path, and environment name.

### Restore

1. Wait for any active scan to finish.
2. Select an exported Job Agent ZIP.
3. Confirm replacement of current local database and resume data.
4. Click **Validate & Restore**.
5. Restart Job Agent after success.

Restore validates paths, limits, checksums, database integrity, schema, foreign keys, settings, and resume references before replacement. Current data remains intact if validation fails.

The archive is not encrypted and contains personal data. Store it securely. It is path-portable between macOS and Linux.

## Scheduler behavior

- Runs only while the Job Agent process is running.
- Defaults to four hours.
- Search Now and scheduled scans use the same pipeline and overlap guard.
- Does not start a second scan while one is active.
- Has no application-level boot integration.
- Records an interrupted Running scan as Failed on restart, then resumes scheduling.

## Linux service setup

First complete Quick start and verify the application interactively. Keep the repository and data writable by the selected Linux user.

Create `/etc/systemd/system/job-agent.service`, replacing the user and paths:

```ini
[Unit]
Description=Job Agent V1
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/job-ai-agent
EnvironmentFile=/home/YOUR_USER/job-ai-agent/.env
ExecStart=/home/YOUR_USER/job-ai-agent/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now job-agent
sudo systemctl status job-agent
```

View logs and restart after `.env` changes or restore:

```bash
journalctl -u job-agent -f
sudo systemctl restart job-agent
```

V1 has no authentication. Keep it on `127.0.0.1` and do not expose it directly to the public internet. Remote access requires a separately secured boundary outside V1 scope.

## Migrations

Migrations run automatically at startup. To inspect or apply them manually:

```bash
alembic current
alembic upgrade head
```

The V1 head revision is `20260809_0010`. Back up useful data before updates or manual database maintenance.

## Verification and tests

Install test dependencies:

```bash
python -m pip install -e ".[test]"
```

Run the deterministic 21-step V1 workflow:

```bash
pytest tests/final/test_m23_end_to_end.py
```

Expected result: `1 passed`. It uses isolated temporary files and local fixtures and does not contact live search, AI, or Telegram services.

Run all M01–M22 focused module tests:

```bash
pytest tests/module
```

Run both groups when deliberately performing complete repository verification:

```bash
pytest tests/module tests/final
```

Check installed dependencies:

```bash
python -m pip check
```

## Updating an existing checkout

1. Export a backup.
2. Stop Job Agent.
3. Update the repository through your normal source-control workflow.
4. Activate `.venv`.
5. Refresh dependencies and apply migrations:

   ```bash
   python -m pip install -e ".[test]"
   alembic upgrade head
   ```

6. Start Job Agent and check `/health`.

## Troubleshooting

### Python is older than 3.12

Install Python 3.12+ through the operating system's supported tooling, recreate `.venv`, and reinstall the project.

### A command is not found

```bash
source .venv/bin/activate
python -m pip install -e ".[test]"
```

### Port 8000 is already in use

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Then open <http://127.0.0.1:8001>.

### No jobs appear

Confirm that an active profile exists, bundled companies appear, Search Now completed, and `/scans` shows source results. Configure Brave discovery or intentionally disable it. Public sources may change or block access; Job Agent logs and skips them without bypassing controls.

### Jobs have no scores or queue entries

Set `JOB_AGENT_AI_PROVIDER`, `JOB_AGENT_AI_MODEL`, and the selected provider key consistently. Restart, then run Search Now. Only qualified jobs are scored.

### Telegram shows Not configured

Set a non-empty `JOB_AGENT_TELEGRAM_BOT_TOKEN`, restart, then configure and enable numeric chat IDs in the browser.

### SQLite is locked or busy

Ensure only one Job Agent process uses the database. Stop duplicate Uvicorn or systemd instances and start one process.

### Resume upload fails

Use a readable TXT, PDF, or DOCX within `JOB_AGENT_RESUME_MAX_BYTES`. Empty, encrypted, invalid, oversized, and unsupported files are rejected; accepted uploads are stored under controlled generated filenames.

### Restore fails

Wait for scans to finish, use an unedited ZIP from this schema version, remain within the displayed limit, and review the browser validation message. Restart after success.

### Linux reports file permission errors

The service user needs repository and `.env` read access plus write access to database and resume directories. Keep `WorkingDirectory` consistent with relative `.env` paths.

## Security and privacy

- Keep `.env` private and never commit, print, or share it.
- API keys and Telegram token are excluded from backups.
- Resumes, extracted text, job history, application notes, and Telegram chat IDs are personal local data.
- Backups contain personal data even though secrets are excluded.
- Job descriptions and web content are untrusted input.
- The generic collector does not execute JavaScript, crawl without bounds, or bypass login, CAPTCHA, rate limits, or anti-bot systems.
- V1 has no login. Bind locally and do not expose it directly to the public internet.

## Repository layout

```text
app/
  models/          SQLAlchemy models
  providers/       Search, job-source, AI, and Telegram boundaries
  repositories/    Persistence queries
  schemas/         Validated inputs and structured outputs
  services/        Discovery, matching, lifecycle, scans, notifications, backup
  tasks/           In-process scheduler
  web/             Routes, Jinja2 templates, and local CSS
data/seeds/         Bundled company seeds
migrations/         Alembic revisions
tests/module/       M01-M22 focused tests
tests/final/        M23 end-to-end workflow
docs/               Frozen specification and implementation status
```

## Project documentation

- `docs/00_PRODUCT_SCOPE.md` — frozen product behavior and exclusions
- `docs/01_TECHNICAL_ARCHITECTURE.md` — architecture and resource limits
- `docs/02_DATA_MODEL.md` — persistence model
- `docs/03_MODULES_AND_ACCEPTANCE.md` — M01–M23 acceptance criteria
- `docs/04_TESTING_POLICY.md` — verification policy
- `docs/05_UI_UX_REFERENCE_THEME.md` — visual direction
- `docs/08_LOCAL_LINUX_RUNBOOK.md` — target runtime constraints
- `docs/09_SECURITY_AND_EXTERNAL_ACCESS.md` — secrets and external access
- `docs/IMPLEMENTATION_STATUS.md` — completed module evidence and decisions
