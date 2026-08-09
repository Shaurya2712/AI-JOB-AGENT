# Prime Agent Usage

## Decision
Do not embed Prime Agent into the Job Agent product. Use it only as a development accelerator alongside Codex.

Prime Agent is appropriate for long-running repository work, parallel research/review, persistent goals, resumable sessions, and targeted verification.

## Role Split
### Codex — primary implementer
Sequential modules, edits, migrations, focused tests, defects, final integration.

### Prime Agent — secondary accelerator
Bounded independent tasks: ATS research, connector investigation, completed-module review, provider comparison, fixture research, resource/performance review.

Never let Codex and Prime Agent edit the same files concurrently.

## Safest Workflow
Prime Agent initially works read-only/research and writes to `docs/research/` or `docs/reviews/`. Codex consumes findings.

For independent coding, use a separate git worktree/branch and review the diff before merge.

## Suggested Research Prompt
Read frozen spec and AGENTS.md. Do not modify application code. Research the minimal reliable implementation approach for Greenhouse, Lever, Ashby, and Workday using public/structured endpoints where practical. For each: endpoint/data strategy, provider identifier extraction, pagination, rate/error behavior, normalization mapping, limitations. Write only docs/research/ats-connectors.md. No extra features/dependencies.

## Suggested Module Review Prompt
Review module M12 against 03_MODULES_AND_ACCEPTANCE.md and 04_TESTING_POLICY.md. Do not refactor unrelated code. Report only acceptance violations, correctness bugs, duplicate/data-loss risks, and missing critical tests to docs/reviews/M12-review.md.

## Suggested Resource Review Prompt
Review for an 8 GB Linux laptop with ~6 GB free. Focus on idle/scan memory, concurrency, unbounded collections, background processes, SQLite contention. Do not redesign architecture. Write docs/reviews/resource-review.md.

## Use These Prime Agent Capabilities
- AGENTS.md project instructions
- API-key providers
- resumable sessions
- bounded subagents for parallel research/review
- persistent goals for bounded long tasks

## Avoid Initially
- autonomous multi-agent editing over the whole repo
- broad self-refinement loops
- scheduled development changes
- many parallel coding subagents

Use Prime Agent only when it reduces a blocking task; stop if coordination overhead exceeds the gain.
