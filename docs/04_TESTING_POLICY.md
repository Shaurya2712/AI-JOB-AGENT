# Testing Policy

## During Development
For each module:
1. implement module
2. run only smallest useful tests for that module/direct dependencies
3. fix
4. verify acceptance
5. update implementation status
6. move on

Do not run the whole suite after every edit.

## High-Value Test Areas
- connector contract
- ATS detection
- normalization
- deduplication
- lifecycle
- deterministic qualification
- AI structured parsing
- AI persistence
- DB upsert/state persistence
- scheduler overlap guard
- notification idempotency
- backup/restore

## Do Not Waste Time Testing
Unless driven by a real bug:
- getters/setters
- constants
- CSS/theme values
- framework internals
- trivial schema declarations
- obvious one-line CRUD wrappers
- trivial template rendering
- third-party library behavior
- exhaustive irrelevant edge cases

## Coverage
No arbitrary percentage. Never add tests solely to raise coverage.

## Fixtures
Use deterministic local fixtures for ATS tests. Live external websites are not part of the default module test command.

## Final Test
Run full workflow only after all modules pass focused tests.

## Bug Rule
For a real bug, add the smallest useful regression test when practical, fix it, and do not expand unrelated testing.
