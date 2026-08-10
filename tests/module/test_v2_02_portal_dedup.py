from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from zipfile import ZIP_DEFLATED, ZipFile

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db import (
    ALEMBIC_CONFIG_PATH,
    MIGRATIONS_DIR,
    create_database_engine,
    create_session_factory,
    run_migrations,
)
from app.models.companies import Company
from app.models.job_matches import JobMatch
from app.models.job_user_state import JobUserState
from app.models.jobs import Job
from app.models.notifications import NotificationDestination, NotificationLog
from app.models.portal_sources import PortalJobSource
from app.models.profiles import CandidateProfile
from app.models.resumes import Resume
from app.providers.jobs.base import ConnectorJob
from app.services.backups import BackupService
from app.services.jobs import JobUpsertService
from app.services.portal_discovery import PortalJobCandidate
from app.services.portal_jobs import PortalJobUpsertService
from app.services.runtime_settings import RuntimeSettingsService, portable_settings


FIRST_SEEN = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)
SECOND_SEEN = FIRST_SEEN + timedelta(hours=4)


def settings_for(tmp_path: Path, name: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
        company_seed_path=tmp_path / "unused-seed.json",
        resume_storage_path=tmp_path / f"{name}-resumes",
        search_provider="disabled",
        ai_provider="disabled",
    )


def open_session(tmp_path: Path, name: str = "m02.db"):
    settings = settings_for(tmp_path, name)
    run_migrations(settings)
    engine = create_database_engine(settings.database_url)
    return settings, engine, create_session_factory(engine)()


def company(
    name: str = "Acme Private Limited",
    *,
    website_suffix: str = "acme",
) -> Company:
    return Company(
        name=name,
        website_url=f"https://{website_suffix}.example",
        careers_url=f"https://jobs.{website_suffix}.example",
        provider_type="greenhouse",
        provider_identifier=website_suffix,
        discovery_source="seed",
        is_active=True,
        provider_supported=True,
        total_jobs_seen=0,
    )


def connector_job(
    source_job_id: str = "ats-101",
    *,
    title: str = "Mobile Engineer",
    location: str = "Bengaluru",
    description: str = "Build reliable mobile products from a complete job description.",
    url: str | None = None,
) -> ConnectorJob:
    return ConnectorJob(
        source_type="greenhouse",
        source_job_id=source_job_id,
        title=title,
        location_text=location,
        description=description,
        job_url=url or f"https://jobs.acme.example/roles/{source_job_id}",
    )


def portal_candidate(
    portal: str = "linkedin",
    *,
    source_job_id: str | None = None,
    title: str = "Mobile Engineer",
    company_name: str = "Acme Pvt Ltd",
    location: str = "Bangalore",
    snippet: str = "Search metadata for a mobile engineering opportunity.",
) -> PortalJobCandidate:
    identifiers = {
        "linkedin": "4035123456",
        "naukri": "12082025123456",
        "indeed": "abc123xyz789",
    }
    identifier = source_job_id or identifiers[portal]
    urls = {
        "linkedin": f"https://in.linkedin.com/jobs/view/mobile-engineer-{identifier}",
        "naukri": (
            "https://www.naukri.com/"
            f"job-listings-mobile-engineer-acme-bangalore-{identifier}"
        ),
        "indeed": f"https://in.indeed.com/viewjob?jk={identifier}",
    }
    return PortalJobCandidate(
        portal=portal,
        source_job_id=identifier,
        original_url=urls[portal],
        title=title,
        company_name=company_name,
        location_text=location,
        snippet=snippet,
    )


