import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models.companies import Company
from app.models.notifications import NotificationLog
from app.models.scan_history import ScanRun, ScanSourceResult
from app.providers.jobs.base import ConnectorJob, JobConnector, record_connector_retry
from app.services.job_collection import ConnectorSourceResult, JobCollectionService
from app.services.notifications import NotificationDestinationService
from app.services.scans import (
    ApplicationScanPipeline,
    ScanController,
    ScanPipelineResult,
    ScanSourceSnapshot,
    _RunCounts,
)


STARTED_AT = datetime(2026, 8, 9, 14, 0, tzinfo=timezone.utc)


def _app(tmp_path: Path, name: str):
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
        )
    )


def _company(session) -> Company:
    company = Company(
        name="History Co",
        website_url="https://history.example",
        careers_url="https://history.example/jobs",
        provider_type="greenhouse",
        provider_identifier="history",
        discovery_source="seed",
        is_active=True,
        provider_supported=True,
        total_jobs_seen=0,
    )
    session.add(company)
    session.commit()
    session.refresh(company)
    return company


class SequenceRunner:
    def __init__(self, results: list[ScanPipelineResult]) -> None:
        self.results = results

    async def run(self, _trigger_type: str) -> ScanPipelineResult:
        return self.results.pop(0)


class ExplodingRunner:
    async def run(self, _trigger_type: str) -> ScanPipelineResult:
        raise RuntimeError("private implementation detail")


def test_success_partial_source_health_and_counts_persist_across_restart(
    tmp_path: Path,
) -> None:
    database_name = "m21-history.db"
    application = _app(tmp_path, database_name)
    long_error = "source unavailable " + ("x" * 700)

    async def first_process() -> httpx.Response:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                company = _company(session)
                company_id = company.id
                NotificationDestinationService(session).configure(
                    "scan_summary",
                    name="Scan status",
                    telegram_chat_id="-21001",
                    is_enabled=True,
                )

            success_source = ScanSourceSnapshot(
                company_id=company_id,
                source_type="greenhouse",
                started_at=STARTED_AT,
                finished_at=STARTED_AT + timedelta(seconds=2),
                status="success",
                jobs_fetched=6,
                jobs_new=4,
                jobs_updated=1,
            )
            failed_source = ScanSourceSnapshot(
                company_id=company_id,
                source_type="greenhouse",
                started_at=STARTED_AT + timedelta(hours=1),
                finished_at=STARTED_AT + timedelta(hours=1, seconds=3),
                status="failed",
                error_message=long_error,
                retry_count=1,
            )
            runner = SequenceRunner(
                [
                    ScanPipelineResult(
                        companies_checked=1,
                        sources_checked=1,
                        jobs_fetched=6,
                        jobs_new=4,
                        jobs_updated=1,
                        jobs_scored=4,
                        strong_matches=2,
                        errors_count=0,
                        errors=(),
                        summary="Successful fixture scan.",
                        source_results=(success_source,),
                    ),
                    ScanPipelineResult(
                        companies_checked=1,
                        sources_checked=1,
                        jobs_fetched=0,
                        jobs_new=0,
                        jobs_updated=0,
                        jobs_scored=0,
                        strong_matches=0,
                        errors_count=1,
                        errors=(long_error,),
                        summary="Partial fixture scan.",
                        source_results=(failed_source,),
                    ),
                ]
            )
            controller = ScanController(
                runner,
                completion_notifier=application.state.notification_service,
                history_writer=application.state.scan_history,
            )
            application.state.scan_controller = controller
            assert await controller.start_manual() is True
            assert (await controller.wait_for_idle()).status == "success"
            assert await controller.run_scheduled() is True
            assert controller.snapshot().status == "partial"

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application),
                base_url="http://testserver",
            ) as client:
                page = await client.get("/scans")

            with application.state.session_factory() as session:
                runs = tuple(session.scalars(select(ScanRun).order_by(ScanRun.id)))
                sources = tuple(
                    session.scalars(
                        select(ScanSourceResult).order_by(ScanSourceResult.id)
                    )
                )
                notifications = tuple(
                    session.scalars(
                        select(NotificationLog).order_by(NotificationLog.id)
                    )
                )
                assert [run.status for run in runs] == ["success", "partial"]
                assert runs[0].jobs_fetched == 6
                assert runs[0].jobs_new == 4
                assert runs[0].jobs_updated == 1
                assert runs[0].jobs_scored == 4
                assert runs[0].strong_matches == 2
                assert "Error details: source unavailable" in runs[1].summary
                assert [source.status for source in sources] == ["success", "failed"]
                assert sources[0].jobs_fetched == 6
                assert sources[0].jobs_new == 4
                assert sources[0].jobs_updated == 1
                assert sources[1].retry_count == 1
                assert len(sources[1].error_message or "") == 500
                assert len(notifications) == 2
                assert {item.scan_run_id for item in notifications} == {
                    runs[0].id,
                    runs[1].id,
                }
            return page

    page = asyncio.run(first_process())

    assert page.status_code == 200
    assert "Run history" in page.text
    assert "Source failures" in page.text
    assert "Successful fixture scan." in page.text
    assert "Partial fixture scan." in page.text
    assert "History Co" in page.text
    assert "source unavailable" in page.text
    assert 'data-scan-status="success"' in page.text
    assert 'data-scan-status="partial"' in page.text

    restarted = _app(tmp_path, database_name)

    async def second_process() -> tuple[httpx.Response, httpx.Response, str, int]:
        async with restarted.router.lifespan_context(restarted):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=restarted),
                base_url="http://testserver",
            ) as client:
                dashboard = await client.get("/")
                history = await client.get("/scans")
            latest = restarted.state.scan_controller.snapshot()
            return dashboard, history, latest.status, latest.errors_count

    dashboard, history, latest_status, latest_errors = asyncio.run(second_process())

    assert dashboard.status_code == history.status_code == 200
    assert latest_status == "partial"
    assert latest_errors == 1
    assert 'data-scan-status="partial"' in dashboard.text
    assert "Successful fixture scan." in history.text
    assert "Partial fixture scan." in history.text


