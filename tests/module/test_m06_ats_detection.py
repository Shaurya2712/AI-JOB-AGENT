from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import Settings
from app.db import create_database_engine, create_session_factory, run_migrations
from app.models.companies import Company
from app.services.ats_detection import AtsDetectionService, AtsUrlDetector


@pytest.mark.parametrize(
    ("url", "provider_type", "identifier"),
    [
        ("https://boards.greenhouse.io/acme/jobs/123", "greenhouse", "acme"),
        (
            "https://job-boards.eu.greenhouse.io/embed/job_board?for=acme-eu",
            "greenhouse",
            "acme-eu",
        ),
        (
            "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
            "greenhouse",
            "acme",
        ),
        ("https://jobs.lever.co/acme/abc-123", "lever", "acme"),
        ("https://api.eu.lever.co/v0/postings/acme", "lever", "acme"),
        ("https://jobs.ashbyhq.com/Acme/abc-123", "ashby", "Acme"),
        (
            "https://api.ashbyhq.com/posting-api/job-board/Acme",
            "ashby",
            "Acme",
        ),
        (
            "https://acme.wd5.myworkdayjobs.com/en-US/External_Careers/job/Pune/123",
            "workday",
            "acme/External_Careers",
        ),
        (
            "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/External/jobs",
            "workday",
            "acme/External",
        ),
    ],
)
def test_supported_ats_fixture_urls_classify(
    url: str,
    provider_type: str,
    identifier: str,
) -> None:
    detection = AtsUrlDetector().detect(url)

    assert detection.provider_type == provider_type
    assert detection.provider_identifier == identifier
    assert detection.provider_supported is True
    assert detection.skip_reason is None


@pytest.mark.parametrize(
    ("url", "provider_type", "identifier", "reason_fragment"),
    [
        (
            "https://jobs-acme.icims.com/jobs/search",
            "icims",
            "jobs-acme",
            "unsupported",
        ),
        (
            "https://acme.bamboohr.com/careers",
            "bamboohr",
            "acme",
            "unsupported",
        ),
        (
            "https://careers.acme.example/openings",
            "custom",
            "careers.acme.example",
            "generic career-page fallback",
        ),
        ("javascript:alert(1)", "unknown", None, "invalid or missing"),
        ("https://jobs.lever.co", "lever", None, "missing provider identifier"),
    ],
)
def test_unsupported_and_invalid_fixture_urls_are_safe_to_skip(
    url: str,
    provider_type: str,
    identifier: str | None,
    reason_fragment: str,
) -> None:
    detection = AtsUrlDetector().detect(url)

    assert detection.provider_type == provider_type
    assert detection.provider_identifier == identifier
    assert detection.provider_supported is False
    assert detection.skip_reason is not None
    assert reason_fragment in detection.skip_reason


def test_classification_persists_state_and_returns_only_connector_ready_sources(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "m06.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        company_seed_path=tmp_path / "unused-seed.json",
        resume_storage_path=tmp_path / "resumes",
    )
    run_migrations(settings)
    engine = create_database_engine(settings.database_url)
    session = create_session_factory(engine)()
    scanned_at = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)
    successful_at = datetime(2026, 8, 9, 10, 1, tzinfo=timezone.utc)

    try:
        session.add_all(
            [
                Company(
                    name="Greenhouse Co",
                    website_url="https://greenhouse.example",
                    careers_url="https://boards.greenhouse.io/greenhouse-co",
                    discovery_source="web:fake",
                    is_active=True,
                    provider_supported=False,
                    last_scanned_at=scanned_at,
                    last_success_at=successful_at,
                    total_jobs_seen=19,
                ),
                Company(
                    name="iCIMS Co",
                    website_url="https://icims.example",
                    careers_url="https://jobs-icims-co.icims.com/jobs/search",
                    discovery_source="web:fake",
                    is_active=True,
                    provider_supported=False,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Custom Co",
                    website_url="https://custom.example",
                    careers_url="https://custom.example/careers",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=False,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Stored Lever Co",
                    website_url="https://stored-lever.example",
                    careers_url="https://stored-lever.example/careers",
                    provider_type="Lever",
                    provider_identifier="stored-lever",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=False,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Inactive Ashby Co",
                    website_url="https://inactive.example",
                    careers_url="https://jobs.ashbyhq.com/inactive",
                    discovery_source="seed",
                    is_active=False,
                    provider_supported=False,
                    total_jobs_seen=0,
                ),
            ]
        )
        session.commit()

        service = AtsDetectionService(session)
        first = service.classify_active_companies()
        second = service.classify_active_companies()

        assert first.companies_checked == 4
        assert first.supported_companies == 2
        assert first.skipped_companies == 2
        assert second.companies_checked == 4

        connector_input = [
            decision.company_name
            for decision in first.decisions
            if decision.should_use_connector
        ]
        skipped_input = [
            decision.company_name
            for decision in first.decisions
            if not decision.should_use_connector
        ]
        assert connector_input == ["Greenhouse Co", "Stored Lever Co"]
        assert skipped_input == ["Custom Co", "iCIMS Co"]
        assert all(
            decision.skip_reason is not None
            for decision in first.decisions
            if not decision.should_use_connector
        )

        companies = {
            company.name: company for company in service.repository.list_companies()
        }
        assert companies["Greenhouse Co"].provider_type == "greenhouse"
        assert companies["Greenhouse Co"].provider_identifier == "greenhouse-co"
        assert companies["Greenhouse Co"].provider_supported is True
        assert companies["Greenhouse Co"].last_scanned_at is not None
        assert companies["Greenhouse Co"].last_success_at is not None
        assert companies["Greenhouse Co"].total_jobs_seen == 19
        assert companies["iCIMS Co"].provider_type == "icims"
        assert companies["iCIMS Co"].provider_supported is False
        assert companies["Custom Co"].provider_type == "custom"
        assert companies["Custom Co"].provider_supported is False
        assert companies["Stored Lever Co"].provider_type == "lever"
        assert companies["Stored Lever Co"].provider_supported is True
        assert companies["Inactive Ashby Co"].provider_type is None
    finally:
        session.close()
        engine.dispose()