def alembic_config(database_path: Path) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    database_url = f"sqlite:///{database_path.as_posix()}"
    config.attributes["database_url"] = database_url
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def seed_v1_job(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO candidate_profiles (id, name) VALUES (1, 'Legacy Profile')"
        )
        connection.execute(
            "INSERT INTO companies "
            "(id, name, website_url, careers_url, provider_type, provider_identifier, "
            "discovery_source, is_active, provider_supported, total_jobs_seen) "
            "VALUES (1, 'Legacy Acme', 'https://legacy.example', "
            "'https://legacy.example/jobs', 'greenhouse', 'legacy', 'seed', 1, 1, 1)"
        )
        connection.execute(
            "INSERT INTO jobs "
            "(id, company_id, source_type, source_job_id, canonical_url, title, "
            "normalized_title, location_text, description, description_hash, "
            "dedupe_signature) VALUES "
            "(1, 1, 'greenhouse', 'legacy-1', "
            "'https://legacy.example/jobs/legacy-1', 'Platform Engineer', "
            "'platform engineer', 'Bengaluru', 'Complete legacy description.', "
            f"'{sha256(b'legacy').hexdigest()}', '{sha256(b'dedupe').hexdigest()}')"
        )
        connection.execute(
            "INSERT INTO job_matches "
            "(id, job_id, profile_id, ai_provider, ai_model, scoring_version, "
            "overall_score, role_score, skills_score, experience_score, "
            "location_score, freshness_score, seniority_score, salary_score, "
            "recommendation_label, explanation, source_job_hash) VALUES "
            "(1, 1, 1, 'fixture', 'fixture', 'job-match-v1', 88, 90, 87, 85, "
            "92, 80, 86, NULL, 'Strong', 'Legacy full match.', "
            f"'{sha256(b'match').hexdigest()}')"
        )
        connection.commit()


def test_fresh_migration_and_reversible_cycle(tmp_path: Path) -> None:
    database_path = tmp_path / "fresh.db"
    config = alembic_config(database_path)

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(jobs)")
        }
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        foreign_keys = tuple(connection.execute("PRAGMA foreign_key_list(jobs)"))
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20260810_0011",)
        assert "portal_job_sources" in tables
        assert columns["company_id"][3] == 0
        assert columns["company_name"][3] == 1
        assert columns["data_completeness"][3] == 1
        assert any(row[2] == "companies" and row[6] == "SET NULL" for row in foreign_keys)

    command.downgrade(config, "20260809_0010")
    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(jobs)")
        }
        assert "company_name" not in columns
        assert "data_completeness" not in columns
        assert "cross_source_signature" not in columns
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'portal_job_sources'"
        ).fetchone() is None

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20260810_0011",)


def test_v1_upgrade_backfills_company_and_full_completeness(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-upgrade.db"
    config = alembic_config(database_path)
    command.upgrade(config, "20260809_0010")
    seed_v1_job(database_path)

    command.upgrade(config, "head")

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT company_id, company_name, data_completeness, "
            "cross_source_signature FROM jobs WHERE id = 1"
        ).fetchone()
        assert row is not None
        assert row[:3] == (1, "Legacy Acme", "full")
        assert isinstance(row[3], str) and len(row[3]) == 64
        assert connection.execute(
            "SELECT overall_score, role_score, recommendation_label "
            "FROM job_matches WHERE id = 1"
        ).fetchone() == (88, 90, "Strong")


def test_portal_only_rediscovery_updates_one_job_and_observation(tmp_path: Path) -> None:
    _settings, engine, session = open_session(tmp_path)
    try:
        service = PortalJobUpsertService(session)
        first = service.upsert(portal_candidate(), seen_at=FIRST_SEEN)
        changed = portal_candidate(
            snippet="Updated bounded search metadata for the same opportunity."
        )
        second = service.upsert(changed, seen_at=SECOND_SEEN)

        assert first.job.id == second.job.id
        assert first.source.id == second.source.id
        assert session.scalar(select(func.count(Job.id))) == 1
        assert session.scalar(select(func.count(PortalJobSource.id))) == 1
        assert second.job.company_id is None
        assert second.job.company_name == "Acme Pvt Ltd"
        assert second.job.data_completeness == "partial"
        assert second.job.description == changed.snippet
        assert second.job.discovered_at == FIRST_SEEN.replace(tzinfo=None)
        assert second.job.last_seen_at == SECOND_SEEN.replace(tzinfo=None)
        assert second.source.first_seen_at == FIRST_SEEN.replace(tzinfo=None)
        assert second.source.last_seen_at == SECOND_SEEN.replace(tzinfo=None)
    finally:
        session.close()
        engine.dispose()