def test_failed_runs_and_interrupted_runs_remain_inspectable(tmp_path: Path) -> None:
    database_name = "m21-failures.db"
    first_application = _app(tmp_path, database_name)

    async def leave_interrupted_run() -> int:
        async with first_application.router.lifespan_context(first_application):
            return first_application.state.scan_history.start_run(
                "scheduled",
                STARTED_AT,
            )

    interrupted_id = asyncio.run(leave_interrupted_run())
    restarted = _app(tmp_path, database_name)

    async def recover_and_fail() -> httpx.Response:
        async with restarted.router.lifespan_context(restarted):
            recovered = restarted.state.scan_controller.snapshot()
            assert recovered.run_id == interrupted_id
            assert recovered.status == "failed"
            assert recovered.finished_at is not None

            controller = ScanController(
                ExplodingRunner(),
                history_writer=restarted.state.scan_history,
            )
            restarted.state.scan_controller = controller
            assert await controller.start_manual() is True
            failed = await controller.wait_for_idle()
            assert failed.status == "failed"
            assert failed.errors == ("Unexpected scan pipeline failure",)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=restarted),
                base_url="http://testserver",
            ) as client:
                page = await client.get("/scans")
            with restarted.state.session_factory() as session:
                runs = tuple(session.scalars(select(ScanRun).order_by(ScanRun.id)))
                assert len(runs) == 2
                assert all(run.status == "failed" for run in runs)
                assert runs[0].finished_at is not None
                assert runs[0].errors_count == 1
                assert "Application restarted before" in runs[0].summary
                assert "Unexpected scan pipeline failure" in runs[1].summary
            return page

    page = asyncio.run(recover_and_fail())

    assert page.status_code == 200
    assert page.text.count('data-scan-status="failed"') == 2
    assert "Application restarted before this scan completed." in page.text
    assert "Unexpected scan pipeline failure" in page.text


def test_pipeline_emits_source_outcomes_after_persistence_and_failure(
    tmp_path: Path,
) -> None:
    application = _app(tmp_path, "m21-pipeline-sources.db")

    class RetryingConnector(JobConnector):
        source_type = "greenhouse"

        async def fetch_open_jobs(self, _provider_identifier: str):
            record_connector_retry()
            return [
                ConnectorJob(
                    source_type="greenhouse",
                    source_job_id="history-1",
                    title="Backend Engineer",
                    location_text="Remote",
                    description="Build Python services.",
                    job_url="https://jobs.example/history-1",
                )
            ]

    async def scenario() -> _RunCounts:
        async with application.router.lifespan_context(application):
            with application.state.session_factory() as session:
                company_id = _company(session).id
            pipeline = ApplicationScanPipeline(
                application.state.session_factory,
                application.state.settings,
            )
            counts = _RunCounts()
            with application.state.session_factory() as session:
                collected = await JobCollectionService(
                    session,
                    concurrency=1,
                ).collect(RetryingConnector())
            assert collected.sources_checked == 1
            assert collected.source_results[0].retry_count == 1
            pipeline._persist_source(collected.source_results[0], counts)
            pipeline._persist_source(
                ConnectorSourceResult(
                    company_id=company_id,
                    company_name="History Co",
                    source_type="greenhouse",
                    status="failed",
                    jobs=(),
                    error_message="Greenhouse fixture unavailable",
                    started_at=STARTED_AT + timedelta(hours=1),
                    finished_at=STARTED_AT + timedelta(hours=1, seconds=2),
                    retry_count=1,
                ),
                counts,
            )
            return counts

    counts = asyncio.run(scenario())

    assert counts.jobs_new == 1
    assert counts.jobs_updated == 0
    assert counts.errors_count == 1
    assert len(counts.source_results) == 2
    assert counts.source_results[0].status == "success"
    assert counts.source_results[0].jobs_fetched == 1
    assert counts.source_results[0].jobs_new == 1
    assert counts.source_results[0].retry_count == 1
    assert counts.source_results[1].status == "failed"
    assert counts.source_results[1].retry_count == 1
    assert counts.source_results[1].error_message == (
        "Greenhouse fixture unavailable"
    )
