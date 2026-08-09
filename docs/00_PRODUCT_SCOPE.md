# Job Agent V1 — Frozen Product Scope

## Goal
Build a minimal, fully working browser-based job hunting assistant that starts finding and prioritizing jobs immediately.

Primary outcome: open the dashboard and know which jobs to apply to today.

Initial environment:
- single user
- local-first
- macOS during development
- Linux laptop for regular use
- 8 GB RAM, about 6 GB free after boot

Future SaaS expansion should remain possible through clean boundaries, but V1 must not add SaaS functionality.

## Non-negotiable rules
1. Working discovery is more important than architectural sophistication.
2. Do not add features outside this specification.
3. No microservices.
4. No Redis, Kafka, Celery, Kubernetes, distributed queues, or local LLM.
5. No authentication/RBAC in V1.
6. No auto-apply.
7. No CAPTCHA/login/access-control bypass.
8. Prefer public/structured ATS data when practical.
9. Generic career-page crawling is best-effort only.
10. Module-focused tests during development; one full-system verification at the end.
11. No arbitrary code-coverage target.

## Candidate Profiles
Support multiple profiles. Each profile stores:
- name
- active/inactive
- target roles
- role synonyms
- skills
- years of experience
- preferred locations
- work modes
- minimum salary preference
- excluded keywords
- notes
- AI suggestions pending approval

Default target roles:
- Flutter Developer
- React Native Developer
- React Developer
- Software Developer
- AI Developer
- Software Engineer — Mobile App Development

Role synonyms should include relevant variants such as Mobile Developer, Mobile Engineer, Software Engineer — Mobile, Cross-platform Developer, Application Developer, and Frontend Mobile Engineer.

AI may suggest new roles/skills but never alter a profile automatically.

## Multiple Resumes
Each profile may have multiple resumes, including a primary resume. Store file reference, extracted text, and AI suggestions. No automatic resume submission.

## Location Behavior
Jobs may be India, India + Remote, specific Indian cities, or worldwide remote. This is controlled by dashboard filters. Onsite roles anywhere in India may appear.

## Company Discovery
Start from a seed company dataset and expand automatically. The app must discover companies/career pages through web search, detect ATS providers, store discoveries permanently, and reuse them in future scans.

Store: company, website, career URL, ATS/provider, discovery source, active flag, last scan, last successful scan, job count.

No company blacklist in V1.

## Job Sources
Pluggable connectors. Priority connectors:
1. Greenhouse
2. Lever
3. Ashby
4. Workday

Recognize iCIMS, BambooHR, and custom pages where practical. Unsupported sources are recorded and skipped safely. Generic HTML career-page collector is best-effort fallback.

## Web Search
Use a search-provider abstraction. Only one working search provider is required initially; others are adapters. Search queries are generated from active profiles, synonyms, and locations.

## Job Discovery
Discover all currently open jobs regardless of posting age. Refresh over time to determine whether they remain open.

## Normalized Job
Minimum fields:
- id
- source
- source_job_id
- company
- title
- location
- remote status
- employment type
- description
- job URL
- salary min/max/currency if known
- required experience if known
- extracted skills
- posted_at if known
- discovered_at
- last_seen_at
- lifecycle status

## Deduplication
Permanently avoid repeatedly surfacing the same job. Use source identity, canonical URL, company/title/location, and content fingerprint where necessary. Rediscovery updates last_seen_at rather than creating duplicates or resending first-time alerts.

## Lifecycle
States: open, possibly_closed, closed.
- missing once -> keep open
- missing on multiple consecutive successful scans -> possibly_closed
- explicit unavailable/closed -> closed
- repeated confirmed absence -> closed

Closed jobs hidden by default. Materially changed jobs are updated and rescored while preserving user state.

## Qualification
Run cheap deterministic qualification before AI.
Exclude internships, unrelated roles, obvious unrealistic experience requirements, and management-only roles when inappropriate.

Do not blindly exclude Senior or Lead. Experience matching is flexible. Partial-skill matches remain visible.

## AI Provider Abstraction
All LLM work behind a provider interface. Expected adapters: OpenAI, Anthropic, Gemini, plus future adapters.

AI responsibilities:
- relevance/match scoring
- role/title fit
- skills fit
- experience fit
- location fit
- salary fit when available
- required vs preferred skills
- seniority fit
- explanation
- profile role/skill suggestions

Use validated structured output. Malformed responses must not crash a scan.

## Match Scoring
Factors:
- skills
- role/title
- experience
- location
- freshness
- required vs preferred skills
- seniority
- salary when available

Salary missing does not reject a job. A matching but low-salary job stays visible with reduced priority.

Labels:
- 90–100 Excellent
- 85–89 Strong
- 75–84 Review
- below 75 Low Priority

Default Telegram instant threshold: 85, configurable.

## User Job State
- New
- Saved
- Applied
- Ignored

Applied may store applied_at, selected resume, and optional note. No interview/offer pipeline in V1.

## UI Theme
The browser interface must use the visual direction defined in `05_UI_UX_REFERENCE_THEME.md`.

Primary visual reference:
`https://168hd5iyr2czx.space.minimax.io/`

The previous Solarized Light direction is superseded. Functional scope must not expand because of this visual change.

## Dashboard
Reference-Inspired Minimal Editorial Theme browser dashboard. It must answer:
- what should I apply to today?
- what new jobs were found?
- what have I applied to?
- are scans healthy?

Primary cards: Apply Today, Strong Matches, New Jobs, Applied, Scan Health.

Filters: profile, role, score, location mode, city, source, lifecycle, New/Saved/Applied/Ignored, salary, remote, posted/discovered date.

## Daily Action Queue
Configurable target, default 10. Rank strongest open not-applied/not-ignored jobs.

## Job Detail
Show title, company, location, source, original URL, description, salary, score breakdown, matching skills, missing skills, concerns, explanation, linked profile, suggested resume, user state.
Actions: Open Original Job, Save, Mark Applied, Ignore.

## Scheduler
Default every 4 hours, configurable. Runs only while app process is running. Provide Search Now. Prevent overlapping scans. No OS boot integration in app.

## Telegram
Notification only. Support three configurable destinations:
1. High-match recommendations
2. Application activity
3. Search/run summaries

High-match sends newly discovered jobs >= threshold. Application chat may notify when user marks Applied. Summary chat sends source/job/error counts after each run. Avoid duplicate notifications.

## Backup
Export/Import one backup containing settings, profiles, resume data, companies, jobs, match results, statuses, and application history.

## Logs
Lightweight scan/source logs: start/end, success/failure, jobs fetched/new/updated, errors, retries.

## Explicitly Out of Scope
- auth/RBAC/multi-tenancy
- billing/subscriptions
- SaaS deployment workflow
- mobile app
- auto-apply/form filling
- CAPTCHA/login/access-control bypass
- prohibited portal scraping
- interview/recruiter CRM
- cover-letter generator
- recruiter-message generator
- full resume rewrite engine
- company blacklist
- vector DB/RAG
- Redis/Celery/Kafka/microservices
- complex CI/CD
- arbitrary analytics
- any feature not explicitly listed above
