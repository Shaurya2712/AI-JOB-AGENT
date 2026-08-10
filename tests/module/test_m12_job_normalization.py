from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.db import create_database_engine, create_session_factory, run_migrations
from app.models.companies import Company
from app.models.jobs import Job
from app.providers.jobs.base import ConnectorJob
from app.services.job_normalization import JobNormalizationError
from app.services.jobs import JobUpsertService


def _open_session(tmp_path: Path):
    database_path = tmp_path / "m12.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        company_seed_path=tmp_path / "unused-seed.json",
        resume_storage_path=tmp_path / "resumes",
    )
    run_migrations(settings)
    engine = create_database_engine(settings.database_url)
    return engine, create_session_factory(engine)()


def _company() -> Company:
    return Company(
        name="Acme",
        website_url="https://acme.example",
        careers_url="https://jobs.acme.example",
        provider_type="greenhouse",
        provider_identifier="acme",
        discovery_source="seed",
        is_active=True,
        provider_supported=True,
        total_jobs_seen=0,
    )


def test_upsert_normalizes_and_rediscovery_refreshes_one_row(tmp_path: Path) -> None:
    engine, session = _open_session(tmp_path)
    first_seen = datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc)
    second_seen = datetime(2026, 8, 9, 13, 0, tzinfo=timezone.utc)

    try:
        company = _company()
        session.add(company)
        session.commit()
        connector_job = ConnectorJob(
            source_type=" GreenHouse ",
            source_job_id=" job-101 ",
            title="  Senior   C++ Engineer  ",
            location_text="  Pune,   India ",
            description="Build reliable systems.\n\n  Ship quality software. ",
            job_url=(
                "HTTPS://Jobs.Acme.Example:443/roles/job-101/"
                "?utm_source=search&b=2&a=1#apply"
            ),
        )

        first = JobUpsertService(session).upsert(
            company.id,
            connector_job,
            seen_at=first_seen,
        )
        second = JobUpsertService(session).upsert(
            company.id,
            connector_job,
            seen_at=second_seen,
        )
        persisted = session.scalar(select(Job))

        assert first.created is True
        assert first.materially_changed is True
        assert second.created is False
        assert second.updated is False
        assert second.materially_changed is False
        assert session.scalar(select(func.count(Job.id))) == 1
        assert persisted is not None
        assert persisted.id == first.job.id == second.job.id
        assert persisted.source_type == "greenhouse"
        assert persisted.source_job_id == "job-101"
        assert persisted.company_id == company.id
        assert persisted.company_name == "Acme"
        assert persisted.data_completeness == "full"
        assert persisted.cross_source_signature is not None
        assert persisted.canonical_url == (
            "https://jobs.acme.example/roles/job-101?a=1&b=2"
        )
        assert persisted.title == "Senior C++ Engineer"
        assert persisted.normalized_title == "senior c++ engineer"
        assert persisted.location_text == "Pune, India"
        assert persisted.description == (
            "Build reliable systems.\nShip quality software."
        )
        assert persisted.description_hash == sha256(
            b"build reliable systems. ship quality software."
        ).hexdigest()
        assert persisted.discovered_at == first_seen.replace(tzinfo=None)
        assert persisted.last_seen_at == second_seen.replace(tzinfo=None)
        assert persisted.lifecycle_status == "open"
        assert persisted.consecutive_missing_scans == 0
        assert persisted.skills_json == []
        assert persisted.city is None
        assert persisted.remote_type is None
    finally:
        session.close()
        engine.dispose()


