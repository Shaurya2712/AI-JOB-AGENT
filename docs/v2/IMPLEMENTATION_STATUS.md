# Job Agent V2 — Portal Discovery Implementation Plan

Last updated: 2026-08-10

Status: V2-M01 Portal Search Boundary is complete. V2-M02 has not started.

## Scope and Repository State

This plan adds search-provider-based discovery for LinkedIn, Naukri, and Indeed to the completed V1 monolith. It does not add portal login, direct authenticated scraping, CAPTCHA/access-control bypass, browser automation, another job database, another matching engine, another scheduler, or another notification system.

The repository was reviewed with an existing user-owned documentation reorganization in the worktree: frozen V1 documents are now under `docs/v1/` and V2 documents are under `docs/v2/`. Those moves and frozen files are not modified by this planning pass.

All V1 documents, the complete V1 implementation record, all V2 specification files, the application code, migrations, and affected focused tests were inspected before deriving this plan.

## Current V1 Architecture Findings Relevant to V2

### Company discovery and web search

- `ProfileSearchQueryGenerator` reads every active profile and combines target roles, role synonyms, preferred locations, and Remote work mode. It deduplicates deterministically and enforces one configured query cap.
- `WebSearchProvider` is already the correct reusable network boundary. It exposes `is_configured` and asynchronous `search(query)` returning bounded `WebSearchResult(title, url, description)` records.
- The only current implementation is `BraveSearchProvider`. It uses bounded results, timeouts, response size, concurrency, and one safe transport/5xx retry. It requires only the existing Brave API key.
- `CompanyDiscoveryService` owns company-career interpretation and persistence. Search failures are isolated and the existing company registry remains available to downstream ATS scans.
- `SearchDiscoveryParser` deliberately blocks LinkedIn, Naukri, and Indeed, along with other aggregators/social hosts, before creating a `Company`. This behavior is correct for V2 and must remain unchanged.

### ATS and job acquisition

- ATS identity lives on `Company` as `provider_type`, `provider_identifier`, and `provider_supported`.
- `AtsDetectionService` classifies only active company-registry records. Supported providers are Greenhouse, Lever, Ashby, and Workday; custom career pages use the bounded generic fallback.
- `JobConnector` returns a company-neutral `ConnectorJob`, but `JobCollectionService` supplies the owning `Company` and produces company-scoped source results.
- Portal discovery should not be forced through `JobCollectionService`: a search result already represents one job and supplies an employer name, not a company-registry career source or a connector capable of listing all open jobs.

### Normalization, persistence, and current deduplication

- `JobUpsertService` sends connector records through `normalize_connector_job` and persists them transactionally into the single `jobs` table.
- URL normalization removes fragments and known tracking parameters. Title/location/description normalization is deterministic and description hashes use SHA-256.
- Current deduplication precedence is: same `company_id + source_type + source_job_id`, then same `company_id + canonical_url`, then same company-scoped title/location/description fingerprint when the description is nonempty.
- Current deduplication cannot satisfy V2 cross-source cases because every job requires `company_id`, and every match is scoped to that ID. A LinkedIn result cannot safely be attached to a fabricated company-registry row.
- `JobUserState`, `JobMatch`, and `NotificationLog` reference the canonical job ID. Updating/enriching that same row is therefore the safest way to preserve application state and notification identity.

### Lifecycle

- Lifecycle reconciliation is scoped to one `company_id + source_type` and is applied only after a successful complete source scan.
- Failed source scans do not count as absences. Seen jobs reopen and reset missing counts; repeated confirmed absence transitions through `possibly_closed` to `closed`.
- Search-engine result sets are ranked samples, not complete portal inventories. Absence from a later portal search must not increment lifecycle missing counters. Portal rediscovery should refresh `last_seen_at`; only a later authoritative/full source may use normal V1 lifecycle reconciliation.

### Qualification and AI matching

