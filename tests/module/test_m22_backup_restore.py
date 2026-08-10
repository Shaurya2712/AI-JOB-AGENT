import asyncio
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models.companies import Company
from app.models.job_matches import JobMatch
from app.models.job_user_state import JobUserState
from app.models.jobs import Job
from app.models.notifications import NotificationDestination
from app.models.profiles import CandidateProfile
from app.models.resumes import Resume
from app.models.runtime_settings import RuntimeSetting
from app.models.scan_history import ScanRun
from app.services.scans import ScanController, ScanPipelineResult


OBSERVED_AT = datetime(2026, 8, 9, 16, 0, tzinfo=timezone.utc)
SOURCE_TELEGRAM_SECRET = "source-telegram-secret"
SOURCE_OPENAI_SECRET = "source-openai-secret"
TARGET_TELEGRAM_SECRET = "target-telegram-secret"


def _app(
    tmp_path: Path,
    name: str,
    *,
    daily_target: int | None = None,
    scan_interval: float | None = None,
    telegram_secret: str | None = None,
    openai_secret: str | None = None,
):
    seed_path = tmp_path / f"{name}-seed.json"
    seed_path.write_text("[]", encoding="utf-8")
    values: dict[str, object] = {
        "environment": "test",
        "database_url": f"sqlite:///{(tmp_path / f'{name}.db').as_posix()}",
        "company_seed_path": seed_path,
        "resume_storage_path": tmp_path / f"{name}-resumes",
        "search_provider": "disabled",
        "ai_provider": "disabled",
    }
    if daily_target is not None:
        values["daily_action_target"] = daily_target
    if scan_interval is not None:
        values["scan_interval_hours"] = scan_interval
    if telegram_secret is not None:
        values["telegram_bot_token"] = telegram_secret
    if openai_secret is not None:
        values["openai_api_key"] = openai_secret
    return create_app(Settings(_env_file=None, **values))


def _seed_complete_state(application, label: str) -> None:
    resume_bytes = f"{label} resume with Python experience".encode()
    resume_reference = f"{label.casefold()}-resume.txt"
    resume_root = application.state.settings.resume_storage_path
    resume_root.mkdir(parents=True, exist_ok=True)
    (resume_root / resume_reference).write_bytes(resume_bytes)

    with application.state.session_factory() as session:
        profile = CandidateProfile(
            name=f"{label} Profile",
            is_active=True,
            years_experience=6,
            target_roles_json=["Backend Engineer"],
            role_synonyms_json=["Python Engineer"],
            skills_json=["Python", "SQL"],
            preferred_locations_json=["Remote"],
            work_modes_json=["Remote"],
            minimum_salary=1_500_000,
            salary_currency="INR",
            excluded_keywords_json=["Internship"],
            notes=f"{label} profile notes",
        )
        company = Company(
            name=f"{label} Company",
            website_url=f"https://{label.casefold()}.example",
            careers_url=f"https://{label.casefold()}.example/jobs",
            provider_type="greenhouse",
            provider_identifier=label.casefold(),
            discovery_source="seed",
            is_active=True,
            provider_supported=True,
            total_jobs_seen=1,
        )
        session.add_all([profile, company])
        session.flush()
        resume = Resume(
            profile_id=profile.id,
            name=f"{label} Resume",
            file_path=resume_reference,
            extracted_text=resume_bytes.decode(),
            is_primary=True,
        )
        session.add(resume)
        session.flush()
        job = Job(
            company_id=company.id,
            source_type="greenhouse",
            source_job_id=f"{label.casefold()}-job",
            canonical_url=f"https://jobs.example/{label.casefold()}-job",
            title=f"{label} Backend Engineer",
            normalized_title=f"{label.casefold()} backend engineer",
            location_text="Remote",
            remote_type="remote",
            description="Build reliable Python services.",
            description_hash="a" * 64,
            dedupe_signature="b" * 64,
            skills_json=["Python", "SQL"],
            discovered_at=OBSERVED_AT,
            last_seen_at=OBSERVED_AT,
            lifecycle_status="open",
        )
        session.add(job)
        session.flush()
        session.add_all(
            [
                JobMatch(
                    job_id=job.id,
                    profile_id=profile.id,
                    ai_provider="fake",
                    ai_model="fixture",
                    scoring_version="job-match-v1",
                    overall_score=92,
                    role_score=94,
                    skills_score=91,
                    experience_score=90,
                    location_score=95,
                    freshness_score=88,
                    seniority_score=90,
                    salary_score=None,
                    recommendation_label="Excellent",
                    matching_skills_json=["Python", "SQL"],
                    missing_skills_json=[],
                    concerns_json=[],
                    explanation="Strong fixture match.",
                    suggested_resume_id=resume.id,
                    source_job_hash="c" * 64,
                    scored_at=OBSERVED_AT,
                ),
                JobUserState(
                    job_id=job.id,
                    profile_id=profile.id,
                    state="applied",
                    applied_at=OBSERVED_AT,
                    resume_id=resume.id,
                    note=f"Applied from {label}",
                    updated_at=OBSERVED_AT,
                ),
                ScanRun(
                    trigger_type="manual",
                    started_at=OBSERVED_AT,
                    finished_at=OBSERVED_AT,
                    status="success",
                    companies_checked=1,
                    sources_checked=1,
                    jobs_fetched=1,
                    jobs_new=1,
                    jobs_updated=0,
                    jobs_scored=1,
                    strong_matches=1,
                    errors_count=0,
                    summary=f"{label} scan completed.",
                ),
                NotificationDestination(
                    type="recommendation",
                    name=f"{label} recommendations",
                    telegram_chat_id="-22001",
                    is_enabled=True,
                ),
            ]
        )
        session.commit()


