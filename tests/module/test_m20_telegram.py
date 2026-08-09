import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models.companies import Company
from app.models.job_matches import JobMatch
from app.models.jobs import Job
from app.models.notifications import NotificationDestination, NotificationLog
from app.models.profiles import CandidateProfile
from app.providers.telegram import open_telegram_client
from app.services.notifications import (
    NotificationDestinationService,
    NotificationService,
)
from app.services.scans import (
    ApplicationScanPipeline,
    ScanController,
    ScanPipelineResult,
    _RunCounts,
)


OBSERVED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
BOT_TOKEN = "fixture-bot-token"


def _app(tmp_path: Path, name: str, *, bot_token: str | None = BOT_TOKEN):
    seed_path = tmp_path / f"{name}-seed.json"
    seed_path.write_text("[]", encoding="utf-8")
    return create_app(
        Settings(
            environment="test",
            database_url=f"sqlite:///{(tmp_path / name).as_posix()}",
            company_seed_path=seed_path,
            resume_storage_path=tmp_path / "resumes",
            search_provider="disabled",
            ai_provider="disabled",
            telegram_bot_token=bot_token,
        )
    )


def _seed_scored_job(session) -> tuple[int, int]:
    company = Company(
        name="Notify Co",
        website_url="https://notify.example",
        careers_url="https://notify.example/jobs",
        provider_type="greenhouse",
        provider_identifier="notify",
        discovery_source="seed",
        is_active=True,
        provider_supported=True,
        total_jobs_seen=1,
    )
    profile = CandidateProfile(
        name="Backend Profile",
        is_active=True,
        years_experience=5,
        target_roles_json=["Backend Engineer"],
        role_synonyms_json=[],
        skills_json=["Python"],
        preferred_locations_json=["Remote"],
        work_modes_json=["Remote"],
        excluded_keywords_json=[],
        notes="",
    )
    session.add_all([company, profile])
    session.flush()
    job = Job(
        company_id=company.id,
        source_type="greenhouse",
        source_job_id="notify-1",
        canonical_url="https://jobs.example/notify-1",
        title="Backend Engineer",
        normalized_title="backend engineer",
        location_text="Remote",
        remote_type="remote",
        description="Build Python services.",
        description_hash="a" * 64,
        dedupe_signature="b" * 64,
        skills_json=["Python"],
        discovered_at=OBSERVED_AT,
        last_seen_at=OBSERVED_AT,
        lifecycle_status="open",
    )
    session.add(job)
    session.flush()
    session.add(
        JobMatch(
            job_id=job.id,
            profile_id=profile.id,
            ai_provider="fake",
            ai_model="fixture",
            scoring_version="job-match-v1",
            overall_score=91,
            role_score=94,
            skills_score=90,
            experience_score=88,
            location_score=95,
            freshness_score=90,
            seniority_score=87,
            salary_score=None,
            recommendation_label="Excellent",
            matching_skills_json=["Python"],
            missing_skills_json=[],
            concerns_json=[],
            explanation="Strong fit.",
            source_job_hash="c" * 64,
            scored_at=OBSERVED_AT,
        )
    )
    session.commit()
    return job.id, profile.id


def _configure_destinations(session) -> None:
    service = NotificationDestinationService(session)
    for destination_type, name, chat_id in (
        ("recommendation", "High matches", "-1001"),
        ("application_activity", "Applications", "-1002"),
        ("scan_summary", "Scan summaries", "-1003"),
    ):
        service.configure(
            destination_type,
            name=name,
            telegram_chat_id=chat_id,
            is_enabled=True,
        )


class CompletedRunner:
    async def run(self, _trigger_type: str) -> ScanPipelineResult:
        return ScanPipelineResult(
            companies_checked=4,
            sources_checked=3,
            jobs_fetched=8,
            jobs_new=2,
            jobs_updated=1,
            jobs_scored=2,
            strong_matches=1,
            errors_count=0,
            errors=(),
            summary="Fixture scan completed.",
        )