- Deterministic qualification is profile-specific and runs immediately before AI scoring. It handles exclusions, internships, unrelated roles, management-only roles, and clear experience mismatches without rejecting partial skill matches.
- `AIMatchingService` has no current completeness concept. Every open job selected by the scan is eligible for qualification/scoring even if its description is empty.
- The prompt and rescore hash already use the canonical job row. The minimal safe V2 change is one completeness-aware branch inside the existing matching service: full jobs retain the V1 prompt/output path, while eligible partial jobs use a constrained preliminary prompt and scoring version.
- A partial portal record is preliminary-score eligible only when deterministic validation finds a usable title, employer, and a non-boilerplate normalized snippet of at least 80 characters. Missing evidence remains null and must not be inferred. Records below that evidence threshold remain visible as Not Scored and do not trigger an AI call.
- Preliminary results use the explicit label `Partial / Low Confidence`, a deterministic five-point confidence penalty, and a maximum stored overall score of 89. Daily-queue ordering remains primarily by stored score, with `full` before `partial` when scores tie, so an equivalent full-data result ranks above its partial counterpart while a sufficiently strong partial result can still enter the queue.
- When a confidently matching full ATS/company record enriches the same job ID, `data_completeness`, the scoring version, and the source hash change. The existing service then replaces the preliminary match with a normal full-data V1 score without changing the canonical job, application state, or notification identity.

### Scheduler, scan logging, Telegram, and filters

- Manual Search Now and APScheduler use one `ApplicationScanPipeline` behind one overlap guard. V2 must add portal discovery to this pipeline, not create another scheduler.
- `ScanSourceSnapshot` and `scan_source_results.company_id` already allow `None`, so LinkedIn/Naukri/Indeed can be logged as independent non-company sources without a schema change to scan history.
- A connector/source failure is already isolated and turns a run Partial while later source families continue.
- Recommendation idempotency is durable through `destination_id + event_key`; high-match keys are `high-match:{job_id}:{profile_id}`. Keeping one canonical job ID prevents a second portal/ATS notification.
- The Jobs source filter currently uses only exact `Job.source_type`, and filter choices come only from distinct canonical job source values. V2 filtering must also consider attached portal observations so an ATS-canonical job discovered on LinkedIn is still returned by the LinkedIn filter.
- Dashboard/detail/Telegram queries currently inner-join `Company`. They must use the canonical job's stored display company name so portal-only jobs do not require fake company rows.
- Backup validation pins the exact Alembic revision and required-table set. Any V2 migration must update backup validation and should preserve restore of existing V1 backups by migrating a staged V1 database before installation.

### Existing incomplete-data behavior

- Text and most enrichment fields may already be empty/null, and the UI renders `Not listed` or `Not scored` in several places.
- There is no explicit partial/full marker, no warning that description text is only a search snippet, and no evidence threshold for meaningful scoring.
- V2 needs only a deterministic preliminary-scoring gate, explicit low-confidence presentation, nullable unavailable score components, and automatic normal rescoring after full enrichment. It does not need a second matcher or a second match table.

## Proposed Minimal Architecture

```text
Active profiles
   -> shared role/location targets
      -> existing company queries -> CompanyDiscoveryService -> ATS/company pipeline
      -> portal queries
          -> existing WebSearchProvider
          -> strict LinkedIn/Naukri/Indeed recognizers
          -> partial portal candidates
          -> canonical Job upsert + portal observation

ATS/company jobs and portal candidates
   -> one jobs table
   -> deterministic cross-source match when unambiguous
   -> full source wins over partial source
   -> existing qualification/matching with a constrained partial-data branch
   -> existing UI/state/Telegram with explicit partial-data presentation
```

The initial implementation should add only two substantive services:

1. `PortalDiscoveryService`: generate bounded portal queries, execute them through `WebSearchProvider`, validate portal-specific job URLs, parse bounded result metadata, and isolate each portal's failures.
2. `PortalJobUpsertService`: transactionally attach/update portal observations, create partial canonical jobs, and merge/enrich only when deterministic matching is unambiguous.

No portal `JobConnector`, vendor SDK, direct portal HTTP client, or browser adapter is needed.

## Portal Query and Recognition Plan