async def _download_backup(application) -> bytes:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/settings/backup/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "job-agent-backup-" in response.headers["content-disposition"]
    return response.content


def test_one_archive_round_trip_restores_data_resumes_and_non_secret_settings(
    tmp_path: Path,
) -> None:
    source = _app(
        tmp_path,
        "source",
        daily_target=17,
        scan_interval=6,
        telegram_secret=SOURCE_TELEGRAM_SECRET,
        openai_secret=SOURCE_OPENAI_SECRET,
    )

    async def create_source_backup() -> bytes:
        async with source.router.lifespan_context(source):
            _seed_complete_state(source, "Source")
            return await _download_backup(source)

    archive_bytes = asyncio.run(create_source_backup())

    with ZipFile(BytesIO(archive_bytes)) as archive:
        assert set(archive.namelist()) == {
            "database.sqlite3",
            "manifest.json",
            "resumes/source-resume.txt",
        }
        manifest_bytes = archive.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        assert manifest["format"] == "job-agent-backup"
        assert manifest["version"] == 1
        assert manifest["settings"]["daily_action_target"] == 17
        assert manifest["settings"]["scan_interval_hours"] == 6
        assert "database_url" not in manifest["settings"]
        assert "resume_storage_path" not in manifest["settings"]
        assert SOURCE_TELEGRAM_SECRET.encode() not in manifest_bytes
        assert SOURCE_OPENAI_SECRET.encode() not in manifest_bytes
        archived_database = tmp_path / "archived-source.sqlite3"
        archived_database.write_bytes(archive.read("database.sqlite3"))
    with sqlite3.connect(archived_database) as connection:
        setting_keys = {
            row[0] for row in connection.execute("SELECT key FROM settings")
        }
        assert "telegram_bot_token" not in setting_keys
        assert "openai_api_key" not in setting_keys
        assert "database_url" not in setting_keys

    target = _app(
        tmp_path,
        "target",
        telegram_secret=TARGET_TELEGRAM_SECRET,
    )

    async def restore_target() -> tuple[httpx.Response, int, float, str]:
        async with target.router.lifespan_context(target):
            _seed_complete_state(target, "Target")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=target),
                base_url="http://testserver",
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    "/settings/backup/restore",
                    data={"confirm": "replace"},
                    files={
                        "backup_file": (
                            "job-agent-backup.zip",
                            archive_bytes,
                            "application/zip",
                        )
                    },
                )
            secret = target.state.settings.telegram_bot_token
            return (
                response,
                target.state.settings.daily_action_target,
                target.state.settings.scan_interval_hours,
                secret.get_secret_value() if secret is not None else "",
            )

    response, daily_target, interval, retained_secret = asyncio.run(restore_target())

    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/settings/backup?restored=1"
    assert daily_target == 17
    assert interval == 6
    assert retained_secret == TARGET_TELEGRAM_SECRET
    with sqlite3.connect(tmp_path / "target.db") as connection:
        assert connection.execute("SELECT name FROM candidate_profiles").fetchone() == (
            "Source Profile",
        )
        assert connection.execute("SELECT title FROM jobs").fetchone() == (
            "Source Backend Engineer",
        )
        assert connection.execute("SELECT state FROM job_user_state").fetchone() == (
            "applied",
        )
        assert connection.execute(
            "SELECT extracted_text FROM resumes"
        ).fetchone() == ("Source resume with Python experience",)
        assert connection.execute(
            "SELECT applied_at, note FROM job_user_state"
        ).fetchone() == ("2026-08-09 16:00:00.000000", "Applied from Source")
        assert connection.execute("SELECT overall_score FROM job_matches").fetchone() == (
            92,
        )
        assert connection.execute("SELECT summary FROM scan_runs").fetchone() == (
            "Source scan completed.",
        )
        assert connection.execute(
            "SELECT name FROM notification_destinations"
        ).fetchone() == ("Source recommendations",)
    assert (tmp_path / "target-resumes" / "source-resume.txt").read_bytes() == (
        b"Source resume with Python experience"
    )
    assert not (tmp_path / "target-resumes" / "target-resume.txt").exists()

    restarted = _app(
        tmp_path,
        "target",
        telegram_secret=TARGET_TELEGRAM_SECRET,
    )

    async def verify_restart() -> tuple[int, float, float, str]:
        async with restarted.router.lifespan_context(restarted):
            secret = restarted.state.settings.telegram_bot_token
            return (
                restarted.state.settings.daily_action_target,
                restarted.state.settings.scan_interval_hours,
                restarted.state.scan_scheduler.snapshot().interval_hours,
                secret.get_secret_value() if secret is not None else "",
            )

    restart_daily, restart_interval, scheduler_interval, restart_secret = asyncio.run(
        verify_restart()
    )
    assert (restart_daily, restart_interval, scheduler_interval) == (17, 6, 6)
    assert restart_secret == TARGET_TELEGRAM_SECRET


