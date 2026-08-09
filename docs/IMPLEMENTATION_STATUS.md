# Job Agent V1 — Implementation Status

Last updated: 2026-08-09

## Current State

M01 Project Foundation and M02 Candidate Profiles are complete. M03 has not started.

The repository was fully inventoried before implementation. It initially contained only the frozen specification pack and a one-line root `README.md`; there was no prior application code, configuration, dependency manifest, migration, seed data, test suite, or runtime data to preserve.

All repository documents were read completely, including every required frozen document plus `07_PRIME_AGENT_USAGE.md`, `README_SPEC_PACK.md`, and the root `README.md`.

No contradictions were found among the frozen requirements. Implementation remains within their module order and scope.

## Architecture Plan

V1 will be a single-process, local-first Python monolith:

- FastAPI serves server-rendered Jinja2 pages and a small health endpoint.
- HTMX provides targeted page updates; Alpine.js will be omitted unless a concrete interaction cannot be handled cleanly with HTML/HTMX.
- SQLAlchemy 2.x and Alembic manage a single SQLite database configured for WAL mode, a busy timeout, short transactions, and one application instance.
- APScheduler runs in the FastAPI process. Manual and scheduled searches call the same scan pipeline and share one overlap guard.
- `httpx` handles bounded, timed external requests for search, ATS connectors, AI providers, and Telegram.
- Provider boundaries cover AI, web search, and job sources. These are in-process interfaces, not services or plugin infrastructure.
- Jobs are normalized before persistence, deduplicated in SQLite, lifecycle-managed after successful source scans, deterministically qualified, and AI-scored only when new or materially changed.
- The browser UI remains server-rendered, editorial, compact, accessible, and usable without external credentials.
- Runtime data stays local: SQLite plus controlled resume storage. Backup/restore uses one portable archive and excludes secrets.
- Future SaaS evolution is limited to clean provider, service, repository, settings, migration, and identifier boundaries. V1 adds no tenancy, authentication, billing, or distributed infrastructure.

Planned runtime flow:

`FastAPI startup -> configuration -> database/migrations -> scheduler -> manual or scheduled trigger -> overlap guard -> query generation -> company discovery -> ATS detection -> connectors -> normalization/deduplication -> lifecycle -> deterministic qualification -> AI matching -> action queue -> Telegram -> scan logs -> release guard`

## Proposed Folder Structure

Only the planning document is created in this pass. The following structure is proposed for module implementation:

```text
job-ai-agent/
├── README.md
├── pyproject.toml
├── .env.example
├── app/
│   ├── main.py
│   ├── config.py
│   ├── db.py
│   ├── models/
│   ├── schemas/
│   ├── repositories/
│   ├── services/
│   │   ├── discovery/
│   │   ├── matching/
│   │   └── notifications/
│   ├── providers/
│   │   ├── ai/
│   │   ├── search/
│   │   └── jobs/
│   ├── tasks/
│   └── web/
│       ├── routes/
│       ├── templates/
│       └── static/
├── data/
│   └── seeds/
│       └── companies.json
├── migrations/
├── scripts/
├── tests/
│   ├── module/
│   ├── final/
│   └── fixtures/
└── docs/
```

Directories will be introduced only when their owning module needs them. Package boundaries may be kept flatter where that reduces ceremony without mixing web, persistence, provider, and domain responsibilities.

## Proposed Dependency List

The planned direct dependencies are deliberately small. Transitive packages will not be promoted to direct dependencies unless application code imports them.

M01 added only `alembic`, `fastapi`, `jinja2`, `pydantic-settings`, `sqlalchemy`, and `uvicorn` as direct runtime dependencies. It added `httpx` and `pytest` in the optional test group. The other packages below remain approved plans for their owning future modules and have not been added as direct dependencies.

M02 added `pydantic` as a direct validation dependency and `python-multipart` for browser form parsing. Both were already explicitly approved by the frozen architecture and no other dependencies were added.

### Runtime

- `fastapi` — web application and routing
- `uvicorn` — ASGI server, without the optional `standard` bundle unless later proven necessary
- `jinja2` — server-rendered templates
- `python-multipart` — HTML forms and resume uploads
- `sqlalchemy` — ORM and persistence
- `alembic` — schema migrations
- `apscheduler` — in-process interval scheduling
- `httpx` — all outbound HTTP integrations and test client transport
- `beautifulsoup4` — bounded generic career-page parsing
- `pydantic` — validated application and provider schemas
- `pydantic-settings` — typed environment/runtime configuration
- `python-dotenv` — local `.env` loading for development
- `pypdf` — PDF resume text extraction
- `python-docx` — DOCX resume text extraction