def test_linkedin_and_indeed_equivalent_results_share_one_canonical_job(
    tmp_path: Path,
) -> None:
    _settings, engine, session = open_session(tmp_path)
    try:
        service = PortalJobUpsertService(session)
        linkedin = service.upsert(portal_candidate("linkedin"), seen_at=FIRST_SEEN)
        indeed = service.upsert(
            portal_candidate(
                "indeed",
                company_name="Acme Private Limited",
                location="Bengaluru",
            ),
            seen_at=SECOND_SEEN,
        )

        assert linkedin.job.id == indeed.job.id
        assert indeed.job_created is False
        assert session.scalar(select(func.count(Job.id))) == 1
        sources = tuple(
            session.scalars(select(PortalJobSource).order_by(PortalJobSource.portal_name))
        )
        assert [source.portal_name for source in sources] == ["indeed", "linkedin"]
    finally:
        session.close()
        engine.dispose()


def test_ats_first_portal_later_retains_full_canonical_data(tmp_path: Path) -> None:
    _settings, engine, session = open_session(tmp_path)
    try:
        registry_company = company()
        session.add(registry_company)
        session.commit()
        full = JobUpsertService(session).upsert(
            registry_company.id,
            connector_job(),
            seen_at=FIRST_SEEN,
        )
        original = (
            full.job.source_type,
            full.job.source_job_id,
            full.job.canonical_url,
            full.job.description,
        )

        portal = PortalJobUpsertService(session).upsert(
            portal_candidate(),
            seen_at=SECOND_SEEN,
        )

        assert portal.job.id == full.job.id
        assert portal.job_created is False
        assert portal.job.data_completeness == "full"
        assert (
            portal.job.source_type,
            portal.job.source_job_id,
            portal.job.canonical_url,
            portal.job.description,
        ) == original
        assert session.scalar(select(func.count(Job.id))) == 1
        assert session.scalar(select(func.count(PortalJobSource.id))) == 1
    finally:
        session.close()
        engine.dispose()