- Refactor `app/services/search_queries.py` only enough to expose the existing ordered role/location targets to both company and portal query builders. Existing company query text and ordering must remain unchanged.
- Add one bounded `portal_search_max_queries_per_run` setting, proposed default `18`, with round-robin ordering across LinkedIn, Naukri, and Indeed. This gives each portal coverage before adding another role/location variation and limits the default to six queries per portal.
- Reuse existing search country, language, result count, timeout, and concurrency settings.
- Queries remain below the provider's existing 400-character/50-word bounds and use strict site/path targets rather than broad portal searches.
- Accept only portal-specific job detail shapes and derive a stable source ID:
  - LinkedIn: regional or main LinkedIn host with `/jobs/view/...` and a terminal numeric job ID.
  - Naukri: main Naukri host with a `/job-listings-...` job detail path and a terminal numeric posting ID.
  - Indeed: supported Indeed country/main host with `/viewjob` and a nonempty `jk` identifier.
- Reject search pages, home pages, profiles, company pages, recruiter pages, articles, help pages, and any result missing a usable job identity, title, employer name, or URL.
- Portal-specific title/snippet parsing must be conservative and bounded. Unparseable results are skipped rather than guessed.

A bounded planning check on 2026-08-10 found current indexed examples of LinkedIn `/jobs/view/...-{numeric_id}`, Naukri `/job-listings-...-{numeric_id}` (including a shorter `/job-listings-{numeric_id}` form), and Indeed India `/viewjob?jk={id}`. These patterns are inputs to deterministic fixtures, not permission to scrape the pages or a guarantee that search indexing will remain stable.

## Proposed Schema Changes

One Alembic revision is genuinely needed.

### Changes to `jobs`

- Make `company_id` nullable and change its database delete behavior to `SET NULL`.
- Add required `company_name` and backfill it from the currently related `companies.name`.
- Add required `data_completeness` constrained to `partial | full`, defaulting/backfilling all V1 jobs to `full`.
- Add nullable indexed `cross_source_signature`, backfilled for existing jobs when normalized company, title, and location are all available.
- Keep existing canonical `source_type`, `source_job_id`, `canonical_url`, description hash, dedupe signature, lifecycle, user state, and match tables.

`source_type` should directly use `linkedin`, `naukri`, or `indeed` for a portal-only canonical job. A separate `source_name` column is unnecessary in the current model.

### Changes to `job_matches`

- Keep one match row per canonical `job_id + profile_id`; do not add a second preliminary-match table.
- Make `role_score`, `skills_score`, `experience_score`, `location_score`, `freshness_score`, and `seniority_score` nullable. Full-data V1 semantic validation must still require every existing non-salary component; preliminary validation permits null only when the corresponding evidence is absent.
- Keep `overall_score` required because an eligible preliminary result must have enough available evidence to produce a meaningful bounded score. `salary_score` remains nullable.
- Extend `recommendation_label` to hold and allow `Partial / Low Confidence`; full-data labels remain unchanged.
- Use `Job.data_completeness` as the confidence discriminator instead of adding another confidence column.

### New `portal_job_sources` table

This is an alternate-source/observation child of the canonical job, not a second job database.

Proposed fields:

- `id`
- `job_id` with cascading foreign key
- `portal_name` constrained to `linkedin | naukri | indeed`
- `source_job_id`
- `original_url`
- bounded observed `title`, `company_name`, `location_text`, and `snippet`
- `data_completeness` constrained to `partial | full`
- `first_seen_at`, `last_seen_at`

Required uniqueness/indexing:

- unique `portal_name + source_job_id`
- unique `portal_name + original_url`
- index `job_id`
- index `last_seen_at`

Do not store raw search-provider payloads or unbounded search context.

### Deterministic cross-source matching

