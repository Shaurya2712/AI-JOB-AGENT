# Job Agent V1 — Implementation Status

Last updated: 2026-08-09

## Current State

M01 Project Foundation through M20 Telegram are complete. M21 has not started.

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

M03 added `pypdf` and `python-docx` for bounded text extraction from the approved resume formats. No other direct dependency was added.

M04 added no dependency; seed loading and URL normalization use the standard library with existing Pydantic/SQLAlchemy validation and persistence.

M05 promoted the already-approved and already-installed `httpx` package from test-only to a direct runtime dependency because the Brave Search adapter imports it for outbound HTTP. No new package was installed.

M06 added no dependency; ATS detection uses deterministic standard-library URL parsing and the existing SQLAlchemy company registry.

M07 added no dependency; the connector reuses the architecture-approved runtime `httpx` and Pydantic packages, with standard-library HTML-to-text handling.

M08 added no dependency; the Lever adapter reuses the M07 connector contract, bounded HTTP configuration, and collection runner.

M09 added no dependency; the Ashby adapter reuses the same connector contract, HTTP settings, and isolated collection runner.

M10 added no dependency; the Workday adapter reuses the existing `httpx`, Pydantic, connector contract, bounded HTTP settings, and collection runner.

M11 added `beautifulsoup4` as the architecture-approved direct runtime HTML parser. It uses the standard-library `html.parser` backend and adds no compiled parser, browser, or JavaScript runtime.

M12 added no dependency; canonicalization, hashing, validation, and transactional persistence use the standard library plus the existing SQLAlchemy/Alembic stack.

M13 added no dependency; lifecycle reconciliation uses the existing job model, SQLAlchemy session/repository boundary, and typed settings.

M14 added no dependency; deterministic qualification uses immutable standard-library results and the existing profile/job models.

M15 added no dependency; the three AI adapters reuse the architecture-approved `httpx` and Pydantic packages already installed as direct runtime dependencies.

M16 added no dependency; dashboard queries, pagination, filtering, and the frozen user-state table use the existing FastAPI, Jinja2, SQLAlchemy, and Alembic stack.

M17 added no dependency; the queue uses the existing typed settings, SQLAlchemy dashboard query, and server-rendered Jinja2 UI.

M18 added no dependency and no migration; job details and state mutations use the existing FastAPI/Jinja2/SQLAlchemy stack and the frozen `job_user_state` schema introduced for M16 filtering.

M19 added the architecture-approved `apscheduler` 3.x runtime dependency for one in-process asyncio scheduler. The installed direct version is `3.11.3`; its only newly installed transitive dependency is `tzlocal==5.4.4`.

M20 added no dependency; Telegram delivery reuses the architecture-approved `httpx` runtime client, while destination and idempotency persistence reuse SQLAlchemy/Alembic.

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
| M03 Resumes | Multiple local resumes per profile, safe TXT/PDF/DOCX extraction, primary selection | Extracted text is persisted and readable by matching; upload boundaries are enforced | Complete |
| M04 Company Registry + Seeds | Company/provider metadata and seed import | Seed load is idempotent and preserves scan metadata | Complete |
| M05 Query Generation + Web Discovery | Profile-derived queries, search abstraction, initial Brave Search adapter, persistent discoveries | Duplicate companies are avoided; discovery failure does not block known ATS scans | Complete |
| M06 ATS Detection | Detect supported ATS types and safely classify recognized/unsupported sources | Fixture URLs classify correctly; unsupported sources are recorded and skipped | Complete |
| M07 Greenhouse Connector | Fetch and normalize open Greenhouse jobs behind the connector contract | Deterministic fixtures validate mapping, pagination/error isolation as applicable | Complete |
| M08 Lever Connector | Fetch and normalize open Lever jobs behind the same contract | Deterministic fixtures validate mapping and isolated failures | Complete |
| M09 Ashby Connector | Fetch and normalize open Ashby jobs behind the same contract | Deterministic fixtures validate mapping and isolated failures | Complete |
| M10 Workday Connector | Pragmatic supported Workday collection behind the same contract | Deterministic fixtures validate the bounded implementation; unsupported variants fail safely | Complete |
| M11 Generic Career Page Fallback | Bounded best-effort HTML job extraction | Time, size, type, URL/domain, and link limits hold; unreliable pages become unsupported | Complete |
| M12 Normalization + Deduplication | Canonical job schema, URL/source/fingerprint identity, upsert | Rediscovery remains one row; changes update; `last_seen_at` refreshes | Complete |
| M13 Lifecycle | Missing counters and open/possibly-closed/closed transitions | One absence stays open; repeated confirmed absence transitions; reappearance resets; explicit closure closes | Complete |
| M14 Deterministic Qualification | Cheap exclusions and flexible experience/seniority/skill handling | Targeted cases reject only specified obvious mismatches and retain valid partial/senior matches | Complete |
| M15 AI Provider Layer + Matching | OpenAI/Anthropic/Gemini HTTP adapters, structured matching, suggestions, persistence | Malformed output cannot crash scans; unchanged jobs need not rescore; secrets/text boundaries are safe | Complete |
| M16 Dashboard + Filters | Paginated job views, required metrics, filters, score labels | Open 85+ jobs are quickly findable; applied/ignored and location filters work | Complete |
| M17 Daily Action Queue | Ranked configurable queue, default 10 | Only strongest open, relevant, unhandled jobs appear | Complete |
| M18 Job Detail + State | Reading-oriented detail, original URL, Save/Applied/Ignore, resume/note | State persists across rediscovery and applied metadata is retained | Complete |
| M19 Scheduler + Search Now | Configurable four-hour default, common pipeline, run visibility, overlap protection | Manual/scheduled paths match and concurrent scans are prevented | Complete |
| M20 Telegram | Three destination types and notification idempotency | Recommendation, application, and summary events route correctly without duplicates | Complete |
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

## M03 Completion Record

Completed: 2026-08-09

Implemented:

- Multiple resume records per candidate profile with display name, controlled storage reference, extracted text, primary state, and timestamps.
- Local TXT, PDF, and DOCX upload and text extraction. DOCX extraction includes paragraph and table text.
- A configurable 5 MiB default upload limit, generated UUID storage names, a configured storage root, and no file execution or public file-serving route.
- Bounded PDF parsing with signature validation, encrypted-file rejection, and a 100-page maximum.
- Bounded DOCX parsing with archive validation, a 500-entry maximum, and a 25 MiB decompressed-size maximum.
- A one-million-character extracted-text limit before SQLite persistence.
- Safe first-upload primary behavior, optional primary selection during upload, later explicit primary switching, and a database partial unique index enforcing at most one primary resume per profile.
- A resume service method that returns persisted extracted text by profile/resume identity for the future matching module.
- Resume upload, list, extracted-character count, primary badge, and Make Primary controls within the existing Profiles page.
- Alembic revision `20260809_0003` for the M03 `resumes` table only. No company or M04 table was created.

Files created:

- `app/models/resumes.py`
- `app/schemas/resumes.py`
- `app/repositories/resumes.py`
- `app/services/resume_files.py` and `app/services/resumes.py`
- `migrations/versions/20260809_0003_resumes.py`
- `tests/module/test_m03_resumes.py`

Files changed:

- `.env.example`, `.gitignore`, `pyproject.toml`, `app/config.py`, and `app/models/__init__.py`
- `app/models/profiles.py` and `app/repositories/profiles.py`
- `app/web/profiles.py`, `app/web/templates/profiles.html`, and `app/web/static/styles.css`
- `README.md` and `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: `pypdf` and `python-docx`
- Transitive through `python-docx`: `lxml`
- Test: none; deterministic TXT/PDF/DOCX fixtures use the existing runtime and test packages

Focused verification evidence:

- Python version: `3.12.13`
- `python -m pytest tests/module/test_m03_resumes.py` -> 2 passed
- Format workflow -> TXT, PDF, and DOCX uploads persisted separately and produced expected extracted text
- Primary workflow -> first upload became primary, ordinary later upload preserved it, requested/explicit changes left exactly one primary
- Matching-read workflow -> `ResumeService.get_extracted_text` returned the persisted resume text
- Storage-safety workflow -> path-like client filename became a generated basename inside the configured directory
- Rejection workflow -> unsupported and oversized uploads returned HTTP 422 with no row or stored file
- `alembic upgrade head` against a temporary database -> `20260809_0003 (head)`
- `alembic check` against the migrated database -> no new upgrade operations detected
- Migrated tables -> `alembic_version`, `candidate_profiles`, `profile_suggestions`, and `resumes` only
- `python -m pip check` -> no broken requirements
- `python -m compileall -q app migrations tests/module/test_m03_resumes.py` -> passed
- `git diff --check` -> passed

Acceptance result: all M03 acceptance criteria pass. Each profile can store multiple local resumes, TXT/PDF/DOCX text is extracted and persisted, one resume can be selected as primary, and the future matching layer can retrieve extracted text through the resume service.

Issues discovered:

- No M03 test, extraction, persistence, or migration failure remains.
- Final review found that re-selecting the already-primary resume could clear its database flag after the bulk reset. Primary assignment now uses an explicit database update, and the focused test covers repeated selection.
- DOCX support necessarily adds the `lxml` transitive dependency through `python-docx`; it is used only during bounded upload-time extraction and does not add a background process.
- Legacy `.doc`, image-only/OCR resumes, download/delete actions, and automatic submission are intentionally absent because they are not required by frozen M03 scope.

## M04 Completion Record

Completed: 2026-08-09

Implemented:

- Persistent `companies` registry with company/website/career URLs, provider type/identifier/support state, discovery source, active state, last scan, last successful scan, total jobs seen, and timestamps.
- A bundled six-company seed dataset focused on product companies with verified official career pages: BrowserStack, Chargebee, Freshworks, Meesho, Postman, and Razorpay.
- Bounded, validated JSON seed loading with normalized absolute HTTP(S) URLs and a one-MiB seed-file limit.
- Idempotent startup import keyed by normalized company website URL.
- Repeat imports preserve active state, detected provider values, scan timestamps, successful-scan timestamps, and job counts; seed data only fills missing career/provider values.
- A database uniqueness constraint preventing duplicate company website identities.
- Server-rendered Companies navigation and a compact registry table showing career page, provider, support status, last scan, job count, and health placeholder.
- Alembic revision `20260809_0004` for the M04 `companies` table only. No query-generation, discovery, or M05 persistence was added.

Files created:

- `app/models/companies.py`
- `app/schemas/companies.py`
- `app/repositories/companies.py`
- `app/services/companies.py`
- `app/web/companies.py` and `app/web/templates/companies.html`
- `data/seeds/companies.json`
- `migrations/versions/20260809_0004_companies.py`
- `tests/module/test_m04_companies.py`

Files changed:

- `.env.example`, `app/config.py`, `app/main.py`, and `app/models/__init__.py`
- `app/web/templates/base.html` and `app/web/static/styles.css`
- `README.md` and `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- Python version: `3.12.13`
- `python -m pytest tests/module/test_m04_companies.py` -> 2 passed
- Bundled-seed workflow -> six company rows loaded and rendered with all registry fields initialized
- Idempotency workflow -> repeated startup plus explicit re-import remained at two fixture rows with `created=0` and `existing=2`
- Metadata preservation -> provider type/identifier, scan timestamps, successful-scan timestamp, and total job count survived repeat imports
- `alembic upgrade head` against a temporary database -> `20260809_0004 (head)`
- `alembic check` against the migrated database -> no new upgrade operations detected
- Migrated tables -> `alembic_version`, `candidate_profiles`, `companies`, `profile_suggestions`, and `resumes` only
- `python -m pip check` -> no broken requirements
- `python -m compileall -q app migrations tests/module/test_m04_companies.py` -> passed
- `git diff --check` -> passed

