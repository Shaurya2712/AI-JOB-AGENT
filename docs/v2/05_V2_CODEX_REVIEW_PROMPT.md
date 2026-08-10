# Codex Prompt — V2 Repository Review and Implementation Planning

V1 of this Job Agent is already implemented.

I now want to add V2 job discovery support for:
- LinkedIn
- Naukri
- Indeed

The repository now contains V2 specification documents.

Before making ANY code changes, inspect the existing V1 implementation and read the V2 documents completely.

Read:
1. the existing V1 specification and AGENTS.md
2. `00_V2_SCOPE.md`
3. `01_V2_ARCHITECTURE_EXTENSION.md`
4. `02_V2_DATA_AND_DEDUP.md`
5. `03_V2_PORTAL_BEHAVIOR.md`
6. `04_V2_ACCEPTANCE_AND_TESTING.md`

## Important
Do NOT start implementation yet.

The V2 documents define requirements and constraints, but intentionally do not prescribe a detailed implementation plan.

Derive the implementation plan from the ACTUAL V1 codebase.

## Inspect and determine
- how V1 company discovery works
- how the web-search provider abstraction works
- how blocked hosts are handled
- how ATS sources are represented
- how jobs are normalized/persisted
- how deduplication works
- how lifecycle/closed-job handling works
- how AI matching works
- how incomplete job data is handled, if at all
- how scan scheduling/orchestration works
- how Telegram idempotency works
- how job source filters are implemented
- which abstractions can be reused
- which minimal schema changes are genuinely needed
- which minimal new services/classes/modules are genuinely needed
- which existing tests protect affected areas

Then produce the smallest safe V2 implementation plan.

## Architectural requirement
V2 must add a separate portal-discovery path.

Do NOT simply remove LinkedIn/Naukri/Indeed from company-discovery blocked hosts.

Conceptually:

```text
Company discovery
LinkedIn/Naukri/Indeed
→ remain non-company sources

Portal job discovery
LinkedIn/Naukri/Indeed
→ accepted intentionally
```

Reuse the existing `WebSearchProvider` abstraction where appropriate.

## Browser automation
Do NOT assume Playwright/Chromium scraping is required.

Initial V2 should prefer search-provider-based portal discovery.

Do not introduce:
- automated portal login
- CAPTCHA bypass
- stealth browser tooling
- proxy rotation
- account rotation
- fingerprint evasion
- permanent Chromium workers

If you believe a browser-assisted feature may later be useful, report it only as an optional later proposal with reasons. Do not include it in the initial V2 implementation unless separately approved.

## Reuse
Reuse all existing V1 functionality wherever possible:
- profiles
- role synonyms
- search provider
- normalized jobs
- SQLite
- deduplication
- AI providers
- matching
- dashboard
- filters
- scheduler
- Telegram
- application state
- logs

Do not duplicate these systems.

Do not add unrelated features.

## Testing
Follow existing V1 testing policy plus `04_V2_ACCEPTANCE_AND_TESTING.md`.

During implementation, use targeted tests for the area currently changing.

Run full V1 + V2 regression/final verification only after V2 implementation is complete.

## Deliverable for this first pass
Do NOT code.

Return:
1. Current V1 architecture findings relevant to V2
2. Exact files/modules V2 will likely touch
3. Proposed minimal architecture changes
4. Proposed schema changes, if any
5. Proposed V2 phases/modules derived from the codebase
6. Reuse vs new-code matrix
7. Risks/unknowns
8. Testing strategy
9. Credentials/configuration needed
10. Genuine blockers
11. Relative complexity of LinkedIn vs Naukri vs Indeed using the proposed search-provider approach

Create/update a V2 implementation-status/planning document in `docs/` if that matches the repository's documentation style.

Stop after producing the plan.

Do not begin implementation until I review the plan.