- Preserve existing V1 source identity, canonical URL, and company-scoped description-fingerprint precedence.
- Add a separate cross-source signature from conservative normalized employer name, normalized title, and normalized location.
- Normalize case, Unicode, whitespace, punctuation, common legal company suffixes, and only a small tested location alias set such as Bangalore/Bengaluru.
- Do not form a cross-source signature when employer, title, or location is missing.
- Merge across portal/portal or portal/full records only when the signature resolves to exactly one canonical candidate. If zero or multiple candidates match, retain separate jobs rather than risk combining different requisitions.
- When partial portal data matches an existing full job, add/update the portal observation and do not overwrite the canonical full fields.
- When a full ATS/company record matches one partial portal job, update that same job ID in place with the real `company_id`, full description, canonical full source identity/URL, and `data_completeness=full`.
- The completeness/scoring-version/hash change must invalidate the preliminary score and invoke the existing full-data V1 matching path. The normal full result replaces the preliminary values on the same `JobMatch` row.
- Never overwrite Saved/Applied/Ignored state, application timestamp, resume, note, existing notification logs, or original `discovered_at` during enrichment.

## Preliminary Matching Policy

- The scan performs existing deterministic qualification first. A qualified partial job proceeds to AI only when it has a usable title, employer, and at least 80 normalized, non-boilerplate snippet characters. Otherwise it has no `JobMatch` row and is presented as Not Scored.
- Use the existing configured `AIProvider`, request/response plumbing, persistence service, and one match row. A separate scoring version such as `job-match-v1-partial` prevents the partial and full inputs from sharing a rescore hash.
- The partial prompt identifies the input as search-result metadata, instructs the provider to score only evidence actually present, and permits null component scores. It must not infer missing skills, experience, seniority, salary, location, freshness, or job-description facts; evidence lists remain empty when the snippet does not support them.
- Apply deterministic post-processing to the returned preliminary overall score: subtract five points, clamp to `0..89`, and persist `Partial / Low Confidence`. Full scores keep the existing V1 labels and values.
- The daily queue may include a partial match when its adjusted score satisfies the existing queue threshold. Ordering is adjusted only by using `full` before `partial` for equal scores; no parallel queue is introduced.
- Telegram uses the existing `high-match:{job_id}:{profile_id}` event key and threshold. A qualifying partial notification must begin with `Partial-data recommendation — low confidence` and must not claim unavailable facts.
- Full enrichment updates the same job and match identities, invokes the normal full-data rescore, and removes the partial label. If the partial recommendation was already delivered, the unchanged event key suppresses a duplicate. If no qualifying partial notification was delivered, a later qualifying full score may create the first notification normally.

## Exact Files Likely to Change

### Existing application/configuration files

- `.env.example` — document the one portal query cap.
- `README.md` — V2 behavior, configuration, partial-data semantics, and focused/final commands after implementation.
- `app/config.py` — typed portal query cap only.
- `app/models/companies.py` — optional job relationship without delete-orphan behavior.
- `app/models/jobs.py` — nullable company relationship and the three canonical V2 fields.
- `app/models/job_matches.py` — nullable unavailable component scores and the longer partial recommendation label constraint.
- `app/models/__init__.py` — register the portal observation model.
- `app/schemas/ai.py` — permit nullable component evidence in preliminary output while retaining strict full-output validation.
- `app/repositories/jobs.py` — portal identity and unique cross-source candidate lookups.
- `app/services/search_queries.py` — shared role/location targets plus bounded portal queries while preserving V1 queries.
- `app/services/job_normalization.py` — shared employer/location normalization and cross-source signature.
- `app/services/jobs.py` — copy company display name for V1 jobs and allow a unique partial job to be upgraded in place.
- `app/services/scans.py` — run portal discovery in the existing scan, log three non-company sources, apply the deterministic partial evidence gate, and rescore partial-to-full upgrades.
- `app/services/ai_matching.py` — add the small completeness-aware prompt/validation branch, preliminary score adjustment/label, and completeness-aware rescore hash; retain one provider and persistence path.
- `app/services/job_dashboard.py` — optional company join, portal-aware source options/filtering, completeness-aware queue tie-breaking, and completeness/source metadata for views.
- `app/services/job_details.py` — optional company registry relationship and portal observation links.
- `app/services/notifications.py` — use `Job.company_name` instead of requiring a Company join, clearly label partial-data recommendations, and keep event keys unchanged.
- `app/services/runtime_settings.py` — make the non-secret portal query cap portable.
- `app/services/backups.py` — current schema/table validation and staged migration of supported V1 backups.
- `app/web/templates/jobs.html` — compact partial/full and source indicators.
- `app/web/templates/job_detail.html` — explicit search-snippet warning and alternate portal links.
- `app/web/templates/dashboard.html` — render the same compact completeness/source metadata where job rows appear.
- `app/web/static/styles.css` — only minimal styling required by the indicators/warning.

