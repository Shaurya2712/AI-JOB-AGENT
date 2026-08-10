import asyncio
from pathlib import Path

import httpx

from app.config import Settings
from app.main import create_app
from app.models.profiles import CandidateProfile
from app.services.scans import (
    ScanController,
    ScanPipelineResult,
    ScanTrigger,
)


def _result(*, errors: int = 0) -> ScanPipelineResult:
    return ScanPipelineResult(
        companies_checked=3,
        sources_checked=2,
        jobs_fetched=7,
        jobs_new=4,
        jobs_updated=1,
        jobs_scored=3,
        strong_matches=2,
        errors_count=errors,
        errors=("fixture source warning",) if errors else (),
        summary="Fixture scan completed.",
    )


class ControlledRunner:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[ScanTrigger] = []

    async def run(self, trigger_type: ScanTrigger) -> ScanPipelineResult:
        self.calls.append(trigger_type)
        self.entered.set()
        await self.release.wait()
        return _result()


def _app(tmp_path: Path, name: str, *, interval: float = 4.0):
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
            scan_interval_hours=interval,
        )
    )


def test_manual_and_scheduled_triggers_share_one_non_overlapping_pipeline() -> None:
    async def scenario() -> tuple[ControlledRunner, ScanController]:
        runner = ControlledRunner()
        controller = ScanController(runner)

        assert await controller.start_manual() is True
        await runner.entered.wait()
        assert controller.snapshot().status == "running"
        assert controller.snapshot().trigger_type == "manual"
        assert await controller.start_manual() is False
        assert await controller.run_scheduled() is False
        assert runner.calls == ["manual"]

        runner.release.set()
        completed = await controller.wait_for_idle()
        assert completed.status == "success"
        assert completed.jobs_fetched == 7
        assert completed.strong_matches == 2

        assert await controller.run_scheduled() is True
        assert runner.calls == ["manual", "scheduled"]
        assert controller.snapshot().status == "success"
        assert controller.snapshot().trigger_type == "scheduled"
        return runner, controller

    asyncio.run(scenario())


def test_search_now_and_schedule_state_are_visible_on_dashboard(
    tmp_path: Path,
) -> None:
    application = _app(tmp_path, "m19-dashboard.db", interval=6)

    async def scenario() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        async with application.router.lifespan_context(application):
            runner = ControlledRunner()
            controller = ScanController(runner)
            application.state.scan_controller = controller
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
                follow_redirects=False,
            ) as client:
                started = await client.post("/scans/search-now")
                await runner.entered.wait()
                running = await client.get("/?scan=started")
                overlap = await client.post("/scans/search-now")
                assert overlap.headers["location"] == "/?scan=already-running"
                runner.release.set()
                await controller.wait_for_idle()
                completed = await client.get("/")
                return started, running, completed

    started, running, completed = asyncio.run(scenario())

    assert started.status_code == 303
    assert started.headers["location"] == "/?scan=started"
    assert running.status_code == completed.status_code == 200
    assert 'data-scan-status="running"' in running.text
    assert "Search Running" in running.text
    assert "no overlapping run was started" not in running.text
    assert 'data-scan-status="success"' in completed.text
    assert "Fixture scan completed." in completed.text
    assert "Manual" in completed.text
    assert "Runs every 6 hours" in completed.text
    assert "Next scan" in completed.text
    assert "Search Now" in completed.text
    for value in ("3", "2", "7", "4 / 1"):
        assert value in completed.text


def test_real_zero_credential_pipeline_completes_without_external_calls(
    tmp_path: Path,
) -> None:
    application = _app(tmp_path, "m19-real-pipeline.db")

    async def scenario():
        async with application.router.lifespan_context(application):
            schedule = application.state.scan_scheduler.snapshot()
            assert application.state.settings.scan_interval_hours == 4
            assert schedule.interval_hours == 4
            assert schedule.next_run_at is not None
            with application.state.session_factory() as session:
                session.add(
                    CandidateProfile(
                        name="Scan Profile",
                        is_active=True,
                        years_experience=5,
                        target_roles_json=["Software Engineer"],
                        role_synonyms_json=[],
                        skills_json=[],
                        preferred_locations_json=["India"],
                        work_modes_json=["Remote"],
                        excluded_keywords_json=[],
                        notes="",
                    )
                )
                session.commit()
            controller = application.state.scan_controller
            assert await controller.start_manual() is True
            return await controller.wait_for_idle()

    snapshot = asyncio.run(scenario())

    assert snapshot.status == "partial"
    assert snapshot.trigger_type == "manual"
    assert snapshot.companies_checked == 0
    assert snapshot.sources_checked == 3
    assert snapshot.jobs_fetched == 0
    assert snapshot.errors_count == 4
    assert snapshot.errors == (
        "disabled search is not configured",
        "linkedin: disabled search is not configured",
        "naukri: disabled search is not configured",
        "indeed: disabled search is not configured",
    )
    assert "Checked 0 companies and 3 sources" in snapshot.summary