def test_portal_first_ats_enrichment_preserves_job_state_match_and_notification(
    tmp_path: Path,
) -> None:
    _settings, engine, session = open_session(tmp_path)
    try:
        partial = PortalJobUpsertService(session).upsert(
            portal_candidate(),
            seen_at=FIRST_SEEN,
        ).job
        saved_profile = _profile("Saved profile")
        applied_profile = _profile("Applied profile")
        session.add_all([saved_profile, applied_profile])
        session.flush()
        resume = Resume(
            profile_id=applied_profile.id,
            name="Applied resume",
            file_path="applied-resume.txt",
            extracted_text="Mobile engineering experience.",
            is_primary=True,
        )
        destination = NotificationDestination(
            type="recommendation",
            name="Recommendations",
            telegram_chat_id="-2001",
            is_enabled=True,
        )
        session.add_all([resume, destination])
        session.flush()
        applied_at = FIRST_SEEN + timedelta(hours=1)
        session.add_all(
            [
                JobUserState(
                    job_id=partial.id,
                    profile_id=saved_profile.id,
                    state="saved",
                    updated_at=applied_at,
                ),
                JobUserState(
                    job_id=partial.id,
                    profile_id=applied_profile.id,
                    state="applied",
                    applied_at=applied_at,
                    resume_id=resume.id,
                    note="Applied from the portal result.",
                    updated_at=applied_at,
                ),
                JobMatch(
                    job_id=partial.id,
                    profile_id=saved_profile.id,
                    ai_provider="fixture",
                    ai_model="fixture",
                    scoring_version="job-match-v1",
                    overall_score=86,
                    role_score=90,
                    skills_score=85,
                    experience_score=82,
                    location_score=90,
                    freshness_score=80,
                    seniority_score=84,
                    salary_score=None,
                    recommendation_label="Strong",
                    matching_skills_json=[],
                    missing_skills_json=[],
                    concerns_json=[],
                    explanation="Existing match history.",
                    suggested_resume_id=None,
                    source_job_hash="a" * 64,
                    scored_at=applied_at,
                ),
                NotificationLog(
                    destination_id=destination.id,
                    job_id=partial.id,
                    event_key=f"high-match:{partial.id}:{saved_profile.id}",
                    status="sent",
                    sent_at=applied_at,
                ),
            ]
        )
        registry_company = company()
        session.add(registry_company)
        session.commit()

        upgraded = JobUpsertService(session).upsert(
            registry_company.id,
            connector_job(),
            seen_at=SECOND_SEEN,
        )

        assert upgraded.job.id == partial.id
        assert upgraded.created is False
        assert upgraded.job.company_id == registry_company.id
        assert upgraded.job.company_name == registry_company.name
        assert upgraded.job.source_type == "greenhouse"
        assert upgraded.job.data_completeness == "full"
        assert upgraded.job.description == connector_job().description
        assert upgraded.job.discovered_at == FIRST_SEEN.replace(tzinfo=None)
        assert session.scalar(select(func.count(Job.id))) == 1
        assert session.scalar(select(func.count(PortalJobSource.id))) == 1

        states = tuple(
            session.scalars(select(JobUserState).order_by(JobUserState.profile_id))
        )
        assert [state.state for state in states] == ["saved", "applied"]
        applied_state = states[1]
        assert applied_state.applied_at == applied_at.replace(tzinfo=None)
        assert applied_state.resume_id == resume.id
        assert applied_state.note == "Applied from the portal result."
        assert session.scalar(select(func.count(JobMatch.id))) == 1
        log = session.scalar(select(NotificationLog))
        assert log is not None
        assert log.job_id == partial.id
        assert log.event_key == f"high-match:{partial.id}:{saved_profile.id}"
    finally:
        session.close()
        engine.dispose()


def test_ambiguous_cross_source_candidates_do_not_merge(tmp_path: Path) -> None:
    _settings, engine, session = open_session(tmp_path)
    try:
        registry_company = company()
        session.add(registry_company)
        session.commit()
        first = JobUpsertService(session).upsert(
            registry_company.id,
            connector_job(
                "ats-a",
                description="First distinct requisition description.",
            ),
            seen_at=FIRST_SEEN,
        )
        second = JobUpsertService(session).upsert(
            registry_company.id,
            connector_job(
                "ats-b",
                description="Second distinct requisition description.",
            ),
            seen_at=FIRST_SEEN,
        )
        assert first.job.id != second.job.id

        portal = PortalJobUpsertService(session).upsert(
            portal_candidate("naukri"),
            seen_at=SECOND_SEEN,
        )

        assert portal.job_created is True
        assert portal.job.id not in {first.job.id, second.job.id}
        assert portal.job.data_completeness == "partial"
        assert session.scalar(select(func.count(Job.id))) == 3
    finally:
        session.close()
        engine.dispose()