def test_three_destinations_are_configurable_without_rendering_the_token(
    tmp_path: Path,
) -> None:
    application = _app(tmp_path, "m20-settings.db")

    async def scenario() -> tuple[httpx.Response, httpx.Response]:
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
                follow_redirects=False,
            ) as client:
                page = await client.get("/settings/notifications")
                for destination_type, name, chat_id in (
                    ("recommendation", "Recommended jobs", "-2001"),
                    ("application_activity", "Applied jobs", "-2002"),
                    ("scan_summary", "Scan status", "-2003"),
                ):
                    response = await client.post(
                        "/settings/notifications",
                        data={
                            "destination_type": destination_type,
                            "name": name,
                            "telegram_chat_id": chat_id,
                            "is_enabled": "on",
                        },
                    )
                    assert response.status_code == 303
                invalid = await client.post(
                    "/settings/notifications",
                    data={
                        "destination_type": "recommendation",
                        "name": "Recommended jobs",
                        "telegram_chat_id": "not-a-chat",
                        "is_enabled": "on",
                    },
                )
            with application.state.session_factory() as session:
                destinations = tuple(
                    session.scalars(
                        select(NotificationDestination).order_by(
                            NotificationDestination.type
                        )
                    )
                )
                assert len(destinations) == 3
                assert all(item.is_enabled for item in destinations)
                assert {item.telegram_chat_id for item in destinations} == {
                    "-2001",
                    "-2002",
                    "-2003",
                }
            return page, invalid

    page, invalid = asyncio.run(scenario())

    assert page.status_code == 200
    assert "High-match recommendations" in page.text
    assert "Application activity" in page.text
    assert "Search/run summaries" in page.text
    assert "Configured" in page.text
    assert BOT_TOKEN not in page.text
    assert invalid.status_code == 422


def test_telegram_settings_load_without_external_credentials(tmp_path: Path) -> None:
    application = _app(tmp_path, "m20-no-token.db", bot_token=None)

    async def scenario() -> httpx.Response:
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                return await client.get("/settings/notifications")

    page = asyncio.run(scenario())

    assert page.status_code == 200
    assert "Not configured" in page.text
    assert application.state.notification_service.sender.is_configured is False


def test_recommendation_application_and_scan_events_route_once(
    tmp_path: Path,
) -> None:
    application = _app(tmp_path, "m20-events.db")
    delivered: list[tuple[str, str]] = []

    def telegram_endpoint(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        delivered.append((str(payload["chat_id"]), str(payload["text"])))
        return httpx.Response(200, json={"ok": True, "result": {}})

    async def scenario() -> None:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                job_id, profile_id = _seed_scored_job(session)
                _configure_destinations(session)

            async with open_telegram_client(
                application.state.settings,
                transport=httpx.MockTransport(telegram_endpoint),
            ) as telegram:
                notifications = NotificationService(
                    application.state.session_factory,
                    telegram,
                    match_threshold=85,
                )
                application.state.notification_service = notifications

                first_match = await notifications.notify_high_match(job_id, profile_id)
                duplicate_match = await notifications.notify_high_match(
                    job_id,
                    profile_id,
                )
                assert first_match.sent == 1
                assert duplicate_match.skipped == 1

                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=application),
                    base_url="http://testserver",
                    follow_redirects=False,
                ) as client:
                    for _ in range(2):
                        response = await client.post(
                            f"/jobs/{job_id}/state",
                            data={"profile_id": profile_id, "action": "applied"},
                        )
                        assert response.status_code == 303

                controller = ScanController(
                    CompletedRunner(),
                    completion_notifier=notifications,
                )
                assert await controller.start_manual() is True
                snapshot = await controller.wait_for_idle()
                duplicate_summary = await notifications.notify_scan_summary(snapshot)
                assert duplicate_summary.skipped == 1

            with application.state.session_factory() as session:
                logs = tuple(
                    session.scalars(select(NotificationLog).order_by(NotificationLog.id))
                )
                assert len(logs) == 3
                assert all(log.status == "sent" for log in logs)
                assert all(log.sent_at is not None for log in logs)
                assert {log.event_key.split(":", 1)[0] for log in logs} == {
                    "high-match",
                    "application",
                    "scan-summary",
                }

    asyncio.run(scenario())

    assert len(delivered) == 3
    assert {chat_id for chat_id, _ in delivered} == {"-1001", "-1002", "-1003"}
    assert any("New high match: 91% Excellent" in text for _, text in delivered)
    assert any("Application recorded" in text for _, text in delivered)
    assert any("8 fetched, 2 new, 1 updated" in text for _, text in delivered)
    assert any("Errors: 0" in text for _, text in delivered)