Plain-text resumes will use the standard library. URL handling, hashing, retries, archives, file operations, and JSON use the standard library where practical. OpenAI, Anthropic, Gemini, Brave Search, and Telegram are planned as direct HTTP adapters through `httpx`, avoiding vendor SDK dependencies. The initial web-search adapter is planned for Brave Search; without a configured key, it reports `Not configured` while known company/ATS scans continue.

### Development/Test

- `pytest` — focused module tests and final verification
- `pytest-asyncio` — async pipeline/provider tests where required

### Browser Asset

- `HTMX` — one pinned, locally served browser asset; no Node/npm build chain

No coverage package or coverage target is planned. No linter, formatter, frontend build chain, JavaScript framework, task queue, browser automation, container stack, or database service will be added unless a frozen acceptance criterion later makes one unavoidable.

Compatible dependency bounds and a reproducible lock/resolution will be recorded in `pyproject.toml` during M01, after validating them against Python 3.12 on the development machine.

## Module Plan and Status

Modules will be implemented strictly in the frozen order. Each module receives the smallest useful focused tests for its acceptance criteria and directly affected behavior. The full workflow is reserved for M23.

| Module | Scope | Focused acceptance/test intent | Status |
|---|---|---|---|
| M01 Project Foundation | FastAPI, config, SQLite, migrations, templates, theme tokens, health endpoint, `.env.example` | Start command works; dashboard shell and health load; DB migrates; zero credentials required | Complete |
| M02 Candidate Profiles | Multiple profiles and approval-gated AI role/skill suggestions | Multiple profiles may be active; accepting/rejecting suggestions is explicit; pending suggestions never mutate profiles | Complete |
| M03 Resumes | Multiple local resumes per profile, safe TXT/PDF/DOCX extraction, primary selection | Extracted text is persisted and readable by matching; upload boundaries are enforced | Pending |
| M04 Company Registry + Seeds | Company/provider metadata and seed import | Seed load is idempotent and preserves scan metadata | Pending |
| M05 Query Generation + Web Discovery | Profile-derived queries, search abstraction, initial Brave Search adapter, persistent discoveries | Duplicate companies are avoided; discovery failure does not block known ATS scans | Pending |
| M06 ATS Detection | Detect supported ATS types and safely classify recognized/unsupported sources | Fixture URLs classify correctly; unsupported sources are recorded and skipped | Pending |
| M07 Greenhouse Connector | Fetch and normalize open Greenhouse jobs behind the connector contract | Deterministic fixtures validate mapping, pagination/error isolation as applicable | Pending |
| M08 Lever Connector | Fetch and normalize open Lever jobs behind the same contract | Deterministic fixtures validate mapping and isolated failures | Pending |
| M09 Ashby Connector | Fetch and normalize open Ashby jobs behind the same contract | Deterministic fixtures validate mapping and isolated failures | Pending |
| M10 Workday Connector | Pragmatic supported Workday collection behind the same contract | Deterministic fixtures validate the bounded implementation; unsupported variants fail safely | Pending |
| M11 Generic Career Page Fallback | Bounded best-effort HTML job extraction | Time, size, type, URL/domain, and link limits hold; unreliable pages become unsupported | Pending |
| M12 Normalization + Deduplication | Canonical job schema, URL/source/fingerprint identity, upsert | Rediscovery remains one row; changes update; `last_seen_at` refreshes | Pending |
| M13 Lifecycle | Missing counters and open/possibly-closed/closed transitions | One absence stays open; repeated confirmed absence transitions; reappearance resets; explicit closure closes | Pending |
| M14 Deterministic Qualification | Cheap exclusions and flexible experience/seniority/skill handling | Targeted cases reject only specified obvious mismatches and retain valid partial/senior matches | Pending |
| M15 AI Provider Layer + Matching | OpenAI/Anthropic/Gemini HTTP adapters, structured matching, suggestions, persistence | Malformed output cannot crash scans; unchanged jobs need not rescore; secrets/text boundaries are safe | Pending |
| M16 Dashboard + Filters | Paginated job views, required metrics, filters, score labels | Open 85+ jobs are quickly findable; applied/ignored and location filters work | Pending |
| M17 Daily Action Queue | Ranked configurable queue, default 10 | Only strongest open, relevant, unhandled jobs appear | Pending |
| M18 Job Detail + State | Reading-oriented detail, original URL, Save/Applied/Ignore, resume/note | State persists across rediscovery and applied metadata is retained | Pending |
| M19 Scheduler + Search Now | Configurable four-hour default, common pipeline, run visibility, overlap protection | Manual/scheduled paths match and concurrent scans are prevented | Pending |
| M20 Telegram | Three destination types and notification idempotency | Recommendation, application, and summary events route correctly without duplicates | Pending |
| M21 Logs / Scan Health | Run/source results, counts, failures, recent health | Successful, partial, and failed scans remain inspectable with bounded error details | Pending |
| M22 Backup / Restore | Portable archive for DB-backed state, settings, and resume files | Round trip restores required data while excluding secrets | Pending |
| M23 Final System Verification | Frozen 21-step end-to-end workflow after M01–M22 pass | Run full workflow, macOS/Linux setup verification, restart/persistence check, and defect-only fixes | Final Verification |