`app/services/web_discovery.py`, search-provider adapters, ATS detection, job connectors, lifecycle service, qualification service, scheduler, scan-history schema/service, user-state models, and Telegram models should not require production changes. Their focused tests may still receive regression assertions.

### Proposed new files

- `app/models/portal_sources.py`
- `app/services/portal_discovery.py`
- `app/services/portal_jobs.py`
- `migrations/versions/20260810_0011_v2_portal_discovery.py`
- `tests/module/test_v2_01_portal_discovery.py`
- `tests/module/test_v2_02_portal_dedup.py`
- `tests/module/test_v2_03_portal_integration.py`
- `tests/final/test_v2_end_to_end.py`

No new dependency is proposed.

## Proposed V2 Modules and Status

| Module | Scope | Focused acceptance intent | Status |
|---|---|---|---|
| V2-M01 Portal Search Boundary | Shared profile targets, bounded portal queries, three strict recognizers, per-portal failure results | All portals generate/recognize valid job results; irrelevant pages are rejected; company blocked hosts remain unchanged; no persistence/browser/login | Complete |
| V2-M02 Canonical Portal Persistence | Migration, partial/full marker, nullable unavailable match components, portal observations, deterministic portal/portal and portal/full enrichment | One canonical row when uniquely equivalent; full source wins; ambiguity does not merge; state is preserved; V1 backup can be staged/migrated | Pending |
| V2-M03 Shared Scan and Preliminary Matching | Existing pipeline, source counts/logs, portal isolation, deterministic evidence gate, constrained preliminary scoring, and normal full-data rescore | Useful partial metadata may be scored/queued with an explicit low-confidence label; insufficient metadata is Not Scored; full enrichment replaces the preliminary score on the same identity | Pending |
| V2-M04 UI, Filters, and Idempotency | Existing Jobs/detail/dashboard, portal-aware source filter, partial warning, queue ordering, alternate links, notification and backup regressions | Portal filters work; partial scores and notifications are unmistakable; equivalent full results rank higher; application and Telegram identity remain canonical | Pending |
| V2-M05 Final V1 + V2 Verification | Full historical V1 suite plus realistic V2 end-to-end workflow | All V1 tests and the final V2 fixture workflow pass; no live portal dependency in default tests | Final Verification |

V2-M01 focused checks pass. Do not begin V2-M02 without explicit user instruction, and do not run the complete regression suite before V2-M05.

## V2-M01 Completion Record

Completed: 2026-08-10

Implemented behavior:

- Extracted the existing ordered profile role/location expansion into a shared bounded target generator while preserving V1 company-query text, ordering, case-insensitive deduplication, and early cap behavior.
- Added deterministic portal queries in target-first, LinkedIn/Naukri/Indeed round-robin order. Queries remain within the existing provider's 400-character and 50-word limits and use the approved default cap of 18.
- Added an in-memory `PortalDiscoveryService` that reuses `WebSearchProvider`, applies the existing search concurrency boundary, returns per-portal outcomes, deduplicates repeated portal identities within a run, and isolates configured, provider, and unexpected failures.
- Added strict portal recognition for LinkedIn `/jobs/view/...-{numeric_id}`, Naukri `/job-listings-...-{numeric_id}`, and Indeed `/viewjob?jk={id}` job-detail identities on exact or subdomain-matching portal hosts.
- Added conservative title/employer/location parsing and bounded normalized snippets. Results without a recognized detail identity, usable title, or usable employer are skipped instead of guessed.
- Explicitly rejects portal home, search, company, recruiter/profile, help, article/blog, and host-spoofing results through exact host and job-detail path validation.
- Kept LinkedIn, Naukri, and Indeed in the unchanged company-discovery blocked-host list.
- Added the portable non-secret `portal_search_max_queries_per_run` setting and documented its environment variable.
- Added no persistence, migration, scan-pipeline integration, browser automation, portal login, direct portal request, or scraping behavior.