def test_failed_delivery_is_safely_logged_and_can_retry(tmp_path: Path) -> None:
    application = _app(tmp_path, "m20-retry.db")
    request_count = 0

    def telegram_endpoint(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(500, json={"ok": False})
        return httpx.Response(200, json={"ok": True, "result": {}})

    async def scenario() -> tuple[str | None, str, int]:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                job_id, profile_id = _seed_scored_job(session)
                NotificationDestinationService(session).configure(
                    "recommendation",
                    name="High matches",
                    telegram_chat_id="-3001",
                    is_enabled=True,
                )
            async with open_telegram_client(
                application.state.settings,
                transport=httpx.MockTransport(telegram_endpoint),
            ) as telegram:
                notifications = NotificationService(
                    application.state.session_factory,
                    telegram,
                )
                first = await notifications.notify_high_match(job_id, profile_id)
                assert first.failed == 1
                with application.state.session_factory() as session:
                    failed_error = session.scalar(
                        select(NotificationLog.error_message)
                    )
                second = await notifications.notify_high_match(job_id, profile_id)
                third = await notifications.notify_high_match(job_id, profile_id)
                assert second.sent == 1
                assert third.skipped == 1
            with application.state.session_factory() as session:
                log = session.scalar(select(NotificationLog))
                assert log is not None
                return failed_error, log.status, request_count

    failed_error, final_status, attempts = asyncio.run(scenario())

    assert failed_error == "Telegram rejected the message"
    assert BOT_TOKEN not in failed_error
    assert final_status == "sent"
    assert attempts == 2


def test_scan_scoring_notifies_only_new_jobs_at_the_configured_threshold(
    tmp_path: Path,
    monkeypatch,
) -> None:
    application = _app(tmp_path, "m20-new-match.db")

    class FakeNotifier:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []

        async def notify_high_match(self, job_id: int, profile_id: int) -> None:
            self.calls.append((job_id, profile_id))

    class FakeProvider:
        is_configured = True

    @asynccontextmanager
    async def fake_provider(_settings):
        yield FakeProvider()

    class FakeMatchingService:
        def __init__(self, _session, _provider) -> None:
            pass

        async def score_job(self, _job_id: int, _profile_id: int):
            return SimpleNamespace(
                status="scored",
                match=SimpleNamespace(overall_score=91),
                error=None,
            )

    monkeypatch.setattr("app.services.scans.open_ai_provider", fake_provider)
    monkeypatch.setattr("app.services.scans.AIMatchingService", FakeMatchingService)

    async def scenario() -> tuple[list[tuple[int, int]], int]:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                job_id, profile_id = _seed_scored_job(session)
            notifier = FakeNotifier()
            pipeline = ApplicationScanPipeline(
                application.state.session_factory,
                application.state.settings,
                recommendation_notifier=notifier,
            )
            new_counts = _RunCounts(new_job_ids={job_id})
            await pipeline._score_jobs(new_counts)
            await pipeline._score_jobs(_RunCounts())
            return notifier.calls, new_counts.jobs_scored

    calls, scored = asyncio.run(scenario())

    assert calls == [(1, 1)]
    assert scored == 1
