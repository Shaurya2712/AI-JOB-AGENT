# V2 Architecture Extension

## Principle
V2 extends V1. Codex must inspect the existing architecture and reuse current abstractions wherever practical.

This document defines boundaries, not exact classes/files.

## New Concept: Portal Discovery
Introduce one clear portal-discovery boundary.

```text
Job Acquisition
│
├── Existing ATS / Career Sources
│
└── Portal Discovery
    ├── LinkedIn
    ├── Naukri
    └── Indeed
```

Outputs should converge into the existing normalization/upsert pipeline.

## Reuse Existing Web Search Provider
V1 already has a web-search provider abstraction.

Reuse it for portal-specific domain searches where possible.

Do not add a second search API abstraction unless the current code makes reuse genuinely inappropriate.

## Suggested Concepts
Possible concepts include:
- PortalJobSource
- PortalSearchResult
- PortalQueryGenerator
- PortalDiscoveryService

These names are not mandatory. Codex should avoid unnecessary abstraction.

## Portal Identity
Every portal-discovered job must retain origin identity, e.g.:

```text
source_type = portal
source_name = linkedin | naukri | indeed
```

If the current model uses different naming, extend it minimally.

## Canonicalization
Portal results should enter existing canonicalization/deduplication.

Potential comparison inputs:
- normalized company
- normalized title
- normalized location
- canonical job URL
- source identifier
- ATS/company-career match
- description/snippet similarity where appropriate

Avoid AI-based deduplication unless deterministic logic proves inadequate.

## Data Quality / Completeness
Portal search results may be incomplete.

Downstream logic needs a minimal way to know this, e.g.:

```text
data_completeness = partial | full
```

Use an equivalent existing concept if already present.

## Matching
Reuse V1 AI-provider and matching logic.

Do not create portal-specific AI providers.

The matching layer must avoid presenting low-information portal snippets as high-confidence full-JD analysis.

Codex should decide the smallest appropriate behavior after inspecting current matching requirements.

## Scheduling
Portal discovery should run through the existing scan/scheduler orchestration.

Do not create a second scheduler.

Prefer one scan pipeline.

## Failure Isolation
Failure of one portal must not stop:
- ATS scans
- company-career scans
- other portal scans

Use existing scan logging wherever possible.

## Resource Constraints
The V1 target still applies:
- Linux laptop
- 8 GB RAM
- about 6 GB free
- single user

Prefer HTTP search APIs, bounded results, incremental processing, existing SQLite, and existing scheduler.

Avoid always-running Chromium.

## Browser Layer
A future browser-assisted capability may use Playwright/Chromium only if separately approved.

If ever added, it should be optional, short-lived, user-assisted, and isolated behind an adapter.

It is not part of current V2 acceptance.
