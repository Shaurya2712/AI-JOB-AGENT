# Job Agent

Job Agent V1 is a lightweight, local-first job-hunting dashboard. The current implementation contains the M01 project foundation only.

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

To apply migrations without starting the web application:

```bash
alembic upgrade head
```

## M01 Focused Tests

```bash
pytest tests/module/test_m01_foundation.py
```