def test_invalid_or_unsafe_archive_is_rejected_without_changing_local_data(
    tmp_path: Path,
) -> None:
    application = _app(tmp_path, "invalid-target", daily_target=12)

    async def scenario() -> tuple[httpx.Response, httpx.Response]:
        async with application.router.lifespan_context(application):
            _seed_complete_state(application, "Original")
            valid_backup = await _download_backup(application)

            unsafe_buffer = BytesIO()
            with ZipFile(BytesIO(valid_backup)) as source, ZipFile(
                unsafe_buffer,
                "w",
                compression=ZIP_DEFLATED,
            ) as unsafe:
                for name in source.namelist():
                    unsafe.writestr(name, source.read(name))
                unsafe.writestr("../escape.txt", b"unsafe")

            checksum_buffer = BytesIO()
            with ZipFile(BytesIO(valid_backup)) as source, ZipFile(
                checksum_buffer,
                "w",
                compression=ZIP_DEFLATED,
            ) as tampered:
                manifest = json.loads(source.read("manifest.json"))
                manifest["database"]["sha256"] = "0" * 64
                for name in source.namelist():
                    payload = (
                        json.dumps(manifest).encode()
                        if name == "manifest.json"
                        else source.read(name)
                    )
                    tampered.writestr(name, payload)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                unsafe_response = await client.post(
                    "/settings/backup/restore",
                    data={"confirm": "replace"},
                    files={"backup_file": ("unsafe.zip", unsafe_buffer.getvalue())},
                )
                checksum_response = await client.post(
                    "/settings/backup/restore",
                    data={"confirm": "replace"},
                    files={
                        "backup_file": ("tampered.zip", checksum_buffer.getvalue())
                    },
                )
            with application.state.session_factory() as session:
                profile = session.scalar(select(CandidateProfile))
                assert profile is not None
                assert profile.name == "Original Profile"
                assert session.scalar(select(RuntimeSetting).where(
                    RuntimeSetting.key == "daily_action_target"
                )).value_json == 12
            assert (
                application.state.settings.resume_storage_path
                / "original-resume.txt"
            ).read_bytes() == b"Original resume with Python experience"
            return unsafe_response, checksum_response

    unsafe_response, checksum_response = asyncio.run(scenario())

    assert unsafe_response.status_code == 422
    assert "unsafe path" in unsafe_response.text
    assert checksum_response.status_code == 422
    assert "checksum validation failed" in checksum_response.text
    assert not (tmp_path / "escape.txt").exists()


def test_restore_is_rejected_while_a_scan_is_running(tmp_path: Path) -> None:
    application = _app(tmp_path, "running-target")

    class HeldRunner:
        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def run(self, _trigger_type: str) -> ScanPipelineResult:
            self.entered.set()
            await self.release.wait()
            return ScanPipelineResult(
                companies_checked=0,
                sources_checked=0,
                jobs_fetched=0,
                jobs_new=0,
                jobs_updated=0,
                jobs_scored=0,
                strong_matches=0,
                errors_count=0,
                errors=(),
                summary="Held scan completed.",
            )

    async def scenario() -> httpx.Response:
        async with application.router.lifespan_context(application):
            _seed_complete_state(application, "Running")
            valid_backup = await _download_backup(application)
            runner = HeldRunner()
            controller = ScanController(runner)
            application.state.scan_controller = controller
            assert await controller.start_manual() is True
            await runner.entered.wait()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                response = await client.post(
                    "/settings/backup/restore",
                    data={"confirm": "replace"},
                    files={"backup_file": ("backup.zip", valid_backup)},
                )
            assert controller.snapshot().status == "running"
            runner.release.set()
            await controller.wait_for_idle()
            with application.state.session_factory() as session:
                assert session.scalar(select(CandidateProfile)).name == "Running Profile"
            return response

    response = asyncio.run(scenario())

    assert response.status_code == 422
    assert "Wait for the current scan to finish" in response.text
