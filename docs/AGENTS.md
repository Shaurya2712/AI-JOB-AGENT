# AGENTS.md — Project Instructions

Mission: build the frozen Job Agent V1 quickly and correctly.

Specification Markdown files are authoritative. Never invent features.

Priorities:
1. working end-to-end behavior
2. simplicity
3. reliability
4. low memory/runtime overhead
5. maintainability
6. aesthetics

Target: macOS development; Linux deployment; 8 GB RAM/~6 GB free; browser UI; single user; SQLite; API-based AI providers.

Do not add microservices, Redis, Celery, Kafka, Kubernetes, tenancy, auth/RBAC, billing, auto-apply, RAG/vector DB, permanent headless-browser worker, speculative SaaS systems, or unsupported modules.

Testing: targeted module tests while building. Full-system verification at end. No coverage target.

Git: prefer small module-aligned commits. No unrelated refactors.

UI: reference-inspired minimal editorial theme; function before decoration.

External sources: public/structured where practical. No CAPTCHA/login/access-control/anti-bot bypass.

Secrets: never commit or print credentials.

Maintain README, .env.example, and docs/IMPLEMENTATION_STATUS.md.
