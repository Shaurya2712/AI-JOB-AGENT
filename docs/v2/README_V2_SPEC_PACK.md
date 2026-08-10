# Job Agent V2 — Portal Discovery Specification Pack

## Purpose
This is a DELTA specification for the completed V1 Job Agent.

It adds:
- LinkedIn job discovery
- Naukri job discovery
- Indeed job discovery

It does not replace the V1 specification.

Keep the existing V1 documentation in the repository.

## Recommended Use
1. Copy these V2 files into the completed V1 repository.
2. Prefer a dedicated folder such as `docs/v2/` if that matches the repo.
3. Commit the V2 docs before changing application code.
4. Give Codex `05_V2_CODEX_REVIEW_PROMPT.md`.
5. Let Codex inspect the actual V1 codebase.
6. Review Codex's implementation plan.
7. Only then authorize implementation.

## Important Design Decision
Initial V2 portal discovery is intended to reuse the existing web-search-provider architecture.

It is not initially based on autonomous Chromium scraping.

A browser-assisted import mechanism can be evaluated later if search-provider discovery proves insufficient, but it is outside this V2 scope unless separately approved.
