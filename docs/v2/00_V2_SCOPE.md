# Job Agent V2 — Portal Discovery Scope

## Purpose
V1 is already implemented and working.

V2 extends the existing Job Agent so jobs can also be discovered from:
- LinkedIn
- Naukri
- Indeed

This is additive scope. Existing V1 behavior must remain intact.

V2 does not replace the ATS/company-career pipeline. The intended source model is:

```text
Existing V1
├── Greenhouse
├── Lever
├── Ashby
├── Workday
└── Generic company career pages

V2
├── LinkedIn portal discovery
├── Naukri portal discovery
└── Indeed portal discovery
```

All sources must continue feeding the existing normalized job database, deduplication, AI matching, dashboard, Telegram notifications, and application tracking.

## Primary V2 Outcome
The system should improve daily job-search coverage by discovering useful opportunities from LinkedIn, Naukri, and Indeed without requiring the user to repeatedly browse all three portals just for discovery.

The dashboard remains the place where jobs are reviewed and manually marked:
- New
- Saved
- Applied
- Ignored

No auto-apply is added.

## Core Integration Strategy
Add a separate Portal Job Discovery path.

Do not make LinkedIn/Naukri/Indeed company-career sources.

```text
Profile
   │
   ├── Existing company discovery
   │       ↓
   │   Company career pages / ATS
   │
   └── Portal job discovery
           ↓
       LinkedIn / Naukri / Indeed

Both
   ↓
Normalized Jobs
   ↓
Deduplication
   ↓
Qualification
   ↓
AI Matching
   ↓
Daily Queue
   ↓
Telegram
```

## Initial Portal Discovery Method
Prefer the existing web-search-provider abstraction.

Portal discovery may generate domain-targeted searches such as:

```text
site:linkedin.com/jobs/view "React Native Developer" India
site:linkedin.com/jobs/view "Mobile Software Engineer" Bangalore

site:naukri.com/job-listings "Flutter Developer"
site:naukri.com/job-listings "React Native" India

site:indeed.com "React Developer" India
site:indeed.com "Mobile Engineer" Remote India
```

Exact query forms should be determined by Codex after inspecting the current implementation and real result patterns.

The V2 specification does not mandate Brave specifically. Reuse the V1 `WebSearchProvider` abstraction.

## Direct Browser Scraping
A permanently running Chromium/Playwright scraper is NOT the default V2 design.

Do not build initial V2 around:
- automated login sessions
- persistent portal cookies
- CAPTCHA solving
- bot-detection evasion
- stealth browser plugins
- account rotation
- proxy rotation
- browser fingerprint manipulation
- automated bypass of access controls

A browser-assisted/manual import capability may be evaluated later only if needed and separately approved. It is not required by V2.

## Portal Job Result
Portal discovery may provide less-complete data than an ATS.

A portal result may initially contain only:
- source portal
- title
- company
- location
- original job URL
- search-result snippet
- discovered_at
- external/source identifier where available

The system must not pretend incomplete portal metadata is a full job description.

## Data Completeness
V2 should distinguish full structured job data from partial portal/search metadata.

If insufficient information exists, the application may:
- provide a lower-confidence match
- provide a preliminary score
- defer full scoring
- clearly indicate partial information

Codex should choose the smallest design that integrates cleanly with V1 matching.

## Source Priority
When the same job is found from multiple sources, prefer the highest-quality canonical source:

```text
Full ATS/company career record
    >
Full authorized portal record
    >
Search-discovered portal metadata
```

Duplicate portal discovery must not create a second visible job when the same role already exists from an ATS/company career page.

## Existing Blocked Hosts
V1 currently blocks job aggregators during company discovery.

That concept remains valid.

```text
Company Discovery
LinkedIn result
→ reject as company source

Portal Job Discovery
LinkedIn result
→ accept as portal job candidate
```

Codex should inspect the current blocked-host implementation and preserve this separation cleanly.

## User Profiles
Portal searches must reuse existing V1 candidate profiles and existing:
- target roles
- role synonyms
- skills where useful
- preferred locations
- remote preferences
- excluded keywords
- experience targeting where practical

Do not create another profile system.

## Locations
Portal discovery must respect existing V1 filtering for:
- India
- India + Remote
- specific Indian cities
- worldwide remote

## Required Portal Sources
- linkedin
- naukri
- indeed

Do not add other portals in this V2.

## Dashboard Integration
Portal jobs must appear in the existing Jobs UI.

Add only minimal source-related UI such as:
- source filter
- source badge
- partial/full data indicator if needed

Do not redesign the dashboard.

## Telegram Integration
Reuse V1 Telegram functionality.

Do not create another notification subsystem.

Do not send repeated notifications for the same canonical job just because it appears on multiple portals.

## Application Tracking
Reuse V1 statuses:
- New
- Saved
- Applied
- Ignored

## Explicitly Out of Scope
V2 does not add:
- auto-apply
- automated form filling
- portal account management
- recruiter messaging
- interview tracking
- cover-letter generation
- browser fingerprint evasion
- CAPTCHA solving
- automated access-control bypass
- proxy rotation
- account rotation
- permanent Chromium worker
- second job database
- second matching engine
- second notification engine
- additional portals beyond LinkedIn/Naukri/Indeed
- SaaS/multi-user functionality