Files created:

- `app/services/portal_discovery.py`
- `tests/module/test_v2_01_portal_discovery.py`

Files changed:

- `.env.example`
- `app/config.py`
- `app/services/runtime_settings.py`
- `app/services/search_queries.py`
- `docs/v2/IMPLEMENTATION_STATUS.md`

Dependencies added: none.

Focused verification:

- `.venv/bin/pytest -q tests/module/test_v2_01_portal_discovery.py` — 31 passed.
- `.venv/bin/pytest -q tests/module/test_m05_discovery.py` — 4 passed.
- `.venv/bin/pytest -q tests/module/test_v2_01_portal_discovery.py tests/module/test_m05_discovery.py` after the bounded-target review adjustment — 35 passed.
- Targeted Python compilation for the four changed application modules — passed.
- Default setting assertion for `portal_search_max_queries_per_run=18` — passed.
- `git diff --check` and trailing-whitespace checks for the new files — passed.

Acceptance result:

- PASS — all three portals receive deterministic, bounded queries derived from existing roles, synonyms, locations, and Remote preferences.
- PASS — the existing `WebSearchProvider` is the sole network abstraction.
- PASS — valid LinkedIn, Naukri, and Indeed job-detail results produce normalized partial candidates with stable source identities and original URLs.
- PASS — non-job portal pages, missing-employer titles, malformed identities, and spoofed hosts are rejected.
- PASS — one portal's search failures do not prevent successful results from the other portals.
- PASS — an unconfigured search provider returns bounded source errors without attempting network calls.
- PASS — company discovery continues rejecting LinkedIn, Naukri, and Indeed results.
- PASS — no job/company persistence or schema change was introduced.
- PASS — no browser, login, CAPTCHA/access-control bypass, scraping, or new dependency was introduced.

Issues/deviations/blockers:

- No deviation from the approved V2-M01 plan and no blocker before V2-M02.
- Live provider yield was intentionally not tested because deterministic fixtures are the acceptance evidence and live indexing is variable.
- The complete project suite was intentionally not run under the V2 testing policy.

## Reuse vs New-Code Matrix

| Concern | Reuse | Minimal new work |
|---|---|---|
| Profiles/roles/locations | Existing profile model/repository and ordered query inputs | Portal query formatting and round-robin cap |
| Network search | Existing `WebSearchProvider` and Brave adapter | None |
| Company discovery | Existing service and blocked-host list unchanged | Regression assertion only |
| Portal recognition | Existing `WebSearchResult` | Strict parser/query logic in `PortalDiscoveryService` |
| Canonical jobs | Existing `jobs` table, normalization helpers, repository, upsert service | Nullable registry relation, company display/completeness/cross-source fields |
| Alternate origins | Canonical job ID and URLs | One bounded `portal_job_sources` child table |
| Deduplication | Existing source ID, URL, and description-fingerprint precedence | One conservative cross-source signature and ambiguity guard |
| Lifecycle | Existing lifecycle for complete company sources | Portal searches refresh seen time only; no absence inference |
| Qualification/matching | Existing deterministic service, AI provider, match row, and rescore hash | Evidence gate plus one constrained partial prompt/validation branch, deterministic score penalty/cap, and full-data rescore |
| Dashboard/detail/state | Existing server-rendered services/routes/templates, queue, and job state | Small completeness/source presentation, full-before-partial tie-break, and optional company handling |
| Scheduler | Existing controller, APScheduler, overlap lock | One portal stage inside the shared pipeline |
| Logs | Existing run/source models and nullable company ID | Emit LinkedIn/Naukri/Indeed source snapshots |
| Telegram | Existing service/log, threshold, and job-ID event keys | Remove mandatory Company join; label partial recommendations and preserve delivery idempotency through enrichment |
| Backup | Existing complete SQLite archive | Recognize current schema/table and migrate supported staged V1 backups |