Acceptance result: all M04 acceptance criteria pass. Company records contain the frozen registry and scan metadata fields, the bundled seed imports automatically, repeated loads do not create duplicates, and later operational metadata is preserved.

Issues discovered:

- No M04 seed, persistence, page, test, or migration failure remains.
- Seed ATS/provider values are intentionally unset even where a career page currently reveals a provider; provider detection belongs exclusively to M06.
- M04 performs no network request during startup or tests. Web search, automatic company discovery, and generated queries remain deferred to M05.

## M05 Completion Record

Completed: 2026-08-09

Implemented:

- Deterministic, case-insensitively deduplicated search-query generation from every active profile's target roles, role synonyms, preferred locations, and Remote work mode.
- A configurable per-run query cap with stable ordering so target roles are searched before synonyms and preferred locations before Remote.
- A small asynchronous web-search provider contract with explicit configured state and isolated provider errors.
- A working Brave Search HTTP adapter using the documented web endpoint, token header, query/country/language/count parameters, and structured response shape.
- Boundaries suitable for the target laptop: three concurrent requests by default (maximum five), ten results per query by default (maximum twenty), a 30-query default cap, bounded timeouts, a one-MiB response limit, and one retry only for transport failures or HTTP 5xx responses.
- Environment-only Brave credentials through Pydantic `SecretStr`; an empty key produces an unconfigured provider state and no credential is included in discovery results/errors.
- Defensive result validation, career-signal filtering, rejection of common job aggregators/social sources, removal of tracking parameters, and normalized company/career URL identities.
- Persistent web discoveries in the existing company registry with `web:<provider>` provenance and M06 provider fields deliberately left unset.
- Deduplication across repeated search results, `www` host variants, shared `jobs`/`boards` tenant paths, existing career URLs, existing registry domains, and subsequent discovery runs.
- Failure isolation that returns the existing company registry unchanged when the search provider is disabled, unconfigured, or fails. That returned registry is the downstream input for the future ATS scan stage.
- No discovery call at startup and no scheduler, Search Now route, ATS detection, connector, or new database table; those remain assigned to later modules.

Files created:

- `app/providers/__init__.py`
- `app/providers/search/__init__.py`, `app/providers/search/base.py`, `app/providers/search/brave.py`, and `app/providers/search/factory.py`
- `app/services/search_queries.py` and `app/services/web_discovery.py`
- `tests/module/test_m05_discovery.py`

Files changed:

- `.env.example`, `pyproject.toml`, and `app/config.py`
- `app/repositories/profiles.py`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: `httpx` moved from the optional test group to direct runtime dependencies; it was already approved by the architecture and installed for prior tests
- Test: none

Focused verification evidence:

- Python version: `3.12.13`
- `python -m pytest tests/module/test_m05_discovery.py` -> 4 passed
- Query workflow -> target roles, role synonyms, preferred locations, Remote mode, case-insensitive deduplication, active-profile filtering, deterministic ordering, and the run cap were exercised
- Discovery workflow -> duplicate results from multiple queries created two company rows once; a repeat run created zero additional rows; tracking parameters and a LinkedIn result were excluded
- Failure workflow -> a provider outage returned the seeded company registry as downstream scan input and did not raise out of discovery
- Brave adapter workflow -> deterministic mock transport verified the official endpoint, token header, country/language/count parameters, one safe HTTP 5xx retry, and structured result parsing without a live network call
- `python -m compileall -q app/providers app/services/search_queries.py app/services/web_discovery.py app/config.py app/repositories/profiles.py tests/module/test_m05_discovery.py` -> passed
- `python -m pip check` -> no broken requirements
- `git diff --check` -> passed

Acceptance result: all M05 acceptance criteria pass. Active profile data produces bounded web searches through an abstract provider, the Brave adapter is operational when configured, discovered company/career pages persist without duplicates, and provider failure leaves known registry companies available for later ATS scans.

Issues discovered:

- No M05 query-generation, provider, persistence, or failure-isolation failure remains.
- A live Brave credential was neither available nor required. The provider contract is verified through an exact deterministic HTTP transport, and an empty key remains a safe unconfigured state.
- Search results can point at shared career-host tenant paths instead of a corporate homepage. M05 stores a stable tenant URL identity without classifying its ATS; provider detection remains exclusively M06.
- Web discovery is callable but intentionally not scheduled or exposed through the UI. The shared manual/scheduled trigger belongs to M19.

## M06 Completion Record

Completed: 2026-08-09

Implemented:

- A deterministic, network-free ATS URL detector for Greenhouse, Lever, Ashby, and pragmatic Workday career-site URL shapes.
- Provider identifier extraction for hosted job boards and their public API URL forms, including Greenhouse embed URLs, Lever global/EU hosts, Ashby job-board URLs, and Workday tenant/site paths.
- Recognition of iCIMS and BambooHR as named unsupported ATS providers rather than misclassifying them as generic sources.
- Recognition of ordinary company-hosted career pages as `custom`, reserved for the M11 generic career-page fallback.
- Explicit `unknown` classification for missing, malformed, credential-bearing, or otherwise invalid source URLs.
- Connector readiness only when a supported provider has a bounded, valid provider identifier. Supported-provider URLs without an identifier are recorded but safely skipped.
- Persistent updates to the existing `provider_type`, `provider_identifier`, and `provider_supported` company fields, with no schema change.
- Reuse and normalization of explicit stored ATS metadata from seed/earlier detection when it contains a recognized provider and usable identifier.
- Active-company-only classification with an explicit decision for every checked company: connector-ready or skipped with a bounded reason.
- Idempotent reruns that preserve company scan timestamps, successful-scan timestamps, job counts, discovery source, and active state.
- No ATS HTTP requests, job fetching, connector contract, normalization, or Greenhouse connector behavior; M07 was not started.

Files created:

- `app/services/ats_detection.py`
- `tests/module/test_m06_ats_detection.py`

Files changed:

- `app/repositories/companies.py`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- Python version: `3.12.13`
- `python -m pytest tests/module/test_m06_ats_detection.py` -> 15 passed
- Supported fixture workflow -> Greenhouse, Lever, Ashby, and Workday hosted/API URL shapes produced the expected provider and board/tenant identifiers
- Unsupported fixture workflow -> iCIMS, BambooHR, custom, malformed, and identifier-less sources remained connector-ineligible with explicit skip reasons
- Registry workflow -> four active companies were classified, only two became connector-ready, two were safely skipped, and one inactive source was untouched
- Persistence workflow -> classifications survived a repeated run while existing scan timestamps and job counts remained unchanged
- `python -m compileall -q app/services/ats_detection.py app/repositories/companies.py tests/module/test_m06_ats_detection.py` -> passed
- `python -m pip check` -> no broken requirements
- `git diff --check` -> passed

Acceptance result: all M06 acceptance criteria pass. Deterministic fixture URLs classify into the required supported providers and recognized fallback/unsupported states, classifications persist in the company registry, and unsupported or unusable sources are returned as explicit skip decisions without raising or starting a connector.

Issues discovered:

- No M06 classification, persistence, or safe-skip failure remains.
- URL-only detection cannot see an ATS embedded behind an unrelated corporate career-page URL. Such pages are intentionally recorded as `custom` for the bounded M11 fallback rather than fetched or guessed in M06.
- Workday detection is deliberately limited to identifiable `myworkdayjobs.com` tenant/site URLs. Universal Workday discovery and collection are outside M06 and explicitly prohibited by the frozen M10 scope.
- Explicit stored ATS metadata with a recognized provider and usable identifier is treated as authoritative, preserving the M04 seed/import boundary.

## M07 Completion Record

Completed: 2026-08-09

Implemented:

- A minimal asynchronous `JobConnector` boundary and immutable provider-neutral `ConnectorJob` result containing source identity, title, location text, plain description, and public job URL.
- A Greenhouse connector using the public Job Board API list endpoint with the detected board token and `content=true` for full descriptions.
- Mapping of Greenhouse job IDs, titles, locations, descriptions, and absolute job URLs into the shared connector result contract.
- Standard-library HTML/entity decoding into bounded plain text without introducing the M11 generic HTML parsing dependency or logic.
- Exclusion of Greenhouse prospect/general-application posts identified by a null `internal_job_id`, while retaining all actual job posts returned by the board endpoint.
- Strict board-token and returned job URL validation, structured Pydantic response validation, a 5,000-job response-list bound, and a configurable eight-MiB default response limit.
- Configurable job-source timeout and concurrency with a maximum of five requests, a bounded HTTP connection pool, disabled redirects, and one retry only for transport failures or HTTP 5xx responses.
- A small collection service that selects only active, connector-ready companies for the connector's provider and isolates each company result as success or failure.
- Bounded connector error text and generic handling for unexpected adapter failures, so one failed Greenhouse board cannot discard successful results from other boards.
- No job table, persistence, canonical normalization, deduplication, lifecycle handling, scan log, scheduler, or Lever connector; M08 was not started.

