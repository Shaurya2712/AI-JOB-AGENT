# V2 Agent Rules

These supplement the existing V1 `AGENTS.md`.

Do not replace the existing AGENTS.md blindly.

## Rules
- V1 is complete and must remain working.
- V2 is additive.
- Reuse V1 architecture before creating new abstractions.
- Portal discovery must remain separate from company discovery.
- LinkedIn, Naukri, and Indeed are portal sources, not company career sources.
- Use the existing search-provider abstraction where practical.
- Do not build initial V2 around automated Chromium scraping.
- Do not add portal login automation.
- Do not add CAPTCHA/access-control bypass.
- Do not add proxy/account/fingerprint evasion tooling.
- Do not create a second job database.
- Do not create a second AI matching stack.
- Do not create a second scheduler.
- Do not create a second Telegram subsystem.
- Preserve V1 application state and notification idempotency.
- Prefer deterministic deduplication.
- Treat partial portal metadata as incomplete data.
- Keep RAM/runtime suitable for the existing Linux target.
- During implementation, use focused tests only.
- Run full V1 + V2 regression verification at the end.
- Do not add other portals in this V2.
