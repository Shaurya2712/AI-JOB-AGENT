# Master Codex Prompt

You are the primary implementation agent for this project.

Build the complete Job Agent V1 defined by the repository specification.

Before coding, read completely:
1. 00_PRODUCT_SCOPE.md
2. 01_TECHNICAL_ARCHITECTURE.md
3. 02_DATA_MODEL.md
4. 03_MODULES_AND_ACCEPTANCE.md
5. 04_TESTING_POLICY.md
6. 05_UI_UX_REFERENCE_THEME.md
7. 06_CODEX_EXECUTION_PLAN.md
8. 08_LOCAL_LINUX_RUNBOOK.md
9. 09_SECURITY_AND_EXTERNAL_ACCESS.md
10. AGENTS.md

Treat them as frozen scope. If any appear to conflict, prefer the narrower explicit product requirement and the smallest implementation that satisfies the user outcome; record the decision in docs/IMPLEMENTATION_STATUS.md. Do not invent functionality.

Core objective: make the application usable for real job hunting as early as possible while completing full V1. Working discovery beats polish; reliability beats abstraction; no unnecessary tests or infrastructure.

Default architecture: Python, FastAPI, Jinja2, HTMX, SQLite, SQLAlchemy, Alembic, APScheduler, httpx, lightweight HTML parser, provider abstractions for AI/web search, Telegram Bot API, reference-inspired minimalist editorial UI.

Do not convert to microservices, a separate SPA/API split, Redis/Celery, Docker orchestration, local LLM, or SaaS platform unless existing repository constraints already make a specific change unavoidable.

Implement M01 through M22 in order. After each module: focused tests only, fix, acceptance verify, update IMPLEMENTATION_STATUS.md, small git commit if appropriate. Full verification only at M23.

External provider features must fail gracefully and application must start with zero keys configured. Never commit credentials.

Only stop for user input if genuinely blocked by missing credential or a decision impossible to infer safely. Do not re-ask settled questions.

Before adding anything, verify it exists in frozen scope. If not, do not add it.

First action:
1. inspect repository
2. read all specs
3. create docs/IMPLEMENTATION_STATUS.md with M01–M22 Pending
4. identify exact planned dependency set
5. record real blockers
6. begin M01

Continue module-by-module until complete or genuinely externally blocked.