Files created:

- `app/providers/jobs/__init__.py`, `app/providers/jobs/base.py`, `app/providers/jobs/greenhouse.py`, and `app/providers/jobs/factory.py`
- `app/services/job_collection.py`
- `tests/module/test_m07_greenhouse.py`

Files changed:

- `.env.example` and `app/config.py`
- `app/repositories/companies.py`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none; M07 reuses existing direct `httpx` and Pydantic dependencies
- Test: none

Focused verification evidence:

- Python version: `3.12.13`
- `python -m pytest tests/module/test_m07_greenhouse.py` -> 3 passed
- Mapping workflow -> two actual fixture jobs mapped to the connector contract with normalized whitespace and plain descriptions; one null-`internal_job_id` prospect post was excluded
- Request workflow -> the public board endpoint, board identifier, `content=true`, JSON accept header, absence of authorization, and one safe HTTP 5xx retry were verified through deterministic mock transport
- Validation workflow -> a path-like board identifier made no request, and malformed Greenhouse JSON raised a controlled connector error
- Isolation workflow -> one failed board and one successful board produced independent results; unsupported Greenhouse and non-Greenhouse companies were not collected
- `python -m compileall -q app/providers/jobs app/services/job_collection.py app/config.py app/repositories/companies.py tests/module/test_m07_greenhouse.py` -> passed
- `python -m pip check` -> no broken requirements
- `git diff --check` -> passed

Acceptance result: all M07 scope and acceptance requirements pass. Greenhouse open jobs are fetched through the public structured endpoint, mapped into the connector contract, and returned per company; malformed responses and failed boards are isolated without preventing other Greenhouse boards from succeeding.

Issues discovered:

- No M07 request, mapping, validation, or source-isolation failure remains.
- Greenhouse documents the list-jobs endpoint as returning all job posts and does not define pagination for that endpoint, so M07 performs one bounded request per board rather than inventing pagination parameters.
- Greenhouse exposes `updated_at`, not a reliable original posting date. M07 does not mislabel it as `posted_at`; later normalization will leave posting time unknown unless a source provides it explicitly.
- Live Greenhouse sites were not called. The public contract and response behavior are verified with deterministic local transport fixtures.

## M08 Completion Record

Completed: 2026-08-09

Implemented:

- A Lever adapter implementing the existing M07 `JobConnector` boundary without changing or widening the connector result contract.
- Public Postings API requests using JSON mode, the detected Lever site identifier, and the documented `skip`/`limit` pagination parameters.
- Mapping of Lever posting IDs, names, primary locations, plaintext combined descriptions, and hosted job URLs into `ConnectorJob`.
- Stable whitespace normalization while retaining description paragraph boundaries supplied by `descriptionPlain`.
- Bounded pagination in 100-posting pages, including a terminating short/empty page, a 5,000-posting source maximum, and an eight-MiB cumulative response limit inherited from M07 configuration.
- Global Lever API lookup first with a first-page 404 fallback to the documented EU API host, allowing the M06 site identifier to work for both regions without a schema change.
- Identifier, job URL, JSON content type, response shape, field size, page size, and response byte validation.
- The existing bounded connection pool, timeout, disabled redirects, and one safe retry for transport/HTTP 5xx failures.
- Per-company error isolation through the existing collection runner, selecting only active, connector-ready Lever companies and preserving successful results when another site fails.
- No job persistence, canonical normalization, deduplication, lifecycle handling, Ashby adapter, or M09 behavior.

Files created:

- `app/providers/jobs/lever.py`
- `tests/module/test_m08_lever.py`

Files changed:

- `app/providers/jobs/__init__.py`
- `app/providers/jobs/factory.py`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- Python version: `3.12.13`
- `python -m pytest tests/module/test_m08_lever.py` -> 4 passed
- Mapping workflow -> fixture postings mapped IDs, titles, locations, plaintext descriptions, and hosted URLs into the unchanged connector contract
- Request workflow -> JSON mode, 100-item limit, skip offset, JSON accept header, absence of authorization, and one safe HTTP 5xx retry were verified with deterministic mock transport
- Pagination/region workflow -> a global first-page 404 switched to the EU host; a full first page and short second page returned 101 postings in order
- Validation workflow -> a path-like site identifier made no request, and a non-list JSON response raised a controlled connector error
- Isolation workflow -> one failed Lever site and one successful site produced independent results; unsupported Lever and Greenhouse companies were not collected
- `python -m compileall -q app/providers/jobs app/services/job_collection.py tests/module/test_m08_lever.py` -> passed
- `python -m pip check` -> no broken requirements
- `git diff --check` -> passed

Acceptance result: all M08 scope and acceptance requirements pass. Published Lever postings are fetched across bounded pages, mapped into the same connector contract as Greenhouse, and isolated per company so one Lever source failure does not prevent other sources from succeeding.

Issues discovered:

- No M08 request, pagination, mapping, validation, regional fallback, or source-isolation failure remains.
- Lever documents the public endpoint as exposing published postings only, so M08 does not invent a separate open-status filter.
- The public Lever result does not provide a reliable original posting timestamp in its documented fields; M08 leaves that concern to later normalization rather than fabricating one.
- Live Lever sites were not called. Deterministic local transports verified global/EU requests, pagination, and response parsing.

## M09 Completion Record

Completed: 2026-08-09

Implemented:

- An Ashby adapter implementing the unchanged M07 `JobConnector` and `ConnectorJob` boundary.
- A public job-board request using the detected Ashby board name and `includeCompensation=false` to avoid collecting unused payload.
- Mapping of Ashby titles, primary locations, plaintext descriptions, hosted job URLs, and stable source IDs derived from the hosted URL's terminal path segment.
- Stable whitespace normalization while retaining description paragraph boundaries supplied by `descriptionPlain`.
- Filtering of `isListed=false` direct-link-only posts while retaining listed postings returned by the public published-post feed.
- Board identifier, hosted URL, derived source ID, JSON content type, response shape, field size, 5,000-job list, and response byte validation.
- One bounded request per board because Ashby's public job-board API documents a complete published-post list and exposes no pagination parameters.
- Reuse of the existing timeout, connection-pool/concurrency limits, disabled redirects, eight-MiB response limit, and one safe retry for transport/HTTP 5xx failures.
- Per-company error isolation through the existing collection runner, selecting only active, connector-ready Ashby companies and retaining successes when another Ashby board fails.
- No persistence, canonical normalization, deduplication, lifecycle handling, Workday adapter, or M10 behavior.

Files created:

- `app/providers/jobs/ashby.py`
- `tests/module/test_m09_ashby.py`

Files changed:

- `app/providers/jobs/__init__.py`
- `app/providers/jobs/factory.py`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- Python version: `3.12.13`
- `python -m pytest tests/module/test_m09_ashby.py` -> 3 passed
- Mapping workflow -> two listed fixture jobs mapped titles, locations, plaintext descriptions, hosted URLs, and URL-derived source IDs into the unchanged connector contract
- Visibility workflow -> one `isListed=false` direct-link-only fixture was excluded
- Request workflow -> board name, `includeCompensation=false`, JSON accept header, absence of authorization, and one safe HTTP 5xx retry were verified through deterministic mock transport
- Validation workflow -> a path-like board identifier made no request, and a structurally incomplete Ashby response raised a controlled connector error
- Isolation workflow -> one failed Ashby board and one successful board produced independent results; unsupported Ashby and Lever companies were not collected
- `python -m compileall -q app/providers/jobs app/services/job_collection.py tests/module/test_m09_ashby.py` -> passed
- `python -m pip check` -> no broken requirements
- `git diff --check` -> passed

Acceptance result: all M09 scope and acceptance requirements pass. Listed Ashby postings are fetched from the public structured feed, mapped into the same connector contract as Greenhouse and Lever, and isolated per company so one Ashby source failure cannot prevent other boards from succeeding.

Issues discovered:

- No M09 request, mapping, validation, visibility-filter, or source-isolation failure remains.
- Ashby's documented public posting object does not expose a separate job ID field. M09 derives the required stable source identity from the hosted `jobUrl` path and rejects unusable URLs rather than inventing a mutable title-based identity.
- Ashby documents one complete published-post response and no pagination parameters, so M09 performs one bounded request rather than inventing pagination.
- Live Ashby boards were not called. Deterministic local transport verifies request and response behavior.

## M10 Completion Record

Completed: 2026-08-09

Implemented:

- A pragmatic Workday adapter implementing the unchanged M07 `JobConnector` and `ConnectorJob` boundary.
- A precise Workday provider identifier containing the detected `myworkdayjobs.com` shard hostname, tenant, and external career-site name; M06 detection now retains the hostname required to reach the correct public site without shard guessing.
- Public CXS listing requests using the empty search/facet payload and fixed 20-job pagination, followed by public detail requests for each listed job so the connector returns the full job description required by the shared contract.
- Mapping of Workday opaque posting IDs, titles, locations, HTML descriptions converted to plain text, and constructed public hosted URLs into `ConnectorJob`.
- Filtering of detail responses that are no longer posted or cannot be applied to, covering listing/detail races without presenting them as open jobs.
- Exact `*.wdN.myworkdayjobs.com` host validation, single-segment tenant/site validation, same-host job-detail construction, and strict `/job/` path validation; legacy hostname-free identifiers are refreshed from their stored career URL during ATS classification and fail before a request when passed directly to the connector.
- A 5,000-job source maximum, 20-job page bound, cumulative configured response-byte budget, configured timeout, bounded shared request semaphore/connection pool with a maximum of five, disabled redirects, and one safe retry for transport/HTTP 5xx failures.
- Structured Pydantic validation for listing and detail responses, bounded fields, controlled failures for premature pagination and unsupported response/path shapes, and standard-library HTML text extraction with no M11 generic-page crawling.
- Per-company error isolation through the existing collection runner, selecting only active, connector-ready Workday companies and retaining successes when another Workday source fails.
- No generic career-page parsing, discovery heuristics, shard probing, browser automation, job persistence, canonical normalization, deduplication, or lifecycle behavior; M11 was not started.