## Testing Strategy

### V2-M01 focused tests

- Deterministic query order/cap across roles, synonyms, locations, Remote, and all three portals.
- Valid and invalid URL/title/snippet fixtures for LinkedIn, Naukri, and Indeed.
- Explicit rejection of portal landing/search/company/profile/article/help pages.
- Existing `tests/module/test_m05_discovery.py` blocked-host and company-query regression.
- Search provider unconfigured/failure behavior and one-portal isolation with fakes only.

### V2-M02 focused tests

- Fresh migration plus upgrade/downgrade/upgrade and Alembic model check.
- Existing V1 rows backfill as `full` with company names and signatures.
- Existing full match rows survive migration; full-data validation still rejects missing non-salary components, while preliminary persistence accepts null only for unavailable components.
- Portal identity/URL rediscovery updates one observation and one job.
- LinkedIn + Indeed deterministic duplicate produces one canonical visible job and two observations.
- Existing ATS then portal attaches without overwriting full data.
- Portal first then ATS upgrades the same job ID and preserves all application metadata.
- Ambiguous same employer/title/location candidates remain separate.
- Directly affected `test_m12_job_normalization.py`, `test_m13_job_lifecycle.py`, and `test_m18_job_detail_state.py` cases.
- Current-schema backup round trip plus restore/migration of a V1-schema fixture archive.

### V2-M03 focused tests

- One shared manual/scheduled pipeline invokes company discovery, all ATS connectors, and the portal stage under the existing overlap guard.
- Failure of one portal produces bounded source/log failure while other portals and ATS sources continue.
- Partial metadata below the exact evidence threshold remains visible as Not Scored and produces no AI call, match row, queue entry, or notification.
- Eligible partial metadata uses the existing provider once, leaves unavailable components null, never invents missing facts, stores the adjusted score at no more than 89, and labels the result `Partial / Low Confidence`.
- A sufficiently strong adjusted partial score can enter the existing daily queue; an equivalent full result sorts ahead of it, including the equal-score tie case.
- A qualifying partial high-match notification is explicitly marked as a low-confidence partial-data recommendation and uses the unchanged canonical event key.
- Later full enrichment is qualified and rescored once through the normal V1 path on the same job/match row. It preserves state, removes the partial label, and sends either zero duplicate notifications or the first notification when no qualifying partial delivery exists.
- Directly affected M14, M15, M19, M20, and M21 focused cases only.

### V2-M04 focused tests

- Source options contain LinkedIn, Naukri, Indeed, and V1 sources.
- Filtering by a portal returns both portal-canonical jobs and ATS-canonical jobs with that portal observation.
- Partial indicator, low-confidence score label, and snippet warning render in list/detail/queue; Not Scored partial jobs remain distinguishable and full jobs retain V1 presentation.
- Save/Applied/Ignore works on partial jobs and survives full enrichment.
- Recommendation and application notification event keys remain stable after enrichment.
- Existing M16, M17, M18, M20, and M22 directly affected tests.

### V2-M05 final verification

Only after V2-M01 through V2-M04 pass:

1. Run the complete historical V1 module suite and V1 M23 workflow.
2. Run a new fixture-driven workflow containing one existing ATS job, a LinkedIn duplicate, a unique Naukri job, an Indeed duplicate, a partial portal job, one portal failure, application state, full enrichment, and Telegram idempotency.
3. Run migration/model checks, `pip check`, targeted compilation, and `git diff --check`.
4. Keep live provider checks separate and optional; they cannot be the sole acceptance evidence.

No coverage target and no low-value tests are proposed.

## Credentials and Configuration

Required for deterministic development/tests: none.

Required for live portal discovery:

- existing `JOB_AGENT_SEARCH_PROVIDER=brave`
- existing `JOB_AGENT_BRAVE_SEARCH_API_KEY`
- normal outbound HTTPS access

Proposed new non-secret setting:

- `JOB_AGENT_PORTAL_SEARCH_MAX_QUERIES_PER_RUN=18`

The existing optional AI key/model is required for both preliminary partial scoring and normal full scoring. Without it, discovered portal jobs remain available for manual review as Not Scored under the existing AI-unavailable behavior. Existing Telegram token/chat configuration is required only for live notifications. LinkedIn, Naukri, and Indeed credentials are neither required nor accepted by initial V2.

## Risks and Unknowns

- Search-engine coverage, ranking, snippets, and freshness are external and can change. Search-result discovery cannot guarantee portal-complete coverage.
- Portal SEO URL/title formats can change. Strict validation favors safe skips over ingesting irrelevant pages.
- Employer/location text differs across sources (`Bangalore` vs `Bengaluru`, legal suffixes, regional subsidiary names). Conservative normalization will leave some false-negative duplicates.
- Exact employer/title/location can still represent multiple requisitions. The unique-candidate rule avoids merging when ambiguity is visible but cannot prove two externally opaque postings are identical.
- Portal-only records cannot be closed safely from search-result absence. Initial V2 will label their data/availability as unverified, refresh last-seen on rediscovery, and avoid missing-count lifecycle transitions.
- Preliminary scores are intentionally low confidence because search snippets omit material job facts. The strict evidence gate, nullable unavailable components, five-point penalty, 89 cap, explicit label, and full-before-partial tie-break prevent them from being presented as equivalent to full-data matches.
- The fixed 80-character evidence threshold is deterministic but may reject terse useful snippets or admit verbose low-information snippets. Focused fixtures and later observed false-positive/false-negative data should guide any separately reviewed threshold change.
- The new nullable company relationship requires careful migration and regression of inner-join UI/notification paths.
- Search volume rises by the bounded portal cap in addition to V1 company queries, affecting Brave quota/cost.
- Existing V1 backup archives require staged schema migration during restore; failure must leave current data untouched.
- The current documentation relocation is uncommitted and root README links to old top-level doc paths may be stale. This is a repository documentation issue, not a V2 implementation blocker, and should be resolved separately or as part of the approved documentation update without altering frozen content.

## Relative Portal Complexity with Search-Provider Discovery

1. **LinkedIn — Low to medium.** Indexed results commonly expose a stable numeric ID in `/jobs/view/...-{id}` and a structured title containing role, employer, and location. Regional hosts and occasional login walls affect the user's open-link experience but do not require automated login for discovery.
2. **Naukri — Medium.** Indexed job pages expose a trailing numeric identity and often include employer/location in SEO titles, but long and short `job-listings` variants, variable title formatting, and uneven index freshness require more parsing fixtures.
3. **Indeed — Medium to high.** The `jk` identifier in `/viewjob` is stable and easy to recognize, but country domains, redirect/search-page variants, and employer names that are often absent from the page title make reliable search-result-only metadata extraction the hardest of the three.

This ranking concerns metadata extraction through generic search results, not direct portal scraping.

## Browser-Assisted Later Proposal

Browser assistance is not part of the initial V2 plan. If measured live search coverage is inadequate after V2 acceptance, a separately approved, short-lived user-assisted import of explicitly selected public job URLs could be evaluated. It must not automate login, preserve portal cookies, bypass challenges, evade detection, or run a permanent Chromium worker.

## Genuine Blockers

There is no blocker to fixture-driven implementation of the proposed V2.

Live proof of current discovery yield requires a user-supplied Brave Search key and available indexed results, but credentials are not required for implementation or default acceptance tests. If product acceptance later changes from "discover useful indexed portal jobs" to guaranteed or exhaustive live portal coverage, the search-provider approach cannot guarantee that outcome and would require a separate product decision.

## Next Action

Stop after V2-M01. Do not modify persistence or begin V2-M02 until the user explicitly authorizes it.