def test_portal_source_identity_and_url_constraints_are_enforced(tmp_path: Path) -> None:
    _settings, engine, session = open_session(tmp_path)
    try:
        persisted = PortalJobUpsertService(session).upsert(
            portal_candidate(),
            seen_at=FIRST_SEEN,
        )
        duplicate = PortalJobSource(
            job_id=persisted.job.id,
            portal_name="linkedin",
            source_job_id=persisted.source.source_job_id,
            original_url="https://linkedin.com/jobs/view/other-role-4035999999",
            title="Other role",
            company_name="Other company",
            location_text="Pune",
            snippet="Other metadata",
            data_completeness="partial",
            first_seen_at=SECOND_SEEN,
            last_seen_at=SECOND_SEEN,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        duplicate_url = PortalJobSource(
            job_id=persisted.job.id,
            portal_name="linkedin",
            source_job_id="4035888888",
            original_url=persisted.source.original_url,
            title="Other role",
            company_name="Other company",
            location_text="Pune",
            snippet="Other metadata",
            data_completeness="partial",
            first_seen_at=SECOND_SEEN,
            last_seen_at=SECOND_SEEN,
        )
        session.add(duplicate_url)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()
        engine.dispose()


def test_deleting_company_keeps_canonical_job_with_display_name(tmp_path: Path) -> None:
    _settings, engine, session = open_session(tmp_path)
    try:
        registry_company = company()
        session.add(registry_company)
        session.commit()
        job = JobUpsertService(session).upsert(
            registry_company.id,
            connector_job(),
            seen_at=FIRST_SEEN,
        ).job
        job_id = job.id
        session.delete(registry_company)
        session.commit()
        session.expire_all()

        retained = session.get(Job, job_id)
        assert retained is not None
        assert retained.company_id is None
        assert retained.company_name == "Acme Private Limited"
    finally:
        session.close()
        engine.dispose()


def test_v1_backup_is_staged_migrated_and_restored_as_v2(tmp_path: Path) -> None:
    legacy_database = tmp_path / "legacy-backup.db"
    config = alembic_config(legacy_database)
    command.upgrade(config, "20260809_0010")
    seed_v1_job(legacy_database)
    source_settings = settings_for(tmp_path, "legacy-source.db")
    legacy_settings = portable_settings(source_settings)
    legacy_settings.pop("portal_search_max_queries_per_run")
    with sqlite3.connect(legacy_database) as connection:
        connection.executemany(
            "INSERT INTO settings (key, value_json) VALUES (?, ?)",
            [(key, json.dumps(value)) for key, value in legacy_settings.items()],
        )
        connection.commit()

    database_bytes = legacy_database.read_bytes()
    manifest = {
        "format": "job-agent-backup",
        "version": 1,
        "schema_revision": "20260809_0010",
        "created_at": FIRST_SEEN.isoformat(),
        "database": {
            "path": "database.sqlite3",
            "size": len(database_bytes),
            "sha256": sha256(database_bytes).hexdigest(),
        },
        "resumes": [],
        "settings": legacy_settings,
    }
    archive_path = tmp_path / "legacy-backup.zip"
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("database.sqlite3", database_bytes)
        archive.writestr("manifest.json", json.dumps(manifest))

    target_settings = settings_for(tmp_path, "restore-target.db")
    run_migrations(target_settings)
    engine = create_database_engine(target_settings.database_url)
    session_factory = create_session_factory(engine)
    restored_settings = BackupService(
        target_settings,
        engine,
        RuntimeSettingsService(session_factory),
    ).restore_archive(archive_path)

    assert restored_settings["portal_search_max_queries_per_run"] == 18
    with sqlite3.connect(tmp_path / "restore-target.db") as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20260810_0011",)
        assert connection.execute(
            "SELECT company_name, data_completeness FROM jobs WHERE id = 1"
        ).fetchone() == ("Legacy Acme", "full")
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'portal_job_sources'"
        ).fetchone() == ("portal_job_sources",)
        assert connection.execute(
            "SELECT value_json FROM settings "
            "WHERE key = 'portal_search_max_queries_per_run'"
        ).fetchone() == (18,)
    assert not tuple(tmp_path.glob(".restore-db-*.sqlite3-wal"))
    assert not tuple(tmp_path.glob(".restore-db-*.sqlite3-shm"))
    engine.dispose()


def _profile(name: str) -> CandidateProfile:
    return CandidateProfile(
        name=name,
        is_active=True,
        years_experience=5,
        target_roles_json=["Mobile Engineer"],
        role_synonyms_json=[],
        skills_json=["Flutter"],
        preferred_locations_json=["Bengaluru"],
        work_modes_json=[],
        excluded_keywords_json=[],
    )