Files created:

- `app/providers/jobs/workday.py`
- `tests/module/test_m10_workday.py`

Files changed:

- `app/providers/jobs/__init__.py`
- `app/providers/jobs/factory.py`
- `app/services/ats_detection.py`
- `tests/module/test_m06_ats_detection.py` (expected Workday identifiers only, reflecting the exact-host prerequisite)
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- Python version: `3.12.13`
- `.venv/bin/python -m pytest tests/module/test_m10_workday.py` -> 5 passed
- Request workflow -> deterministic transport verified the exact CXS host/tenant/site URL, empty search/facet payload, 20-item offsets, JSON headers, absence of authorization, detail requests, and one safe HTTP 5xx retry
- Pagination/mapping workflow -> a full first page and one-item second page were collected; open details mapped opaque IDs, normalized titles/locations, plain descriptions, and hosted URLs into the unchanged connector contract
- Open-state workflow -> a fixture posting that became non-posted/non-applicable between listing and detail was excluded
- Validation workflow -> hostname-free and non-Workday identifiers made no request, and an absolute cross-host detail path raised a controlled unsupported-variant error
- Detection workflow -> a hosted Workday career URL retained the exact shard hostname, tenant, and site required by the connector; a previously stored hostname-free M06 identifier was refreshed from its career URL without a migration
- Isolation workflow -> one failed Workday source and one successful source produced independent results; unsupported Workday and Ashby companies were not collected
- `.venv/bin/python -m compileall -q app/providers/jobs/workday.py app/providers/jobs/factory.py app/providers/jobs/__init__.py app/services/ats_detection.py tests/module/test_m10_workday.py` -> passed
- `.venv/bin/python -m pip check` -> no broken requirements
- `git diff --check` -> passed

Acceptance result: all M10 scope and acceptance requirements pass. Supported public Workday career sites are collected through bounded listing and detail requests, open jobs are mapped into the same connector contract as Greenhouse, Lever, and Ashby, unsupported variants fail safely, and one Workday source failure cannot prevent another source from succeeding.

Issues discovered:

- No M10 request, pagination, mapping, validation, open-state, or source-isolation failure remains.
- The M06 `tenant/site` identifier omitted the Workday deployment shard and could not identify a resolvable public endpoint. M10 refined only Workday identifiers to `hostname/tenant/site`; existing hostname-free values refresh on ATS classification and no database migration is needed because the field remains within its existing 255-character schema.
- Workday documents external career-site listing/detail behavior but does not publish the CXS transport as a stable general-purpose public API. M10 therefore supports only the observed, narrowly validated public career-site shape and does not probe shards, discover alternate transports, or reverse engineer customer-specific variants.
- Workday allows customers to exclude career sites from third-party indexing. Access-disabled sites and HTTP errors are reported as isolated source failures; M10 does not bypass the restriction or fall back to browser automation.
- Complete descriptions require one bounded detail request per listed job. Requests share the configured maximum-five connection limit and cumulative response budget to remain suitable for the target Linux laptop.
- The M10 tests use deterministic local HTTP fixtures. One bounded read-only inspection of Workday's own public career site was used during implementation to confirm the current listing and detail field shapes; it was not part of the test command.

## M11 Completion Record

Completed: 2026-08-09

Implemented:

- A `GenericCareerPageConnector` implementing the existing `JobConnector` and `ConnectorJob` boundary with source type `custom`.
- One public career-index request followed by detail requests for at most 50 high-confidence job links; detail pages are never recrawled for more links.
- Conservative link recognition using explicit job/position/opening/vacancy path shapes or known job-ID query keys, meaningful anchor text, fragment removal, and stable first-seen URL deduplication.
- Same-host job links plus a narrow allowlist for the already-supported public Greenhouse, Lever, Ashby, and Workday career hosts; arbitrary cross-domain and non-public literal links are skipped.
- Public HTTP(S) URL validation covering credentials, ports, hostname shape, local/internal names, private/reserved literal IP addresses, fragments, and a 4,000-character URL maximum.
- Structured detail extraction from explicit description elements or bounded `main`/`article` fallbacks, with script/style/template/SVG removal, a reliable title requirement, optional bounded location text, and a minimum useful description length.
- Stable generic source IDs derived from the fragment-free public detail URL without introducing M12 canonical normalization or persistence.
- Strict HTML/XHTML content-type checks, per-response and cumulative response-byte limits, a 50-link cap, configured timeout, disabled redirects, a shared maximum-five request semaphore/connection pool, and one retry only for transport/HTTP 5xx failures.
- Early cumulative-budget exhaustion so queued details do not continue requesting after the source byte allowance is spent.
- An explicit `UnsupportedCareerPageError` for invalid URLs, pages without reliable job links, and sources where every candidate detail is unreliable; individual unusable details are skipped when other reliable jobs remain.
- Collection of active M06 `custom` companies by their full careers URL while leaving structured connector selection unchanged; generic source failures remain isolated per company.
- No recursive crawler, headless browser, JavaScript execution, redirect following, authentication, CAPTCHA/access-control bypass, job persistence, canonical normalization, deduplication, or lifecycle functionality; M12 was not started.

Files created:

- `app/providers/jobs/generic.py`
- `tests/module/test_m11_generic_career_page.py`

Files changed:

- `app/providers/jobs/__init__.py`
- `app/providers/jobs/factory.py`
- `app/repositories/companies.py`
- `app/services/job_collection.py`
- `pyproject.toml`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: `beautifulsoup4>=4.15,<5` (installed version `4.15.0`; pure-Python `html.parser` backend)
- Transitive: `soupsieve==2.9.2`
- Test: none

Focused verification evidence:

- Python version: `3.12.13`
- `.venv/bin/python -m pytest tests/module/test_m11_generic_career_page.py` -> 4 passed
- Mapping workflow -> a reliable same-host detail mapped a URL-derived source ID, normalized title/location, plain description, and public URL into the unchanged connector contract while an unreliable sibling detail was skipped
- Request workflow -> fixture requests used only bounded GETs with HTML accept headers, no authorization, one safe HTTP 5xx retry, and no redirect or browser behavior
- URL/domain workflow -> a private literal URL made no request; arbitrary external and private links were ignored; duplicate fragments collapsed to one detail URL
- Type/size workflow -> non-HTML content, oversized single responses, and cumulative source-budget exhaustion raised controlled errors; queued requests stopped after cumulative exhaustion
- Link/crawl workflow -> only the first 50 high-confidence index links were fetched, and job links found inside details were never crawled
- Reliability workflow -> an index without reliable detail links became explicitly unsupported; partial detail failures retained reliable jobs
- Isolation workflow -> active custom companies were selected by full careers URL despite being structured-connector unsupported, one custom source failure did not discard another source's result, and inactive/non-custom companies were not selected
- `.venv/bin/python -m compileall -q app/providers/jobs/generic.py app/providers/jobs/factory.py app/providers/jobs/__init__.py app/repositories/companies.py app/services/job_collection.py tests/module/test_m11_generic_career_page.py` -> passed
- `.venv/bin/python -m pip check` -> no broken requirements
- `git diff --check` -> passed

Acceptance result: all M11 acceptance criteria pass. Public generic career pages are handled through a non-recursive, time/size/type/URL/domain/link-bounded HTML fallback; reliable job details map into the existing connector contract, unreliable sources become explicit unsupported errors, source failures are isolated, and no access-control bypass is attempted.

Issues discovered:

- No M11 request-boundary, link-cap, no-recursion, mapping, reliability, or source-isolation failure remains.
- Generic pages are intentionally heuristic. JavaScript-only listings, generic CTA-only links, pages without useful server-rendered detail text, unrecognized URL shapes, and arbitrary cross-domain job hosts are reported as unsupported rather than guessed or crawled broadly.
- M06 marks custom pages unsupported for structured connectors. M11 deliberately selects only active `custom` companies with a stored careers URL and passes that full URL to the fallback, without changing their structured-provider classification.
- Individual detail failures are skipped when at least one reliable job remains. If no reliable detail succeeds, the whole custom source is unsupported so an empty result cannot be mistaken for a confirmed zero-job scan.
- Generic source IDs are SHA-256 hashes of the bounded fragment-free detail URL. M12 remains responsible for canonical URL normalization, persistence, and cross-scan deduplication.
- DNS hostnames are syntactically validated and local/private literal addresses are rejected, but M11 does not add a DNS resolver or network service. Requests remain bounded to the configured client with redirects disabled.
- Live career pages were not called. All M11 request, parsing, failure, and security-boundary behavior is verified with deterministic local HTTP fixtures.

## M12 Completion Record

Completed: 2026-08-09

Implemented:

- A normalized `jobs` table and SQLAlchemy model covering the complete frozen job schema: company/source identity, canonical URL, display and normalized title, location breakdown fields, remote/employment types, description and hash, compensation, experience, skills, posting/discovery/last-seen timestamps, missing count, lifecycle state, optional source payload, and timestamps.
- Company-scoped unique constraints for connector source identity and canonical URL, plus indexed fallback signature, description hash, last-seen time, and company/lifecycle lookup paths.
- Database defaults and checks for an initial `open` lifecycle state and a nonnegative missing-scan count without implementing M13 lifecycle transitions.
- Deterministic connector normalization for source type/ID, Unicode/whitespace-stable titles, locations, descriptions, and a search-friendly normalized title that retains meaningful tokens such as C++, C#, and .NET.
- Canonical HTTP(S) job URLs with lowercase scheme/host, default-port removal, root/trailing-slash stability, fragment removal, known tracking-parameter removal, and deterministic query ordering.
- SHA-256 description fingerprints that ignore insignificant whitespace/case differences and a company/title/location/description fallback signature for sources whose connector identity and URL change.
- Dedupe precedence of company-scoped connector identity, canonical URL, then the conservative fallback signature; empty descriptions do not use fallback fingerprint matching.
- A transactional single/batch upsert service that creates once, updates connector-owned fields in place, preserves `discovered_at`, advances but never regresses `last_seen_at`, and reports created/updated/materially-changed state.
- Preservation of lifecycle and future enrichment fields on rediscovery; M12 does not reset missing counters, transition lifecycle, infer locations/work mode/employment/compensation/experience/skills, or clear future scoring/state.
- Atomic rollback when any item in a normalization batch is invalid, while preserving data committed before that batch.
- No scan orchestration, lifecycle transitions, deterministic qualification, AI scoring, user state, dashboard, or M13+ functionality; M13 was not started.

