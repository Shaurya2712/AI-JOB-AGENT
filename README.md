# Job Agent

Job Agent V1 is a lightweight, local-first job-hunting dashboard. The current implementation contains M01 Project Foundation through M19 Scheduler + Search Now.

## Requirements

- Python 3.12 or newer
- macOS for development or Linux for regular use

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
cp .env.example .env
```

No API keys or other external credentials are required for the foundation application.

## Start

Run the application from the repository root with this single command:

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. The SQLite database is created and migrated automatically during application startup. The health endpoint is available at <http://127.0.0.1:8000/health>.

Candidate profiles can be created and edited at <http://127.0.0.1:8000/profiles>. Multiple profiles may remain active, and stored AI role/skill suggestions require an explicit accept or reject decision before they can change a profile. Each profile can store multiple local TXT, PDF, or DOCX resumes and select one primary resume.

The local company registry is available at <http://127.0.0.1:8000/companies>. The bundled company seed file is imported idempotently at startup. Discovery, ATS detection, supported job-source connectors, normalization/deduplication, and lifecycle handling are implemented as application services; scan orchestration remains a later module.

The paginated job reference is available at <http://127.0.0.1:8000/jobs>. It supports the frozen profile, role, score, location, source, lifecycle, user-state, salary, remote, posted-date, and discovered-date filters. Open a job to review its description, complete match breakdown, linked profile and suggested resume, then Save, Mark Applied, or Ignore it. Applied jobs may record a profile-owned resume and an optional note.

The dashboard's Apply Today section ranks the strongest open scored jobs for active profiles, excluding jobs already applied to or ignored. Set `JOB_AGENT_DAILY_ACTION_TARGET` to change its default target of 10 (maximum 100).

The application starts one in-process scheduler with a four-hour default interval. Set `JOB_AGENT_SCAN_INTERVAL_HOURS` to a value from `0.25` to `168` to change it. Search Now and scheduled scans use the same guarded discovery, collection, persistence, lifecycle, qualification, and matching pipeline; a second scan cannot overlap a running scan. Scheduling stops when the application process stops.

AI matching is disabled by default, so the application still starts without credentials. To configure M15 matching, set `JOB_AGENT_AI_PROVIDER` to `openai`, `anthropic`, or `gemini`, set `JOB_AGENT_AI_MODEL`, and provide only the corresponding API key in the local `.env`. Never commit that file. The scan pipeline and browser match views remain later modules.

To apply migrations without starting the web application:

```bash
alembic upgrade head
```

## M01 Focused Tests

```bash
pytest tests/module/test_m01_foundation.py
```

## M13 Focused Tests

```bash
pytest tests/module/test_m13_job_lifecycle.py
```

## M14 Focused Tests

```bash
pytest tests/module/test_m14_job_qualification.py
```

## M15 Focused Tests

```bash
pytest tests/module/test_m15_ai_matching.py
```

## M16 Focused Tests

```bash
pytest tests/module/test_m16_dashboard_filters.py
```

## M17 Focused Tests

```bash
pytest tests/module/test_m17_daily_action_queue.py
```

## M18 Focused Tests

```bash
pytest tests/module/test_m18_job_detail_state.py
```

## M19 Focused Tests

```bash
pytest tests/module/test_m19_scheduler_scan.py
```