## M01 Completion Record

Completed: 2026-08-09

Implemented:

- Python 3.12+ package metadata with a small runtime and test dependency set.
- Typed environment configuration with safe local defaults and `.env.example`; no credentials are required or rendered.
- FastAPI application factory and documented Uvicorn start command.
- SQLite engine setup with WAL mode, a five-second busy timeout, foreign keys, short connection use, and automatic database-directory creation.
- Alembic configuration and an initial schema revision. The revision intentionally creates no M02 data tables; it establishes migration state only.
- Automatic migration and database readiness verification during application startup.
- `/health` endpoint reporting application/database readiness.
- Server-rendered Jinja2 dashboard shell with the exact primary navigation, compact status strip, semantic markup, keyboard focus treatment, responsive behavior, and zero-data empty state.
- A local, dependency-free stylesheet using semantic cream/red editorial tokens derived from the frozen reference direction. No external font, CSS, JavaScript, animation, SPA, or design-system dependency is used.
- Focused M01 tests for dashboard rendering without credentials, idempotent startup migration, health response, and required SQLite pragmas.
- README setup, single start command, migration behavior, health URL, and focused test command.

Files created:

- `.env.example`, `.gitignore`, `alembic.ini`, and `pyproject.toml`
- `app/__init__.py`, `app/config.py`, `app/db.py`, and `app/main.py`
- `app/web/__init__.py`, `app/web/routes.py`, two Jinja2 templates, and `app/web/static/styles.css`
- `migrations/env.py`, `migrations/script.py.mako`, and `migrations/versions/20260809_0001_foundation.py`
- `tests/module/test_m01_foundation.py`

Files changed:

- `README.md`
- `docs/IMPLEMENTATION_STATUS.md`

Focused verification evidence:

- Python version: `3.12.13`
- `python -m pytest tests/module/test_m01_foundation.py` -> 3 passed
- Documented Uvicorn start command -> application startup completed and Alembic applied `20260809_0001`
- `GET /health` -> HTTP 200 with `{"status":"ok","database":"ok"}`
- `GET /` -> HTTP 200 with the dashboard shell and local stylesheet reference
- `GET /static/styles.css` -> HTTP 200, `text/css`
- Standalone `alembic upgrade head` against a temporary configured database -> `20260809_0001`
- `python -m pip check` -> no broken requirements
- `python -m compileall -q app migrations tests/module` -> passed
- `git diff --check` -> passed

Acceptance result: all M01 acceptance criteria pass. The application has one documented start command, the dashboard shell loads, SQLite is created and migrated, the health and local UI assets load, and startup requires no external credentials.

Issues discovered:

- The normal browser fetch could not access the visual-reference host, but a bounded direct HTTPS fetch succeeded and exposed its layout and palette. The implementation uses only its broad visual language, not its branding, content, remote fonts, or source CSS.
- The initially resolved Starlette test wrapper warned that its synchronous `TestClient` path is deprecated. Focused tests now use `httpx.ASGITransport` directly, removing the warning without another dependency.
- No unresolved M01 blocker or failure remains.

## M02 Completion Record

Completed: 2026-08-09

Implemented:

