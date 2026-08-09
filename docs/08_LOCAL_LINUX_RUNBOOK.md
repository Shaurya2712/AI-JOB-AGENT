# Local and Linux Runbook

Development: macOS, Python 3.12+, SQLite, browser dashboard.

Linux target: 8 GB RAM, ~6 GB available, single user.

Recommended runtime: one FastAPI process + in-process APScheduler + SQLite.

When moved permanently to Linux, use a small systemd service to keep it running after reboot/login. Systemd is deployment configuration, not app functionality.

Scheduler only runs while app process is running. On start it begins using stored interval; Search Now is always available.

Resource rules: bounded source/AI concurrency, batches, pagination, SQLite WAL, no persistent headless browser, no local model, no Redis/workers.

Backup archive must be portable from Mac development to Linux machine.
