# Technical Architecture

## Goal
A small maintainable monolith that runs comfortably on an 8 GB Linux laptop.

## Recommended Stack
- Python 3.12+
- FastAPI
- Jinja2
- HTMX
- Alpine.js only if truly needed
- reference-inspired semantic CSS tokens derived from `05_UI_UX_REFERENCE_THEME.md`
- SQLite
- SQLAlchemy 2.x
- Alembic
- APScheduler in-process
- httpx
- BeautifulSoup or selectolax
- Pydantic
- Telegram Bot API via HTTP

## AI
Create AIProvider interface with adapters such as OpenAI, Anthropic, Gemini. Provider/model selected via settings/environment. Use structured Pydantic schemas.

## Web Search
Create WebSearchProvider interface. Implement one reliable provider first. Other providers remain adapters. The app must still scan known ATS/company sources if web discovery is disabled or temporarily fails.

## SQLite
Use WAL mode, sensible busy timeout, short transactions, one app instance in V1.

## Scheduler
One in-process APScheduler instance. Prevent overlapping discovery runs. Default 4h and configurable. Search Now uses the same pipeline.

## HTTP Rules
Bounded connection pools, timeouts, safe retries, per-source concurrency limits.

## Suggested Layout
```text
job-agent/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── .env.example
├── migrations/
├── data/seeds/companies.json
├── app/
│   ├── main.py
│   ├── config.py
│   ├── db.py
│   ├── models/
│   ├── schemas/
│   ├── repositories/
│   ├── services/
│   ├── providers/
│   │   ├── ai/
│   │   ├── search/
│   │   └── jobs/
│   ├── web/routes/
│   ├── web/templates/
│   ├── web/static/
│   └── tasks/
├── tests/module/
├── tests/final/
└── scripts/
```
Codex may simplify the folder structure if boundaries remain clear.

## Runtime Flow
Application -> DB/migrations -> scheduler -> manual/scheduled scan -> scan lock -> query generation -> company discovery -> ATS detection -> connectors -> normalize -> dedupe/upsert -> lifecycle -> deterministic qualification -> AI score new/changed jobs -> queue -> Telegram -> scan logs -> release lock.

## Resource Constraints
- no local LLM
- no persistent headless browser
- bounded HTTP and AI concurrency
- pagination
- batch processing
- indexed SQLite columns
- score only new/materially changed jobs
- avoid holding large job datasets in memory
- avoid extra background services

## Future SaaS Compatibility
Allow future evolution through provider interfaces, service/repository boundaries, migrations, IDs, and settings abstraction only. Do not add tenant/auth/billing systems now.