Files created:

- `app/models/jobs.py`
- `app/repositories/jobs.py`
- `app/services/job_normalization.py`
- `app/services/jobs.py`
- `migrations/versions/20260809_0005_jobs.py`
- `tests/module/test_m12_job_normalization.py`

Files changed:

- `app/models/__init__.py`
- `app/models/companies.py`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- Python version: `3.12.13`
- `.venv/bin/python -m pytest tests/module/test_m12_job_normalization.py` -> 3 passed
- Migration/schema workflow -> a fresh database upgraded through revision `20260809_0005` and accepted normalized jobs with required constraints/defaults
- Normalization workflow -> source identity, Unicode/whitespace, canonical URL, title/location/description, description hash, and fallback signature normalized deterministically
- Rediscovery workflow -> the same connector job observed twice remained one row, retained its original `discovered_at`, and refreshed `last_seen_at`
- Change workflow -> changed title, location, and description updated the existing row and reported a material change without resetting lifecycle fields owned by M13
- Multi-identity workflow -> different source identities with the same canonical URL, then a different URL with the same fallback signature, converged on one job row
- Atomicity workflow -> one invalid URL in a two-job batch rolled back the entire batch and left previously committed job data unchanged
- `.venv/bin/python -m compileall -q app/models/jobs.py app/models/companies.py app/models/__init__.py app/services/job_normalization.py app/repositories/jobs.py app/services/jobs.py migrations/versions/20260809_0005_jobs.py tests/module/test_m12_job_normalization.py` -> passed
- Disposable SQLite `alembic upgrade head` through `20260809_0005`, followed by `alembic check` -> no new upgrade operations detected
- `.venv/bin/python -m pip check` -> no broken requirements
- `git diff --check` -> passed

Acceptance result: all M12 acceptance criteria pass. Jobs persist in the canonical schema, connector identity/canonical URL/fallback fingerprints prevent rediscovery duplicates, connector changes update the existing row, `discovered_at` remains stable, and `last_seen_at` refreshes on later observations.

Issues discovered:

- No M12 schema, normalization, identity, upsert, timestamp, or transaction failure remains.
- Fallback matching deliberately requires a nonempty description and includes its normalized fingerprint. This avoids merging separate same-title/same-location requisitions when a source supplies too little content, at the cost of not guessing that such sparse records are duplicates.
- Job uniqueness is company-scoped. Duplicate company records are intentionally not reconciled in M12; M04/M05 own company identity and already prevent normal duplicate registry insertion.
- Connector updates own only source identity, canonical URL, title, location text, description, hashes, and last-seen/update timestamps. Nullable canonical enrichment fields remain available for later owning modules and are not fabricated from unstructured text here.
- SQLite returns stored timezone values without timezone metadata. M12 requires timezone-aware observation inputs, converts them to UTC, and compares persisted naive values as UTC so `last_seen_at` cannot regress.
- `source_payload_json` is nullable and remains empty because the frozen connector contract does not expose raw payloads. M12 does not expand that contract or persist unbounded source responses.
- No external sites were called. All M12 behavior is verified against a temporary migrated SQLite database and deterministic connector records.

## M13 Completion Record

Completed: 2026-08-09

Implemented:

- A source-scoped lifecycle reconciliation service over persisted M12 jobs, with no scan orchestration or M14 qualification behavior.
- Failed-scan protection: unsuccessful source scans make no lifecycle or missing-counter changes and return an explicit `scan_applied=false` result.
- Successful-scan missing counters: the first confirmed absence remains `open`, the second becomes `possibly_closed`, and the configured repeated-absence threshold closes the job.
- A typed `JOB_AGENT_JOB_LIFECYCLE_CLOSE_AFTER_MISSING_SCANS` setting with a conservative default of three successful absences and a validated range of 3–20.
- Reappearance handling that resets the missing counter to zero and restores `open`, including jobs previously marked `possibly_closed` or `closed`.
- Direct explicit-closure handling that transitions a persisted job to `closed` immediately and is idempotent when repeated.
- Frozen handling for already-closed absent jobs so later absence scans do not continuously increase their counters or manufacture additional transitions.
- Company/source existence and scope validation before mutation, preventing a successful scan from reconciling job identifiers belonging to another company or source.
- Atomic commit/rollback behavior and normalized timezone-aware reconciliation timestamps.
- Focused lifecycle tests covering repeated successful absence, failed-scan protection, cross-scope rejection, explicit closure, repeated closure, and reappearance reset.
- No database migration: M12 already created the lifecycle status and missing-counter columns required by M13.

Files created:

- `app/services/job_lifecycle.py`
- `tests/module/test_m13_job_lifecycle.py`

Files changed:

- `.env.example`
- `README.md`
- `app/config.py`
- `app/repositories/jobs.py`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- `.venv/bin/python -m pytest tests/module/test_m13_job_lifecycle.py` -> 3 passed
- Repeated-absence workflow -> first successful absence remained `open` with count 1, second became `possibly_closed` with count 2, and the default third absence became `closed` with count 3
- Closed-state workflow -> later absence left the closed job and counter unchanged
- Reappearance workflow -> a seen closed job returned to `open` with a zero missing counter; a normal M12 upsert alone did not bypass lifecycle reconciliation
- Failed-scan workflow -> an unsuccessful scan changed neither lifecycle nor missing count
- Scope workflow -> a seen job identifier owned by another company was rejected before any lifecycle changes, and the transaction remained unchanged
- Explicit-closure workflow -> an open job closed immediately, a repeated request was idempotent, and a later confirmed reappearance reset it to open
- `.venv/bin/python -m compileall -q app/config.py app/repositories/jobs.py app/services/job_lifecycle.py tests/module/test_m13_job_lifecycle.py` -> passed
- `.venv/bin/python -m pip check` -> no broken requirements
- `git diff --check` -> passed

Acceptance result: all M13 acceptance criteria pass. One confirmed absence does not close a job, repeated successful absences transition safely through `possibly_closed` to `closed`, failed scans do not count as absences, reappearance restores `open` with zero misses, and an explicit closed signal may close immediately.

Issues discovered:

- No M13 lifecycle, transaction, source-scope, explicit-closure, or reappearance failure remains.
- The closure threshold is intentionally at least three, ensuring the second absence can represent `possibly_closed`; deployments may raise it through the typed environment setting without code changes.
- Failed scans neither increment nor reset the counter. The next successful scan therefore continues from the preceding successful observation history, matching the frozen requirement for consecutive successful scan evidence.
- Explicit closure does not fabricate a missing-scan count. The lifecycle state records the direct signal, while the counter continues to represent confirmed scan absences.
- M13 accepts already-persisted source scan results; scan scheduling, overlap control, company scan metadata, and scan-health logging remain owned by later modules.

## M14 Completion Record

Completed: 2026-08-09

Implemented:

- A stateless, profile-specific deterministic qualification service that runs against existing M02 profiles and M12 jobs and returns an immutable eligible/rejected result with stable reason codes.
- Exact-token internship detection from job titles and employment type, avoiding false positives such as `Internal Tools Engineer`.
- Conservative role relevance using the profile's target roles and approved synonyms, small developer/engineer aliases, ignored seniority/level words, and a narrow set of obvious occupational domain conflicts.
- Management-only rejection for manager/director/head/chief/VP-style titles unless a management role in the profile explicitly targets the same role family.
- Flexible experience handling that uses structured `experience_min` when available or conservatively recognizes explicit required/minimum experience statements in descriptions.
- A three-year experience allowance so close Senior/Lead opportunities remain eligible while only obvious gaps are rejected; Senior, Lead, Principal, Staff, and similar title words never reject by themselves.
- Preferred/desirable experience statements are ignored by the deterministic rejection rule rather than treated as hard requirements.
- Partial-skill preservation: qualification does not reject based on missing or incomplete `skills_json`; detailed skill fit remains owned by M15 scoring.
- Existing profile excluded keywords are honored through bounded phrase matching over title, employment type, and description.
- No qualification persistence, schema migration, score, AI provider, job match, scan pipeline, UI, or M15 behavior was added.

Files created:

- `app/services/job_qualification.py`
- `tests/module/test_m14_job_qualification.py`

Files changed:

- `README.md`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- `.venv/bin/python -m pytest tests/module/test_m14_job_qualification.py` -> 4 passed
- Internship workflow -> a software internship was rejected while `Internal Tools Engineer` remained eligible
- Unrelated-role workflow -> an obvious Sales Engineer conflict was rejected despite sharing the generic Engineer word
- Management workflow -> Engineering Manager was rejected for an engineering-only profile and retained for a profile explicitly targeting Engineering Manager
- Flexible-experience workflow -> a Senior role requiring three additional years remained eligible; a Lead role with a four-year gap and a description with ten explicitly required years were rejected
- Preferred-experience workflow -> a ten-year preferred-only statement did not reject
- Seniority/skill workflow -> a Technical Lead with only one recorded matching skill remained eligible
- Profile-exclusion workflow -> an explicit `contract role` profile exclusion rejected a matching role containing that phrase
- `.venv/bin/python -m compileall -q app/services/job_qualification.py tests/module/test_m14_job_qualification.py` -> passed
- `.venv/bin/python -m pip check` -> no broken requirements
- `git diff --check` -> passed

