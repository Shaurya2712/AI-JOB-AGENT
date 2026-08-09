from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import utc_now
from app.models.companies import Company
from app.models.scan_history import ScanRun, ScanSourceResult
from app.services.scans import (
    ScanRunSnapshot,
    ScanSourceSnapshot,
    ScanTrigger,
)


RECENT_RUN_LIMIT = 25
RECENT_FAILURE_LIMIT = 50
MAX_RUN_SUMMARY_CHARS = 4_000
MAX_SOURCE_ERROR_CHARS = 500


@dataclass(frozen=True)
class ScanRunView:
    id: int
    trigger_type: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    companies_checked: int
    sources_checked: int
    jobs_fetched: int
    jobs_new: int
    jobs_updated: int
    jobs_scored: int
    strong_matches: int
    errors_count: int
    summary: str


@dataclass(frozen=True)
class SourceFailureView:
    scan_run_id: int
    company_name: str
    source_type: str
    finished_at: datetime
    jobs_fetched: int
    jobs_new: int
    jobs_updated: int
    retry_count: int
    error_message: str


@dataclass(frozen=True)
class ScanHealthView:
    runs: tuple[ScanRunView, ...]
    source_failures: tuple[SourceFailureView, ...]
    successful_runs: int
    unhealthy_runs: int


class ScanHistoryService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def recover_interrupted_runs(self) -> int:
        recovered_at = utc_now()
        with self.session_factory() as session:
            interrupted = tuple(
                session.scalars(
                    select(ScanRun).where(ScanRun.status == "running")
                )
            )
            for run in interrupted:
                run.status = "failed"
                run.finished_at = recovered_at
                run.errors_count += 1
                run.summary = _bounded_summary(
                    run.summary,
                    ("Application restarted before this scan completed.",),
                )
            session.commit()
            return len(interrupted)

    def start_run(self, trigger_type: ScanTrigger, started_at: datetime) -> int:
        with self.session_factory() as session:
            run = ScanRun(
                trigger_type=trigger_type,
                started_at=started_at,
                status="running",
                summary="Scan is running.",
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return run.id

    def finish_run(
        self,
        snapshot: ScanRunSnapshot,
        source_results: tuple[ScanSourceSnapshot, ...],
    ) -> None:
        if snapshot.run_id is None:
            return
        with self.session_factory() as session:
            run = session.get(ScanRun, snapshot.run_id)
            if run is None:
                raise LookupError(f"Scan run {snapshot.run_id} was not found")
            run.finished_at = snapshot.finished_at
            run.status = snapshot.status
            run.companies_checked = snapshot.companies_checked
            run.sources_checked = snapshot.sources_checked
            run.jobs_fetched = snapshot.jobs_fetched
            run.jobs_new = snapshot.jobs_new
            run.jobs_updated = snapshot.jobs_updated
            run.jobs_scored = snapshot.jobs_scored
            run.strong_matches = snapshot.strong_matches
            run.errors_count = snapshot.errors_count
            run.summary = _bounded_summary(snapshot.summary, snapshot.errors)
            session.add_all(
                ScanSourceResult(
                    scan_run_id=run.id,
                    company_id=result.company_id,
                    source_type=result.source_type[:40],
                    started_at=result.started_at,
                    finished_at=result.finished_at,
                    status=result.status,
                    jobs_fetched=result.jobs_fetched,
                    jobs_new=result.jobs_new,
                    jobs_updated=result.jobs_updated,
                    error_message=(
                        result.error_message[:MAX_SOURCE_ERROR_CHARS]
                        if result.error_message
                        else None
                    ),
                    retry_count=result.retry_count,
                )
                for result in source_results
            )
            session.commit()

    def latest_snapshot(self) -> ScanRunSnapshot | None:
        with self.session_factory() as session:
            run = session.scalar(
                select(ScanRun).order_by(ScanRun.started_at.desc(), ScanRun.id.desc())
            )
            if run is None:
                return None
            return ScanRunSnapshot(
                run_id=run.id,
                status=run.status,  # type: ignore[arg-type]
                trigger_type=run.trigger_type,  # type: ignore[arg-type]
                started_at=run.started_at,
                finished_at=run.finished_at,
                companies_checked=run.companies_checked,
                sources_checked=run.sources_checked,
                jobs_fetched=run.jobs_fetched,
                jobs_new=run.jobs_new,
                jobs_updated=run.jobs_updated,
                jobs_scored=run.jobs_scored,
                strong_matches=run.strong_matches,
                errors_count=run.errors_count,
                summary=run.summary,
            )

    def recent_health(self) -> ScanHealthView:
        with self.session_factory() as session:
            runs = tuple(
                session.scalars(
                    select(ScanRun)
                    .order_by(ScanRun.started_at.desc(), ScanRun.id.desc())
                    .limit(RECENT_RUN_LIMIT)
                )
            )
            failure_rows = tuple(
                session.execute(
                    select(ScanSourceResult, Company.name)
                    .outerjoin(Company, Company.id == ScanSourceResult.company_id)
                    .where(ScanSourceResult.status == "failed")
                    .order_by(
                        ScanSourceResult.finished_at.desc(),
                        ScanSourceResult.id.desc(),
                    )
                    .limit(RECENT_FAILURE_LIMIT)
                )
            )
            run_views = tuple(_run_view(run) for run in runs)
            source_failures = tuple(
                SourceFailureView(
                    scan_run_id=result.scan_run_id,
                    company_name=company_name or "Unassigned source",
                    source_type=result.source_type,
                    finished_at=result.finished_at,
                    jobs_fetched=result.jobs_fetched,
                    jobs_new=result.jobs_new,
                    jobs_updated=result.jobs_updated,
                    retry_count=result.retry_count,
                    error_message=result.error_message or "Source failed without details",
                )
                for result, company_name in failure_rows
            )
        return ScanHealthView(
            runs=run_views,
            source_failures=source_failures,
            successful_runs=sum(run.status == "success" for run in run_views),
            unhealthy_runs=sum(
                run.status in {"partial", "failed"} for run in run_views
            ),
        )


def _bounded_summary(summary: str, errors: tuple[str, ...]) -> str:
    cleaned_summary = " ".join(summary.split())
    if errors:
        details = " | ".join(" ".join(error.split())[:500] for error in errors)
        cleaned_summary = f"{cleaned_summary} Error details: {details}"
    return cleaned_summary[:MAX_RUN_SUMMARY_CHARS]


def _run_view(run: ScanRun) -> ScanRunView:
    return ScanRunView(
        id=run.id,
        trigger_type=run.trigger_type,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        companies_checked=run.companies_checked,
        sources_checked=run.sources_checked,
        jobs_fetched=run.jobs_fetched,
        jobs_new=run.jobs_new,
        jobs_updated=run.jobs_updated,
        jobs_scored=run.jobs_scored,
        strong_matches=run.strong_matches,
        errors_count=run.errors_count,
        summary=run.summary,
    )
