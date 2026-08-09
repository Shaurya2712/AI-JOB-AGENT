import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx
from sqlalchemy import select

from app.config import DEFAULT_COMPANY_SEED_PATH, Settings
from app.main import create_app
from app.models.companies import Company
from app.services.companies import CompanyService


def build_test_app(database_path: Path, seed_path: Path):
    return create_app(
        Settings(
            environment="test",
            database_url=f"sqlite:///{database_path.as_posix()}",
            log_level="WARNING",
            company_seed_path=seed_path,
            resume_storage_path=database_path.parent / "resumes",
        )
    )


def write_seed(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "name": "Alpha",
                    "website_url": "https://alpha.example/",
                    "careers_url": "https://alpha.example/careers/",
                    "provider_type": "greenhouse",
                    "provider_identifier": "alpha-board",
                    "provider_supported": True,
                },
                {
                    "name": "Beta",
                    "website_url": "https://beta.example",
                    "careers_url": None,
                    "is_active": False,
                },
            ]
        ),
        encoding="utf-8",
    )


def test_bundled_seed_loads_and_companies_page_renders(tmp_path: Path) -> None:
    application = build_test_app(tmp_path / "companies.db", DEFAULT_COMPANY_SEED_PATH)

    async def scenario() -> None:
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/companies")

            assert response.status_code == 200
            assert "Company Registry" in response.text
            assert "BrowserStack" in response.text
            assert "Chargebee" in response.text
            assert "Freshworks" in response.text
            assert "Meesho" in response.text
            assert "Postman" in response.text
            assert "Razorpay" in response.text
            assert "Pending detection" in response.text

            with application.state.session_factory() as session:
                companies = list(session.scalars(select(Company).order_by(Company.name)))
                assert len(companies) == 6
                assert all(company.discovery_source == "seed" for company in companies)
                assert all(company.is_active for company in companies)
                assert all(company.provider_type is None for company in companies)
                assert all(company.last_scanned_at is None for company in companies)
                assert all(company.last_success_at is None for company in companies)
                assert all(company.total_jobs_seen == 0 for company in companies)

    asyncio.run(scenario())


def test_seed_import_is_idempotent_and_preserves_scan_metadata(tmp_path: Path) -> None:
    seed_path = tmp_path / "companies.json"
    database_path = tmp_path / "companies.db"
    write_seed(seed_path)

    first_application = build_test_app(database_path, seed_path)

    async def first_start() -> None:
        async with first_application.router.lifespan_context(first_application):
            with first_application.state.session_factory() as session:
                companies = list(session.scalars(select(Company).order_by(Company.name)))
                assert len(companies) == 2
                alpha, beta = companies
                assert alpha.website_url == "https://alpha.example"
                assert alpha.careers_url == "https://alpha.example/careers"
                assert alpha.provider_type == "greenhouse"
                assert alpha.provider_identifier == "alpha-board"
                assert alpha.provider_supported is True
                assert beta.is_active is False

                alpha.provider_type = "workday"
                alpha.provider_identifier = "alpha-tenant"
                alpha.last_scanned_at = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)
                alpha.last_success_at = datetime(2026, 8, 9, 10, 1, tzinfo=timezone.utc)
                alpha.total_jobs_seen = 17
                session.commit()

    asyncio.run(first_start())

    second_application = build_test_app(database_path, seed_path)

    async def second_start() -> None:
        async with second_application.router.lifespan_context(second_application):
            with second_application.state.session_factory() as session:
                result = CompanyService(session).import_seed_file(seed_path)
                companies = list(session.scalars(select(Company).order_by(Company.name)))

                assert result.created == 0
                assert result.existing == 2
                assert len(companies) == 2
                alpha = companies[0]
                assert alpha.provider_type == "workday"
                assert alpha.provider_identifier == "alpha-tenant"
                assert alpha.last_scanned_at is not None
                assert alpha.last_success_at is not None
                assert alpha.total_jobs_seen == 17

    asyncio.run(second_start())