Acceptance result: all M14 acceptance criteria pass. Internships, obvious unrelated roles, inappropriate management-only roles, and clear experience mismatches are rejected before AI, while Senior/Lead titles, flexible near-range experience, preferred-only experience, explicitly targeted management roles, and partial-skill matches remain eligible.

Issues discovered:

- No M14 deterministic-rule or focused-test failure remains.
- Role filtering is intentionally conservative: generic or ambiguous technical roles remain eligible unless there is an explicit conflict, leaving nuanced relevance to M15 rather than risking false negatives.
- Description experience parsing accepts only narrow required/minimum/range forms and ignores nearby preferred/desirable language. Ambiguous prose stays eligible.
- The three-year experience allowance is a small fixed V1 rule, not a new runtime setting; this keeps qualification flexible without adding unspecified configuration.
- Qualification is evaluated per profile and is not persisted because the frozen data model defines no qualification record or job-level profile-independent flag. M15 can score only results that pass this gate.

## M15 Completion Record

Completed: 2026-08-09

Implemented:

- The frozen `job_matches` persistence model with one current match per job/profile, provider/model/scoring version, all required score components, derived recommendation label, matching/missing skills, concerns, explanation, optional suggested resume, source-job hash, and score timestamp.
- Alembic revision `20260809_0006` with score/label checks, job/profile/resume foreign keys, cascade/set-null behavior, uniqueness, and profile-score/job indexes.
- One strict Pydantic output contract with bounded scores, lists, strings, explanation, resume ID, and role/skill profile suggestions; unexpected or malformed fields are rejected before persistence.
- An `AIProvider` boundary, disabled zero-credential provider, settings-driven provider factory, and direct `httpx` adapters for OpenAI Responses, Anthropic Messages, and Gemini Generate Content.
- Provider-native structured requests: OpenAI JSON-schema output with response storage disabled, Anthropic forced schema-backed tool input, and Gemini JSON-schema response configuration; every result is independently revalidated by Pydantic.
- A shared one-MiB response limit, configured 5–120 second timeout, configured one-to-three connection limit, redirects disabled through the factory, and one safe retry for transport or HTTP 5xx failures.
- A profile-specific asynchronous matching service that builds a bounded prompt from the job, profile, and up to 20 resumes, with a 30,000-character job-description cap and 60,000-character total resume-text cap.
- Explicit untrusted-data delimiters and system instructions preventing job descriptions, notes, or resume text from overriding matching instructions; secrets and raw provider responses are never placed in prompts or errors.
- Transactional match create/update behavior, server-derived frozen score labels, and validation that a suggested resume belongs to the scored profile.
- AI role/skill suggestions persisted only as pending M02 suggestions, with existing/current/duplicate values suppressed and no direct candidate-profile mutation.
- A stable scoring-input hash over material job fields. An unchanged job/provider/model/scoring version returns `skipped` without an AI call; changed job content updates the same match row and can rescore.
- Provider/malformed/semantic failures return an isolated `failed` result without creating a match or suggestion; missing job/profile identifiers remain explicit programming errors.
- No deterministic qualification changes, scan orchestration, dashboard/filter UI, queue, notification, or M16+ functionality.

Files created:

- `app/models/job_matches.py`
- `app/providers/ai/__init__.py`, `app/providers/ai/_http.py`, `app/providers/ai/base.py`, and `app/providers/ai/factory.py`
- `app/providers/ai/openai.py`, `app/providers/ai/anthropic.py`, and `app/providers/ai/gemini.py`
- `app/repositories/job_matches.py`
- `app/schemas/ai.py`
- `app/services/ai_matching.py`
- `migrations/versions/20260809_0006_job_matches.py`
- `tests/module/test_m15_ai_matching.py`

Files changed:

- `.env.example`
- `README.md`
- `app/config.py`
- `app/models/__init__.py`, `app/models/jobs.py`, and `app/models/profiles.py`
- `app/repositories/profiles.py` and `app/repositories/resumes.py`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- `.venv/bin/python -m pytest tests/module/test_m15_ai_matching.py` -> 4 passed
- Persistence workflow -> all frozen match fields persisted, the score label was derived, the suggested resume belonged to the profile, and a role/skill suggestion remained pending without mutating profile skills
- Prompt-safety workflow -> instruction-like job text remained inside explicit untrusted-data delimiters and the system prompt stated that it could not override instructions
- Unchanged-input workflow -> the second scoring request returned `skipped` with no second provider call; changed description content rescored and updated the same match row
- Malformed-output workflow -> invalid structured OpenAI text returned a controlled `failed` result and persisted no match or suggestion
- Resume-boundary workflow -> an otherwise valid response suggesting an ID outside the profile failed without persistence
- Adapter workflow -> deterministic local HTTP fixtures validated OpenAI, Anthropic, and Gemini structured request/response envelopes, credential headers, and one safe OpenAI HTTP 503 retry
- Disabled/factory workflow -> zero-credential settings selected the disabled provider; configured OpenAI settings selected the adapter without exposing the key
- Disposable SQLite `alembic upgrade head` through `20260809_0006`, followed by `alembic check` -> no new upgrade operations detected
- `.venv/bin/python -m compileall -q app/config.py app/models app/schemas/ai.py app/providers/ai app/repositories app/services/ai_matching.py migrations/versions/20260809_0006_job_matches.py tests/module/test_m15_ai_matching.py` -> passed
- `.venv/bin/python -m pip check` -> no broken requirements
- `git diff --check` -> passed

Acceptance result: all M15 acceptance criteria pass. Configured adapters share one validated structured contract, successful matches and suggestions persist safely, malformed/invalid output cannot crash or partially write, and an unchanged job with the same provider/model/scoring version does not rescore.

Issues discovered:

- The first focused run found that a newly assigned integer experience value (`6`) reloaded from SQLite as a float (`6.0`), changing a JSON hash despite identical meaning. Hash inputs now canonicalize numeric experience values, and the unchanged-job regression test passes.
- No M15 migration, adapter, persistence, prompt-boundary, malformed-output, resume-ownership, or rescore-skip failure remains.
- No live AI request was made. Real matching requires the chosen provider's API key and model ID; absent configuration remains a safe disabled state rather than an application-start blocker.
- AI inputs are deliberately bounded and may truncate very long descriptions/resume collections. Resume IDs and names remain present for the bounded resume set, while excessive text cannot grow a request without limit.
- M15 exposes the provider and matching service boundaries but does not schedule them or render results; the common scan pipeline and dashboard remain later owning modules.

## M16 Completion Record

Completed: 2026-08-09

Implemented:

- A server-rendered dashboard backed by live aggregate counts for Apply Today candidates, open Strong Matches, new open jobs, and applied jobs while retaining the existing scan-health placeholder owned by M21.
- A Strong Matches dashboard table showing the five highest-scoring open jobs and a direct link to the complete 85+ open-job result set. This is a reference list, not M17's configurable daily action queue.
- A `/jobs` browser page with 25-row server-side pagination, stable score-first ordering, total/page information, previous/next navigation, and an explicit empty state.
- The complete frozen M16 filter set: candidate profile, role, minimum score, location mode, city, source, lifecycle, New/Saved/Applied/Ignored, minimum salary, remote-only, posted date, and discovered date.
- A compact editorial job table with the required Match, Role, Company, Location, Salary, Source, Discovered/Posted, and Status columns.
- Best available profile match selection per job, frozen M15 score labels, profile name, user state, lifecycle state, formatted salary, and posted/discovered dates.
- The frozen `job_user_state` table and SQLAlchemy relationships required for M16's read-only state filters, including one state per job/profile, constrained state values, optional application metadata fields, and cascade/set-null foreign-key behavior.
- Alembic revision `20260809_0007` for only the frozen user-state table and its required constraints/indexes.
- Read-only M16 state display/filtering. Save, Applied, Ignore, note, resume-selection, and job-detail mutation routes remain owned by M18 and were not added.
- No client-side dataset rendering, SPA framework, JavaScript dependency, configurable queue, job detail, state action, scheduler, scan orchestration, or M17+ functionality.

Files created:

- `app/models/job_user_state.py`
- `app/services/job_dashboard.py`
- `app/web/jobs.py`
- `app/web/templates/jobs.html`
- `migrations/versions/20260809_0007_job_user_state.py`
- `tests/module/test_m16_dashboard_filters.py`

Files changed:

- `app/main.py`
- `app/models/__init__.py`, `app/models/jobs.py`, and `app/models/profiles.py`
- `app/web/routes.py`, `app/web/templates/base.html`, and `app/web/templates/dashboard.html`
- `app/web/static/styles.css`
- `README.md`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- `.venv/bin/python -m pytest tests/module/test_m16_dashboard_filters.py` -> 3 passed
- Dashboard workflow -> live counts reported two strong unhandled candidates, three open strong matches, one new open job, and one applied job from the deterministic fixture.
- 85+ workflow -> the dashboard and `/jobs?min_score=85&lifecycle=open` surfaced all three open 85+ matches, displayed `92%` as `Excellent`, and excluded an open 82 match and a closed 95 match.
- State/location workflow -> profile-scoped applied and ignored filters returned only their matching rows with onsite/Bengaluru and hybrid/Pune constraints; a remote/Pune saved Lever result also filtered correctly.
- Complete-filter workflow -> the rendered form exposed all twelve frozen filter inputs and retained filtered values.
- Pagination workflow -> 26 open jobs rendered as 25 rows on page one and one row on page two with working Next/Previous links.
- Disposable SQLite `alembic upgrade head` through `20260809_0007`, followed by `alembic check` -> no new upgrade operations detected.
- `.venv/bin/python -m compileall -q app/models app/services/job_dashboard.py app/web/jobs.py app/web/routes.py app/main.py migrations/versions/20260809_0007_job_user_state.py tests/module/test_m16_dashboard_filters.py` -> passed.
- `.venv/bin/python -m pip check` -> no broken requirements.
- `git diff --check` -> passed.
- The full application test suite was intentionally not run under the frozen testing policy.

