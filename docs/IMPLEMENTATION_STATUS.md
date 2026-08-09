# Job Agent V1 — Implementation Status

Last updated: 2026-08-09

## Current State

M01 Project Foundation through M10 Workday Connector are complete. M11 has not started.

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

There are no genuine blockers to starting M11 when explicitly requested.

Live AI scoring, web company discovery, and Telegram delivery will eventually require user-supplied credentials or destination identifiers. These are not implementation blockers: the application must start and expose configured/not-configured states with zero credentials, provider behavior will be tested with deterministic fakes/fixtures, and known ATS sources must remain scannable when web search is unavailable.

The visual reference was inspected during M01 through a bounded direct fetch after the normal browser fetch failed.

## Next Action

Stop after M10. Do not begin M11 until explicitly requested.