def test_changes_update_in_place_without_resetting_future_lifecycle_fields(
    tmp_path: Path,
) -> None:
    engine, session = _open_session(tmp_path)
    first_seen = datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc)
    changed_seen = datetime(2026, 8, 9, 15, 0, tzinfo=timezone.utc)

    try:
        company = _company()
        session.add(company)
        session.commit()
        original = ConnectorJob(
            source_type="lever",
            source_job_id="job-202",
            title="Backend Engineer",
            location_text="Remote",
            description="Build backend services for a growing product team.",
            job_url="https://jobs.example.com/jobs/job-202",
        )
        first = JobUpsertService(session).upsert(company.id, original, seen_at=first_seen)
        first.job.lifecycle_status = "possibly_closed"
        first.job.consecutive_missing_scans = 2
        session.commit()

        changed = ConnectorJob(
            source_type="lever",
            source_job_id="job-202",
            title="Senior Backend Engineer",
            location_text="Remote — India",
            description="Build critical backend services and mentor the product team.",
            job_url="https://jobs.example.com/jobs/job-202?ref=careers",
        )
        result = JobUpsertService(session).upsert(
            company.id,
            changed,
            seen_at=changed_seen,
        )

        assert result.job.id == first.job.id
        assert result.created is False
        assert result.updated is True
        assert result.materially_changed is True
        assert result.job.title == "Senior Backend Engineer"
        assert result.job.location_text == "Remote — India"
        assert result.job.description == (
            "Build critical backend services and mentor the product team."
        )
        assert result.job.last_seen_at == changed_seen.replace(tzinfo=None)
        assert result.job.lifecycle_status == "possibly_closed"
        assert result.job.consecutive_missing_scans == 2
        assert session.scalar(select(func.count(Job.id))) == 1
    finally:
        session.close()
        engine.dispose()


def test_canonical_and_fallback_identity_dedupe_and_batch_failure_is_atomic(
    tmp_path: Path,
) -> None:
    engine, session = _open_session(tmp_path)
    observed_at = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)

    try:
        company = _company()
        session.add(company)
        session.commit()
        service = JobUpsertService(session)
        first = service.upsert(
            company.id,
            ConnectorJob(
                source_type="greenhouse",
                source_job_id="greenhouse-303",
                title="Platform Engineer",
                location_text="Bengaluru",
                description="Build the shared cloud platform for all product teams.",
                job_url="https://careers.example.com/jobs/platform-engineer",
            ),
            seen_at=observed_at,
        )
        canonical_match = service.upsert(
            company.id,
            ConnectorJob(
                source_type="lever",
                source_job_id="lever-303",
                title="Platform Engineer",
                location_text="Bengaluru",
                description="Build the shared cloud platform for all product teams.",
                job_url=(
                    "https://careers.example.com/jobs/platform-engineer/"
                    "?utm_campaign=hiring"
                ),
            ),
            seen_at=observed_at,
        )
        fallback_match = service.upsert(
            company.id,
            ConnectorJob(
                source_type="custom",
                source_job_id="custom-303",
                title="Platform Engineer",
                location_text="Bengaluru",
                description="Build the shared cloud platform for all product teams.",
                job_url="https://careers.example.com/openings/platform-role",
            ),
            seen_at=observed_at,
        )

        assert first.job.id == canonical_match.job.id == fallback_match.job.id
        assert canonical_match.updated is True
        assert canonical_match.materially_changed is False
        assert fallback_match.updated is True
        assert fallback_match.materially_changed is False
        assert session.scalar(select(func.count(Job.id))) == 1

        with pytest.raises(JobNormalizationError, match="Job URL is invalid"):
            service.upsert_many(
                company.id,
                [
                    ConnectorJob(
                        source_type="ashby",
                        source_job_id="valid-before-error",
                        title="Mobile Engineer",
                        location_text="Pune",
                        description="Build mobile applications for global customers.",
                        job_url="https://careers.example.com/jobs/mobile-engineer",
                    ),
                    ConnectorJob(
                        source_type="ashby",
                        source_job_id="invalid-url",
                        title="Web Engineer",
                        location_text="Pune",
                        description="Build web applications for global customers.",
                        job_url="javascript:alert(1)",
                    ),
                ],
                seen_at=observed_at,
            )

        assert session.scalar(select(func.count(Job.id))) == 1
    finally:
        session.close()
        engine.dispose()
