import asyncio
from pathlib import Path
import sqlite3

import httpx
from sqlalchemy import text

from app.config import Settings
from app.main import create_app


def build_test_app(database_path: Path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        log_level="WARNING",
    )
    return create_app(settings)


async def get(application, path: str) -> httpx.Response:
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path)


def test_dashboard_shell_loads_without_external_credentials(tmp_path: Path) -> None:
    database_path = tmp_path / "foundation.db"

    response = asyncio.run(get(build_test_app(database_path), "/"))

    assert response.status_code == 200
    assert "Job Search Dashboard" in response.text
    assert "Dashboard" in response.text
    assert "Jobs" in response.text
    assert "Profiles" in response.text
    assert "Companies" in response.text
    assert "Scans" in response.text
    assert "Settings" in response.text
    assert "/static/styles.css" in response.text


def test_startup_creates_and_migrates_database_idempotently(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "foundation.db"
    first_health = asyncio.run(get(build_test_app(database_path), "/health"))
    second_health = asyncio.run(get(build_test_app(database_path), "/health"))

    assert first_health.status_code == 200
    assert first_health.json() == {"status": "ok", "database": "ok"}
    assert second_health.json() == {"status": "ok", "database": "ok"}
    assert database_path.is_file()

    with sqlite3.connect(database_path) as connection:
        revisions = connection.execute("SELECT version_num FROM alembic_version").fetchall()

    assert revisions == [("20260810_0011",)]


def test_sqlite_uses_required_connection_pragmas(tmp_path: Path) -> None:
    application = build_test_app(tmp_path / "foundation.db")

    async def read_pragmas() -> tuple[str, int, int]:
        async with application.router.lifespan_context(application):
            with application.state.engine.connect() as connection:
                return (
                    connection.execute(text("PRAGMA journal_mode")).scalar_one(),
                    connection.execute(text("PRAGMA busy_timeout")).scalar_one(),
                    connection.execute(text("PRAGMA foreign_keys")).scalar_one(),
                )

    journal_mode, busy_timeout, foreign_keys = asyncio.run(read_pragmas())

    assert journal_mode == "wal"
    assert busy_timeout == 5000
    assert foreign_keys == 1
