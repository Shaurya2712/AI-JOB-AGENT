# Modules and Acceptance Criteria

Build in this order. A module completes only after its focused test passes.

## M01 Project Foundation
Runnable FastAPI, SQLite, migrations, templates, reference-inspired theme tokens, health endpoint, config, .env.example.
Acceptance: one documented start command; dashboard shell loads; DB created/migrated; UI loads without external credentials.

## M02 Candidate Profiles
Multiple profiles, target roles/synonyms/skills/experience/locations/salary/exclusions/notes, AI suggestions accept/reject.
Acceptance: multiple active profiles allowed; AI suggestion never mutates until approved.

## M03 Resumes
Multiple per profile, local upload, text extraction for needed formats, primary resume.
Acceptance: matching service can read extracted text.

## M04 Company Registry + Seeds
Seed import, company records, provider/career fields, scan metadata.
Acceptance: idempotent seed load.

## M05 Query Generation + Web Discovery
Generate searches from profiles/synonyms/locations; search provider abstraction; one working provider; persist company/career discoveries.
Acceptance: adds companies without duplication; discovery failure does not stop ATS scans.

## M06 ATS Detection
Detect Greenhouse, Lever, Ashby, Workday; recognize iCIMS/BambooHR/custom where practical; unsupported state.
Acceptance: fixture URLs classify correctly; unsupported skips safely.

## M07 Greenhouse Connector
Fetch open jobs, normalize to connector contract, isolate errors.

## M08 Lever Connector
Same contract.

## M09 Ashby Connector
Same contract.

## M10 Workday Connector
Same contract. Keep pragmatic; do not build a universal Workday reverse-engineering platform.

## M11 Generic Career Page Fallback
Best-effort job links/details, strict limits/timeouts, unsupported when unreliable, no access-control bypass.

## M12 Normalization + Deduplication
Canonical schema, URL normalization, source identity, fingerprint, upsert.
Acceptance: rediscovery -> one row; changes update; last_seen_at refreshes.

## M13 Lifecycle
Missing counters, possibly_closed, closed, reset on reappearance.
Acceptance: one missing scan does not close; repeated absence transitions safely; explicit closed may close directly.

## M14 Deterministic Qualification
Exclude internships/unrelated/obvious experience mismatch/management-only; do not blindly reject Senior/Lead; preserve partial-skill matches.

## M15 AI Provider Layer + Matching
Provider abstraction, configured adapters, Pydantic structured output, retry/failure handling, scoring/explanation/resume suggestion/profile suggestions.
Acceptance: malformed provider response does not crash; unchanged job need not rescore.

## M16 Dashboard + Filters
Paginated jobs, key stats, all product filters, score labels.
Acceptance: quickly find 85+ open jobs; applied/ignored and location filters work.

## M17 Daily Action Queue
Configurable target default 10; open relevant unhandled jobs only.

## M18 Job Detail + State
Details, scores, URL, Save/Applied/Ignore, optional applied note/resume.
Acceptance: state persists through rediscovery.

## M19 Scheduler + Search Now
Default 4h configurable; no overlapping scans; manual uses same pipeline; visible run state.

## M20 Telegram
Three destination types; high-match, application activity, scan summary; idempotency.

## M21 Logs / Scan Health
Run history, source failures, counts, recent health.

## M22 Backup / Restore
One archive; restore profiles/jobs/state/settings/resumes.

## M23 Final System Verification
Only after M01–M22 focused tests pass.

End-to-end verify:
1. create profile
2. add resume
3. load seeds
4. run company discovery
5. detect ATS
6. collect each supported connector
7. normalize/dedupe
8. lifecycle
9. qualify
10. AI score
11. dashboard
12. daily queue
13. save
14. mark Applied
15. persistent history
16. second scan no duplicate
17. changed job rescored
18. repeated disappearance lifecycle
19. Telegram recommendation/application/summary
20. backup/restore
21. restart and confirm persisted settings/scheduler behavior

Do not add functionality during final verification except defects against frozen scope.
