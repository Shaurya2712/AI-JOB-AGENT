# V2 Acceptance and Testing

## Testing Policy
V1 testing philosophy remains unchanged.

During V2 development:
- test the area/module currently being changed
- test directly affected V1 behavior
- do not run the full project suite after every edit
- do not chase arbitrary coverage
- do not add low-value tests

At the end, run full V1 + V2 regression/final verification.

## Required Focused Test Areas
At minimum:
1. portal-specific query generation
2. LinkedIn result recognition/filtering
3. Naukri result recognition/filtering
4. Indeed result recognition/filtering
5. company-discovery blocked-host behavior remains correct
6. portal results are not treated as company career pages
7. portal result normalization
8. portal/full ATS duplicate handling
9. portal/portal duplicate handling where deterministic match exists
10. application state preservation during enrichment
11. notification idempotency
12. incomplete-data behavior in matching/UI
13. one portal failure does not break other scan sources

Use deterministic fixtures/mocks for normal tests.

Default tests must not depend on live LinkedIn/Naukri/Indeed pages.

## Functional Acceptance Criteria
V2 is complete when:
- LinkedIn jobs can be discovered through the approved portal-discovery mechanism
- Naukri jobs can be discovered through the approved portal-discovery mechanism
- Indeed jobs can be discovered through the approved portal-discovery mechanism
- portal discovery is separate from company discovery
- existing ATS connectors still work
- portal jobs enter the same canonical job system
- duplicate visible jobs are minimized across portals and ATS sources
- application state survives source enrichment
- Telegram does not repeatedly notify the same canonical opportunity
- existing filters continue working
- source filters include all three portals
- incomplete portal jobs are not presented as full-confidence JD matches
- scheduler/manual scan integrates portal discovery
- V1 remains regression-safe

## Final V2 Verification
After implementation, Codex should create and execute the final verification plan based on the actual codebase.

It should include realistic fixture-driven cases for:

```text
existing ATS job
+
LinkedIn duplicate
+
Naukri unique job
+
Indeed duplicate
+
partial portal result
+
portal failure
+
application state
+
Telegram idempotency
```

Live checks may be run separately if providers permit, but they must not be the sole proof of correctness.
