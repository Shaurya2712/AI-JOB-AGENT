from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import Settings
from app.db import create_database_engine, create_session_factory, run_migrations
from app.models.companies import Company
from app.providers.jobs.base import ConnectorJob
from app.services.job_lifecycle import JobLifecycleScopeError, JobLifecycleService
from app.services.jobs import JobUpsertService


def _open_session(tmp_path: Path):
    database_path = tmp_path / "m13.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        company_seed_path=tmp_path / "unused-seed.json",
        resume_storage_path=tmp_path / "resumes",
    )
    run_migrations(settings)
    engine = create_database_engine(settings.database_url)
    return settings, engine, create_session_factory(engine)()


def _company(name: str = "Acme") -> Company:
    slug = name.casefold().replace(" ", "-")
    return Company(
        name=name,
        website_url=f"https://{slug}.example",
        careers_url=f"https://jobs.{slug}.example",
        provider_type="greenhouse",
        provider_identifier=slug,
        discovery_source="seed",
        is_active=True,
        provider_supported=True,
        total_jobs_seen=0,
    )


def _connector_job(source_job_id: str, title: str) -> ConnectorJob:
    return ConnectorJob(
        source_type="greenhouse",
        source_job_id=source_job_id,
        title=title,
        location_text="Pune, India",
        description=f"Build reliable products as the {title} for the team.",
        job_url=f"https://jobs.example.com/jobs/{source_job_id}",
    )


def test_repeated_successful_absence_transitions_and_reappearance_resets(
    tmp_path: Path,
) -> None:
    settings, engine, session = _open_session(tmp_path)
    first_seen = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)

    try:
        company = _company()
        session.add(company)
        session.commit()
        upserts = JobUpsertService(session).upsert_many(
            company.id,
            [
                _connector_job("job-101", "Backend Engineer"),
                _connector_job("job-102", "Frontend Engineer"),
            ],
            seen_at=first_seen,
        )
        retained, disappearing = (result.job for result in upserts)
        lifecycle = JobLifecycleService(
            session,
            close_after_missing_scans=(
                settings.job_lifecycle_close_after_missing_scans
            ),
        )

        first_missing = lifecycle.reconcile_source(
            company.id,
            " GreenHouse ",
            {retained.id},
            scan_succeeded=True,
            reconciled_at=first_seen + timedelta(hours=1),
        )
        assert disappearing.consecutive_missing_scans == 1
        assert disappearing.lifecycle_status == "open"
        assert first_missing.jobs_closed == 0
        assert first_missing.jobs_marked_possibly_closed == 0

        second_missing = lifecycle.reconcile_source(
            company.id,
            "greenhouse",
            {retained.id},
            scan_succeeded=True,
            reconciled_at=first_seen + timedelta(hours=2),
        )
        assert disappearing.consecutive_missing_scans == 2
        assert disappearing.lifecycle_status == "possibly_closed"
        assert second_missing.jobs_marked_possibly_closed == 1
        assert second_missing.jobs_closed == 0

        third_missing = lifecycle.reconcile_source(
            company.id,
            "greenhouse",
            {retained.id},
            scan_succeeded=True,
            reconciled_at=first_seen + timedelta(hours=3),
        )
        assert disappearing.consecutive_missing_scans == 3
        assert disappearing.lifecycle_status == "closed"
        assert third_missing.jobs_closed == 1

        still_missing = lifecycle.reconcile_source(
            company.id,
            "greenhouse",
            {retained.id},
            scan_succeeded=True,
            reconciled_at=first_seen + timedelta(hours=4),
        )
        assert disappearing.consecutive_missing_scans == 3
        assert disappearing.lifecycle_status == "closed"
        assert still_missing.jobs_closed == 0

        reappeared = JobUpsertService(session).upsert(
            company.id,
            _connector_job("job-102", "Frontend Engineer"),
            seen_at=first_seen + timedelta(hours=5),
        )
        assert reappeared.job.lifecycle_status == "closed"
        reset = lifecycle.reconcile_source(
            company.id,
            "greenhouse",
            {retained.id, disappearing.id},
            scan_succeeded=True,
            reconciled_at=first_seen + timedelta(hours=5),
        )

        assert retained.consecutive_missing_scans == 0
        assert retained.lifecycle_status == "open"
        assert disappearing.consecutive_missing_scans == 0
        assert disappearing.lifecycle_status == "open"
        assert reset.jobs_reopened == 1
        assert reset.jobs_seen == 2
    finally:
        session.close()
        engine.dispose()


