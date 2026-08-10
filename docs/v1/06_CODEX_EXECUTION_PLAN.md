# Codex Execution Plan

Codex is the primary coding agent. Specification files are authoritative.

Read order:
1. 00_PRODUCT_SCOPE.md
2. 01_TECHNICAL_ARCHITECTURE.md
3. 02_DATA_MODEL.md
4. 03_MODULES_AND_ACCEPTANCE.md
5. 04_TESTING_POLICY.md
6. 05_UI_UX_REFERENCE_THEME.md
7. AGENTS.md

Work M01 -> M22 exactly in order.

For each module:
1. inspect current code
2. state smallest implementation plan
3. implement only that module
4. run focused tests only
5. fix failures
6. verify acceptance
7. update docs/IMPLEMENTATION_STATUS.md
8. make clean module-aligned commit if git available
9. continue

Do not ask approval between modules unless blocked by missing credentials, irresolvable ambiguity, external service requirement, or destructive migration risk.

Make the app usable as early as possible. Expose working collected data in the dashboard once the first connector + normalization/dedupe path is viable; do not wait for all connectors.

No scope creep: no auth, Docker unless genuinely needed for final Linux run, distributed queues, auto-apply, cover letters, recruiter messages, interview tracking, extra analytics, speculative abstractions.

Dependency rule: add only if required by explicit V1 behavior and justified against standard library/existing deps/runtime cost.

External integrations need timeouts and isolated failure. App starts with zero credentials; features show Not configured.

Use fixtures for module tests, not live ATS sites.

Complete when M01–M22 acceptance pass, M23 passes, README documents macOS/Linux setup, .env.example is complete, secrets are not committed, and no out-of-scope modules exist.
