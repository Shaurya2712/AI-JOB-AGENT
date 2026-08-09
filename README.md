# Job Agent

Job Agent V1 is a lightweight, local-first job-hunting dashboard. The current implementation contains M01 Project Foundation through M13 Lifecycle.

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

The local company registry is available at <http://127.0.0.1:8000/companies>. The bundled company seed file is imported idempotently at startup. Discovery, ATS detection, supported job-source connectors, normalization/deduplication, and lifecycle handling are implemented as application services; scan orchestration and browser job views remain later modules.

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
