# V2 Data and Deduplication Requirements

## Goal
Integrate portal jobs without duplicating V1's job model or losing application history.

Codex must inspect current models/migrations before making schema changes.

Only add fields/tables that are genuinely needed.

## Minimum Portal Metadata
A portal-discovered job may include:
- portal/source name
- portal job URL
- title
- company
- location
- snippet/short description
- source job identifier if available
- discovered timestamp
- data completeness
- search context if useful for debugging

Do not store large unbounded provider payloads unless consistent with V1 practices.

## Canonical Job
The existing V1 job record remains the canonical visible job entity.

Do not create a separate permanent portal-job system that bypasses the normal job pipeline.

## Duplicate Handling

### Case A
Greenhouse finds a job. LinkedIn later finds the same role.

Expected:
- one visible job
- full ATS/company source stays canonical
- portal may be recorded as an alternate source if useful
- no duplicate Telegram "new job" notification

### Case B
LinkedIn finds a job first. Workday later finds the full role.

Expected:
- enrich/update the canonical job when confidently matched
- preserve Saved/Applied/Ignored
- prefer better-quality full JD
- rescore if material content changed

### Case C
LinkedIn and Indeed both find the same job with no ATS copy.

Expected:
- avoid duplicate visible rows when confidently equivalent
- preserve useful original source links/metadata

## Application State Preservation
Portal enrichment/deduplication must never reset:
- Saved
- Applied
- Ignored
- applied_at
- selected resume
- notes

## Notification Idempotency
If a canonical job already generated its new strong-match notification, discovery through another source must not trigger the same notification again.

Reuse V1 notification idempotency.

## Data Completeness
The system should distinguish:

```text
partial
full
```

or an equivalent existing concept.

Codex should define the exact threshold based on current V1 matching input requirements.