Acceptance result: all M16 acceptance criteria pass. Open jobs scoring at least 85 are directly reachable from the dashboard and score/lifecycle filters; pagination and score labels render correctly; applied, ignored, city, location-mode, and remote filtering work alongside every other frozen product filter.

Issues discovered:

- No M16 migration, dashboard-query, pagination, score-label, state-filter, location-filter, or rendering failure remains.
- The request said to verify M15 acceptance criteria while otherwise limiting work and tests to M16. This was treated as a module-number typo; M16 acceptance criteria were verified, and M15 or full-project tests were not rerun.
- M16 needs the frozen `job_user_state` schema to read applied/ignored filters before M18 owns the browser mutations. Focused fixtures create those states directly; no premature state action was exposed.
- The Apply Today metric counts open 85+ jobs that have not been applied to or ignored, but M16 does not choose a configurable target or render a ranked daily queue. Those behaviors remain entirely deferred to M17.
- A first disposable-migration command was rejected before execution because its temporary-file cleanup used a prohibited `rm` command. The check was rerun successfully with an OS-managed temporary database and no manual deletion.
- No live provider or external site was called; M16 uses only the local SQLite data already produced by earlier modules.

## M17 Completion Record

Completed: 2026-08-09

Implemented:

- A typed `daily_action_target` runtime setting with the frozen default of 10, exposed as `JOB_AGENT_DAILY_ACTION_TARGET` and bounded from 1 to 100 to keep the local dashboard query and rendered table small.
- A database-backed daily action queue that selects only `open` jobs with a persisted M15 match for an active candidate profile. A persisted match is the available V1 relevance signal because M14 qualification gates jobs before M15 scoring and the frozen model defines no separate relevance flag.
- Strongest-active-profile selection for jobs with multiple profile matches, preventing a higher historical match for an inactive profile from hiding a valid active-profile result.
- Global exclusion of jobs with any Applied or Ignored state, while Saved and New jobs remain eligible as required by the frozen not-applied/not-ignored rule.
- Deterministic score-first ranking with discovery time and job ID tie-breakers, plus a single SQL limit equal to the configured target so the queue does not load the full job dataset into memory.
- The Apply Today dashboard metric now reports the rendered queue size rather than the uncapped number of potential candidates.
- The frozen Apply Today editorial section with rank, score/label, role, linked profile, company, location, salary, source, and current state, followed by the existing Strong Matches section.
- An explicit empty queue state when no open scored job needs action.
- No schema migration, new table, browser-side rendering, job detail, Save/Applied/Ignore mutation, application note/resume selection, or M18+ functionality.

Files created:

- `tests/module/test_m17_daily_action_queue.py`

Files changed:

- `.env.example`
- `app/config.py`
- `app/services/job_dashboard.py`
- `app/web/routes.py`
- `app/web/templates/dashboard.html`
- `app/web/static/styles.css`
- `README.md`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- `.venv/bin/python -m pytest tests/module/test_m17_daily_action_queue.py` -> 2 passed.
- Default-target workflow -> twelve otherwise eligible jobs produced exactly ten ranked Apply Today rows and a dashboard metric of 10.
- Configured-target workflow -> `daily_action_target=2` produced exactly the same top two ranked jobs and a dashboard metric of 2.
- Ranking workflow -> the saved 99-point match ranked ahead of the new 98-point match; lower-ranked rows were capped at the configured target.
- Eligibility workflow -> Saved stayed eligible, while Applied, Ignored, closed, unscored, inactive-profile-only, and globally handled multi-profile jobs did not enter the queue.
- Active-profile workflow -> a 100-point inactive historical match did not hide the same job's 98-point active match.
- `.venv/bin/python -m compileall -q app/config.py app/services/job_dashboard.py app/web/routes.py tests/module/test_m17_daily_action_queue.py` -> passed.
- `.venv/bin/python -m pip check` -> no broken requirements.
- `git diff --check` -> passed.
- No migration check was needed because M17 changes no database schema.
- The full application test suite was intentionally not run under the frozen testing policy.

Acceptance result: all M17 acceptance criteria pass. The queue defaults to 10, honors a configured target, ranks the strongest active-profile matches, and contains only open, scored/relevant jobs that have not been applied to or ignored.

Issues discovered:

- The first focused pass exposed a multi-profile selection edge: choosing the best match before restricting profiles could let a higher inactive-profile score suppress an active-profile match. Active-profile filtering now occurs inside the correlated best-match query, and the regression test passes.
- No unresolved M17 configuration, ranking, eligibility, query-boundary, or rendering failure remains.
- Applied/Ignored exclusion is intentionally job-wide so the same job is not recommended again through another profile. Saved remains queue-eligible because the frozen rule excludes only Applied and Ignored.
- Queue relevance is represented by a persisted match for an active profile; no speculative relevance table, qualification persistence, or extra threshold was invented.
- M18 remains responsible for job details and state mutations. M17 only reads the frozen state records introduced for M16 filters.

## M18 Completion Record

Completed: 2026-08-09

Implemented:

- An internal `/jobs/{job_id}` reading-oriented detail page; Jobs, Apply Today, and Strong Matches now link to it with the relevant profile instead of sending the user directly away from the application.
- A separate `Open Original Job` action using the stored canonical URL with a new tab and `noopener noreferrer` boundary.
- Complete frozen detail content: title, company, location/work mode, source, lifecycle, original URL, description, salary, experience, employment type, posted/discovered dates, linked profile, suggested resume, and current user state.
- Complete M15 match presentation for the selected profile: overall score/label, all seven component scores plus nullable salary score, explanation, matching skills, missing skills, and concerns.
- Active-first default profile selection, score ordering within active/inactive groups, and a compact profile switcher when multiple candidate profiles exist. Unscored jobs remain readable and state-capable without fabricating match data.
- Profile-specific Save, Mark Applied, and Ignore mutations over the existing frozen `job_user_state` table, with one upserted row per job/profile and transactional commit/rollback behavior.
- Optional application resume and note persistence. Resume identifiers are accepted only when they belong to the selected profile, notes are whitespace-trimmed and bounded to 5,000 characters, and the original applied timestamp is retained on repeated Applied updates.
- Applied metadata remains retained if the current state later changes to Saved or Ignored, preserving the single-table application history available in frozen V1.
- Internal job-list rows now carry the selected profile identifier so detail, match, state, and resume context remain aligned.
- No M19 scheduler, Search Now action, scan orchestration, notification, new database schema, browser framework, or external integration.

Files created:

- `app/services/job_details.py`
- `app/web/templates/job_detail.html`
- `tests/module/test_m18_job_detail_state.py`

Files changed:

- `app/services/job_dashboard.py`
- `app/web/jobs.py`
- `app/web/templates/jobs.html`
- `app/web/templates/dashboard.html`
- `app/web/static/styles.css`
- `README.md`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- `.venv/bin/python -m pytest tests/module/test_m18_job_detail_state.py` -> 2 passed.
- Detail workflow -> the internal job link opened a profile-aligned page containing company/location/source/original URL, full match summary and breakdown, skills/gaps/concerns, salary/experience, readable description, suggested resume, current state, and all three frozen actions.
- Save workflow -> a New job created one profile-specific state row with state Saved and redirected back to the aligned detail page.
- Applied workflow -> the same row changed to Applied and stored `applied_at`, the selected profile-owned resume, and the optional note.
- Rediscovery workflow -> an M12 source-identity upsert updated the existing job description while retaining the same job ID and complete Applied state metadata; the refreshed detail page showed both the updated description and Applied state.
- Ignore workflow -> the same row changed to Ignored after rediscovery without losing its prior application timestamp, resume, or note.
- Resume-boundary workflow -> a resume owned by another profile returned HTTP 422 and did not alter the persisted state.
- `.venv/bin/python -m compileall -q app/services/job_details.py app/services/job_dashboard.py app/web/jobs.py tests/module/test_m18_job_detail_state.py` -> passed.
- `.venv/bin/python -m pip check` -> no broken requirements.
- `git diff --check` -> passed.
- No migration check was needed because M18 uses the already-migrated frozen state table without schema changes.
- The full application test suite was intentionally not run under the frozen testing policy.

Acceptance result: all M18 acceptance criteria pass. The detail page provides the required decision information and original URL; Save, Applied, and Ignore persist per job/profile; optional application resume/note metadata is validated and retained; and state survives a real rediscovery/upsert of the same job.

Issues discovered:

- No unresolved M18 detail, profile-selection, state-upsert, resume-ownership, rediscovery-persistence, or rendering failure remains.
- Applied metadata is deliberately not erased when a user later selects Save or Ignore because the frozen schema has no separate application-history table and V1 requires application history to remain recoverable.
- A job may be viewed and assigned a state even when it has no match. In that case the page clearly reports `Not scored`, selects the first active profile by default, and does not fabricate scores or recommendations.
- The state form is available for inactive profiles only when that profile is explicitly selected; M18 preserves existing profile-linked history rather than silently remapping it.
- M19 remains responsible for enabling Search Now, scheduling, overlap protection, and visible scan-run state.

## M19 Completion Record

Completed: 2026-08-09

Implemented:

- One application-process `AsyncIOScheduler` using the architecture-approved APScheduler 3.x asyncio scheduler and an interval trigger.
- A typed `scan_interval_hours` runtime setting exposed as `JOB_AGENT_SCAN_INTERVAL_HOURS`, defaulting to the frozen four hours and bounded from 0.25 hours to seven days.
- Scheduler startup after database migration/readiness and seed import, plus scheduler/task shutdown before engine disposal. Scheduling exists only while the FastAPI process runs; no OS boot integration or persistent worker was added.
- A single shared scan pipeline used unchanged by manual and scheduled triggers: profile-driven company discovery, ATS classification, all five supported/fallback connector passes, normalized upsert/deduplication, lifecycle reconciliation, deterministic profile qualification, and configured AI matching.
- Continued known-source scans when web discovery is disabled or fails; discovery, source, persistence, and individual AI failures remain isolated and produce a Partial run rather than discarding completed work.
- Sequential connector families with each connector's existing bounded concurrency, short per-source persistence/lifecycle sessions, and 100-job matching batches to remain suitable for the target Linux laptop.
- Company `last_scanned_at`, successful-scan timestamp, and last job count updates as sources run.
- One `ScanController` task/lock guard shared by both trigger types. A running task causes additional manual or scheduled starts to return immediately without queuing or overlapping work; APScheduler also uses `max_instances=1` and coalescing.
- A non-blocking `POST /scans/search-now` action that starts the shared pipeline and redirects immediately with Started or Already Running feedback.
- Live dashboard visibility for Idle, Running, Success, Partial, or Failed state; trigger type; start/completion and next-run timing; company/source/job/scoring counts; bounded current-run errors; configured interval; and current summary.
- Only the current/last snapshot is held in process. M21 retains ownership of persistent `scan_runs`, source-result history, historical health, and durable logs.
- No M20 Telegram destination, delivery, notification event, idempotency log, new schema, external worker, Redis, Celery, OS service, or boot integration.