- `candidate_profiles` persistence for name, active state, target roles, role synonyms, skills, years of experience, preferred locations, work modes, minimum salary/currency, excluded keywords, notes, and timestamps.
- `profile_suggestions` persistence for role/skill suggestions, rationale, pending/accepted/rejected status, and creation time.
- Multiple simultaneously active profiles with no singleton or uniqueness restriction on active state.
- Pydantic validation and bounded normalization for profile form values while preserving ordered, case-insensitive unique lists.
- A small SQLAlchemy repository/service boundary for profile creation, editing, listing, and suggestion decisions.
- Atomic suggestion decisions: recording or rejecting a suggestion never changes a profile; accepting a pending skill or role suggestion adds only that approved value; decided suggestions cannot be applied again.
- Server-rendered profile list, new-profile, and edit-profile pages integrated into the existing editorial navigation/theme.
- Explicit Accept and Reject actions for stored AI suggestions. Suggestion generation remains deferred to M15.
- Default target roles and role synonyms from the frozen product scope in the new-profile form.
- Alembic revision `20260809_0002` for only the two M02 tables and their small supporting indexes/constraints. No resume or M03 table was created.

Files created:

- `app/models/base.py`, `app/models/profiles.py`, and `app/models/__init__.py`
- `app/schemas/profiles.py` and `app/schemas/__init__.py`
- `app/repositories/profiles.py` and `app/repositories/__init__.py`
- `app/services/profiles.py` and `app/services/__init__.py`
- `app/web/dependencies.py`, `app/web/profiles.py`, `app/web/templates/profiles.html`, and `app/web/templates/profile_form.html`
- `migrations/versions/20260809_0002_candidate_profiles.py`
- `tests/module/test_m02_profiles.py`

Files changed:

- `pyproject.toml`, `app/db.py`, `app/main.py`, and `migrations/env.py`
- `app/web/routes.py`, `app/web/templates/base.html`, and `app/web/static/styles.css`
- `README.md` and `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: `pydantic` and `python-multipart`
- Test: none; M02 reuses the existing `pytest` and `httpx` test dependencies

Focused verification evidence:

- Python version: `3.12.13`
- `python -m pytest tests/module/test_m02_profiles.py` -> 3 passed
- Multiple-profile browser workflow -> two profiles remained active and every frozen profile field persisted
- Profile edit workflow -> fields and active state persisted
- Suggestion workflow -> pending profile unchanged, accepted skill added, rejected role not added, statuses persisted, repeated decision returned HTTP 409
- `alembic upgrade head` against a temporary database -> `20260809_0002 (head)`
- `alembic check` against the migrated database -> no new upgrade operations detected
- Migrated tables -> `alembic_version`, `candidate_profiles`, and `profile_suggestions` only
- `python -m pip check` -> no broken requirements
- `python -m compileall -q app migrations tests/module/test_m02_profiles.py` -> passed
- `git diff --check` -> passed

Acceptance result: all M02 acceptance criteria pass. Multiple profiles can coexist and remain active. AI suggestions are persisted as pending without mutating profile roles or skills, rejection leaves the profile unchanged, and only explicit acceptance updates the relevant profile field.

Issues discovered:

- No M02 test or migration failures remain.
- Browser form parsing required the explicitly approved lightweight `python-multipart` dependency; no other new runtime infrastructure was needed.
- AI suggestion generation is intentionally absent until M15; M02 provides only persistence and approval/rejection behavior.

## Execution Rules

For M01 through M22:

1. Inspect the current implementation and restate the smallest module scope.
2. Implement only that module and direct prerequisites already assigned to it.
3. Run only its smallest valuable tests and tests for directly affected behavior.
4. Fix module defects and verify the frozen acceptance criteria.
5. Update this status document with evidence and any decisions.
6. Make a small module-aligned commit when appropriate.
7. Continue to the next module unless a genuine blocker requires user input.

M23 begins only after M01–M22 focused tests pass. It may fix defects against frozen scope but may not introduce new functionality.

## Blockers and Deferred External Configuration

There are no genuine blockers to starting M03 when explicitly requested.

Live AI scoring, web company discovery, and Telegram delivery will eventually require user-supplied credentials or destination identifiers. These are not implementation blockers: the application must start and expose configured/not-configured states with zero credentials, provider behavior will be tested with deterministic fakes/fixtures, and known ATS sources must remain scannable when web search is unavailable.

The visual reference was inspected during M01 through a bounded direct fetch after the normal browser fetch failed.

## Next Action

Stop after M02. Do not begin M03 until explicitly requested.