def test_failed_scans_and_out_of_scope_seen_ids_never_mark_jobs_missing(
    tmp_path: Path,
) -> None:
    settings, engine, session = _open_session(tmp_path)
    observed_at = datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc)

    try:
        company = _company()
        other_company = _company("Other Co")
        session.add_all([company, other_company])
        session.commit()
        tracked = JobUpsertService(session).upsert(
            company.id,
            _connector_job("job-201", "Platform Engineer"),
            seen_at=observed_at,
        ).job
        other = JobUpsertService(session).upsert(
            other_company.id,
            _connector_job("job-202", "Mobile Engineer"),
            seen_at=observed_at,
        ).job
        lifecycle = JobLifecycleService(
            session,
            close_after_missing_scans=(
                settings.job_lifecycle_close_after_missing_scans
            ),
        )

        failed = lifecycle.reconcile_source(
            company.id,
            "greenhouse",
            set(),
            scan_succeeded=False,
            reconciled_at=observed_at + timedelta(hours=1),
        )
        assert failed.scan_applied is False
        assert tracked.consecutive_missing_scans == 0
        assert tracked.lifecycle_status == "open"

        with pytest.raises(JobLifecycleScopeError, match="do not belong"):
            lifecycle.reconcile_source(
                company.id,
                "greenhouse",
                {other.id},
                scan_succeeded=True,
                reconciled_at=observed_at + timedelta(hours=2),
            )
        assert tracked.consecutive_missing_scans == 0
        assert tracked.lifecycle_status == "open"

        applied = lifecycle.reconcile_source(
            company.id,
            "greenhouse",
            set(),
            scan_succeeded=True,
            reconciled_at=observed_at + timedelta(hours=3),
        )
        assert applied.scan_applied is True
        assert tracked.consecutive_missing_scans == 1
        assert tracked.lifecycle_status == "open"
    finally:
        session.close()
        engine.dispose()


def test_explicit_closure_is_immediate_idempotent_and_reopens_when_seen(
    tmp_path: Path,
) -> None:
    settings, engine, session = _open_session(tmp_path)
    observed_at = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)

    try:
        company = _company()
        session.add(company)
        session.commit()
        job = JobUpsertService(session).upsert(
            company.id,
            _connector_job("job-301", "Data Engineer"),
            seen_at=observed_at,
        ).job
        lifecycle = JobLifecycleService(
            session,
            close_after_missing_scans=(
                settings.job_lifecycle_close_after_missing_scans
            ),
        )

        closed = lifecycle.mark_explicitly_closed(
            job.id,
            closed_at=observed_at + timedelta(minutes=5),
        )
        repeated = lifecycle.mark_explicitly_closed(
            job.id,
            closed_at=observed_at + timedelta(minutes=10),
        )

        assert closed.transitioned is True
        assert repeated.transitioned is False
        assert job.lifecycle_status == "closed"
        assert job.consecutive_missing_scans == 0

        reset = lifecycle.reconcile_source(
            company.id,
            "greenhouse",
            {job.id},
            scan_succeeded=True,
            reconciled_at=observed_at + timedelta(minutes=15),
        )
        assert reset.jobs_reopened == 1
        assert job.lifecycle_status == "open"
        assert job.consecutive_missing_scans == 0
    finally:
        session.close()
        engine.dispose()