Files created:

- `app/services/scans.py`
- `app/tasks/__init__.py`
- `app/tasks/scheduler.py`
- `tests/module/test_m19_scheduler_scan.py`

Files changed:

- `.env.example`
- `pyproject.toml`
- `app/config.py`
- `app/main.py`
- `app/web/routes.py`
- `app/web/templates/dashboard.html`
- `app/web/static/styles.css`
- `README.md`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime direct: `apscheduler>=3.11,<4` (installed `3.11.3`)
- Runtime transitive: `tzlocal==5.4.4`
- Test: none

Focused verification evidence:

- `.venv/bin/python -m pytest tests/module/test_m19_scheduler_scan.py` -> 3 passed.
- Shared-pipeline workflow -> the same injected runner received one Manual and one Scheduled trigger through the same controller path.
- Overlap workflow -> while Manual was held in Running state, a second Manual start and a Scheduled trigger both returned `false`; the runner remained at exactly one call.
- Default schedule workflow -> application startup created a future next-run time with the frozen four-hour interval.
- Configurable schedule workflow -> a six-hour application setting rendered `Runs every 6 hours` and a future next scheduled time.
- Search Now workflow -> POST returned HTTP 303 immediately, Running state and a disabled `Search Running` button were visible, a concurrent POST reported Already Running, and completion rendered Success with the Manual trigger and fixture counts.
- Real zero-credential workflow -> one active profile with disabled search and AI completed the real shared pipeline without any external request; it returned a controlled Partial result for the unconfigured search while safely checking zero known sources.
- `.venv/bin/python -m compileall -q app/config.py app/main.py app/services/scans.py app/tasks app/web/routes.py tests/module/test_m19_scheduler_scan.py` -> passed.
- `.venv/bin/python -m pip check` -> no broken requirements.
- `git diff --check` -> passed.
- No migration check was needed because M19 persists no new schema and leaves M21 scan tables unimplemented.
- The full application test suite was intentionally not run under the frozen testing policy.

Acceptance result: all M19 acceptance criteria pass. The scheduler defaults to four hours and is configurable, Search Now and scheduled execution call the same pipeline, the application-wide guard prevents concurrent scans, and current/last run plus next-run state is visible in the dashboard.

Issues discovered:

- The first zero-credential test expected a disabled-search warning with no active profiles. The pipeline correctly generated no query and returned a successful no-op, so the focused fixture was corrected to include one active profile and now exercises the intended disabled-search path.
- No unresolved M19 scheduler lifecycle, trigger parity, overlap, zero-credential, pipeline isolation, run-visibility, or resource-boundary failure remains.
- The current/last run snapshot is deliberately in memory and resets on application restart. Persistent run/source history belongs to the frozen M21 tables and was not started early.
- Source metadata update failures are non-fatal and counted in the visible current-run errors so one metadata write cannot stop later sources; M21 will make such failures durably inspectable.
- APScheduler uses its in-memory job store because the frozen app interval is supplied by typed runtime settings and scheduler operation is process-bound. No extra scheduler database, thread pool, worker, or service was introduced.
- The request's dependency wording referred to M18 while otherwise limiting work to M19. This was treated as a module-number typo; only the explicitly architecture-approved scheduler dependency required by M19 was added.
- M20 remains responsible for Telegram destinations, three notification event types, delivery, and notification idempotency.

## M20 Completion Record

Completed: 2026-08-09

Implemented:

- A Telegram Bot API adapter over the existing bounded `httpx` client with a ten-second configurable timeout, two-connection limit, redirects disabled, plain-text messages, and sanitized delivery failures. The environment-only bot token is never stored in application tables or rendered in the browser.
- Typed `telegram_bot_token`, `telegram_match_threshold` (default 85), and `telegram_timeout_seconds` runtime settings plus safe empty/default entries in `.env.example`.
- Frozen `notification_destinations` and `notification_log` models/migration. The three destination types and delivery states are constrained; each type has one single-user V1 configuration; destination/event uniqueness supplies durable idempotency.
- A server-rendered Telegram settings page exposing exactly High-match recommendations, Application activity, and Search/run summaries. Each destination has a validated name, signed numeric chat ID, and enable switch; enabling without a valid chat ID is rejected.
- Recommendation notifications after a newly persisted job is successfully scored at or above the configured Telegram threshold. Rediscovered/previously known jobs do not enter this event hook, and a stable job/profile event key prevents duplicates.
- Application activity notifications after a successful Mark Applied mutation. Repeated Applied submissions retain the M18 `applied_at` timestamp and therefore resolve to the same idempotency event.
- Scan summary notifications after successful, partial, or failed manual/scheduled completion through the shared M19 controller. Messages contain company/source counts, fetched/new/updated/scored/strong-match counts, and error count.
- Delivery reservation before outbound HTTP, followed by Sent or Failed persistence. Pending and Sent events are suppressed; Failed events may retry and reuse the same row. Provider failures cannot undo a completed application mutation or crash the scan controller.
- The nullable `scan_run_id` column required by the frozen data model is present without a premature foreign key because M21 owns and has not yet introduced persistent `scan_runs`.
- No M21 persistent scan-run/source history or health UI, no bot commands or inbound Telegram behavior, no polling/webhook server, no worker/queue, and no additional feature or dependency.

Files created:

- `app/models/notifications.py`
- `app/providers/telegram.py`
- `app/services/notifications.py`
- `app/web/settings.py`
- `app/web/templates/notification_settings.html`
- `migrations/versions/20260809_0008_notifications.py`
- `tests/module/test_m20_telegram.py`

Files changed:

- `.env.example`
- `app/config.py`
- `app/main.py`
- `app/models/__init__.py`
- `app/services/scans.py`
- `app/web/jobs.py`
- `app/web/static/styles.css`
- `app/web/templates/base.html`
- `README.md`
- `docs/IMPLEMENTATION_STATUS.md`

Dependencies added:

- Runtime: none
- Test: none

Focused verification evidence:

- `.venv/bin/python -m pytest tests/module/test_m20_telegram.py` -> 5 passed.
- Destination workflow -> the settings page rendered exactly three categories and only a Configured status, never the fixture token; all three chat IDs persisted enabled; an invalid ID returned HTTP 422.
- Zero-credential workflow -> application startup and the settings page completed with no bot token, reported Not configured, and created no external request.
- Event-routing workflow -> one high-match, one Applied, and one completed-scan event reached their independently configured chats; repeats produced exactly three total HTTP requests and three Sent idempotency rows.
- Recommendation-boundary workflow -> a 91-point newly discovered job notified once, while scoring the same known job outside the new-job set did not notify again.
- Scan-summary workflow -> the shared completion hook sent source/job/error counts and a direct repeat of the same completed snapshot was suppressed.
- Failure/retry workflow -> an HTTP 500 stored the sanitized `Telegram rejected the message` failure, the same event retried successfully into the existing row, and the subsequent repeat skipped; the bot token was absent from the stored failure.
- Fresh SQLite migration round trip `upgrade head -> downgrade 20260809_0007 -> upgrade head` -> passed; Alembic reported `20260809_0008 (head)`.
- `.venv/bin/python -m compileall -q app/config.py app/main.py app/models/notifications.py app/providers/telegram.py app/services/notifications.py app/services/scans.py app/web/jobs.py app/web/settings.py tests/module/test_m20_telegram.py` -> passed.
- `.venv/bin/python -m pip check` -> no broken requirements.
- `git diff --check` -> passed.
- The full application test suite was intentionally not run under the frozen testing policy.

Acceptance result: all M20 acceptance criteria pass. The three independent destination types are configurable; recommendation, application, and scan-summary events route to the correct chats; repeated events are durably suppressed; and failures are isolated and inspectable without exposing secrets.

Issues discovered:

- No unresolved M20 destination configuration, token handling, threshold, event routing, duplicate suppression, failure isolation, retry, schema, migration, or rendering issue remains.
- Telegram does not offer a client-supplied idempotency key. The application reserves its local event row before sending so concurrent/repeated local triggers cannot duplicate a confirmed delivery; a transport failure remains Failed and may be retried because Telegram cannot confirm whether an ambiguous network interruption delivered remotely.
- Only new jobs from the current scan trigger recommendation delivery, matching the frozen product wording. Changed or unchanged rediscoveries remain scoreable under M15 rules but do not create another recommendation event.
- M20 summary idempotency uses the M19 trigger/start timestamp because persistent scan IDs do not exist yet. M21 can populate `scan_run_id` when it introduces the frozen scan tables without changing notification behavior.
- Live delivery still requires a user-owned bot token and chat IDs. Missing credentials are an expected Not configured state, not an application-start blocker.
- M21 remains responsible for durable scan/source logs, run history, counts, and recent health presentation.

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

There are no genuine blockers to starting M21 when explicitly requested.

Live AI scoring, web company discovery, and Telegram delivery will eventually require user-supplied credentials or destination identifiers. These are not implementation blockers: the application must start and expose configured/not-configured states with zero credentials, provider behavior will be tested with deterministic fakes/fixtures, and known ATS sources must remain scannable when web search is unavailable.

The visual reference was inspected during M01 through a bounded direct fetch after the normal browser fetch failed.

## Next Action

Stop after M20. Do not begin M21 until explicitly requested.
