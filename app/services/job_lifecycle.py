from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timezone
import re

from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.companies import Company
from app.models.jobs import Job
from app.repositories.jobs import JobRepository


POSSIBLY_CLOSED_AFTER_MISSING_SCANS = 2
_SOURCE_TYPE_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")


class JobLifecycleCompanyNotFoundError(LookupError):
    pass


class JobLifecycleJobNotFoundError(LookupError):
    pass


class JobLifecycleScopeError(ValueError):
    pass


@dataclass(frozen=True)
class LifecycleReconciliationResult:
    scan_applied: bool
    jobs_checked: int
    jobs_seen: int
    jobs_missing: int
    jobs_reopened: int
    jobs_marked_possibly_closed: int
    jobs_closed: int


@dataclass(frozen=True)
class ExplicitClosureResult:
    job: Job
    transitioned: bool


class JobLifecycleService:
    def __init__(
        self,
        session: Session,
        *,
        close_after_missing_scans: int,
    ) -> None:
        if not 3 <= close_after_missing_scans <= 20:
            raise ValueError("Lifecycle close threshold must be between three and twenty")
        self.session = session
        self.repository = JobRepository(session)
        self.close_after_missing_scans = close_after_missing_scans

    def reconcile_source(
        self,
        company_id: int,
        source_type: str,
        seen_job_ids: Collection[int],
        *,
        scan_succeeded: bool,
        reconciled_at: datetime | None = None,
    ) -> LifecycleReconciliationResult:
        if not scan_succeeded:
            return LifecycleReconciliationResult(
                scan_applied=False,
                jobs_checked=0,
                jobs_seen=0,
                jobs_missing=0,
                jobs_reopened=0,
                jobs_marked_possibly_closed=0,
                jobs_closed=0,
            )

        normalized_source = source_type.strip().casefold()
        if not _SOURCE_TYPE_PATTERN.fullmatch(normalized_source):
            raise JobLifecycleScopeError("Lifecycle source type is invalid")
        if self.session.get(Company, company_id) is None:
            raise JobLifecycleCompanyNotFoundError(
                f"Company {company_id} was not found"
            )
        observed_at = self._observed_at(reconciled_at)
        seen_ids = set(seen_job_ids)
        if any(job_id <= 0 for job_id in seen_ids):
            raise JobLifecycleScopeError("Lifecycle seen-job identifiers are invalid")

        try:
            jobs = self.repository.list_for_source(company_id, normalized_source)
            known_ids = {job.id for job in jobs}
            unknown_ids = seen_ids - known_ids
            if unknown_ids:
                raise JobLifecycleScopeError(
                    "Lifecycle seen jobs do not belong to the reconciled source"
                )

            reopened = 0
            possibly_closed = 0
            closed = 0
            for job in jobs:
                if job.id in seen_ids:
                    if job.lifecycle_status != "open":
                        reopened += 1
                    if (
                        job.lifecycle_status != "open"
                        or job.consecutive_missing_scans != 0
                    ):
                        job.lifecycle_status = "open"
                        job.consecutive_missing_scans = 0
                        job.updated_at = observed_at
                    continue

                if job.lifecycle_status == "closed":
                    continue

                previous_status = job.lifecycle_status
                job.consecutive_missing_scans += 1
                if job.consecutive_missing_scans >= self.close_after_missing_scans:
                    job.lifecycle_status = "closed"
                elif (
                    job.consecutive_missing_scans
                    >= POSSIBLY_CLOSED_AFTER_MISSING_SCANS
                ):
                    job.lifecycle_status = "possibly_closed"
                else:
                    job.lifecycle_status = "open"
                job.updated_at = observed_at

                if (
                    previous_status != "possibly_closed"
                    and job.lifecycle_status == "possibly_closed"
                ):
                    possibly_closed += 1
                if previous_status != "closed" and job.lifecycle_status == "closed":
                    closed += 1

            self.session.commit()
            return LifecycleReconciliationResult(
                scan_applied=True,
                jobs_checked=len(jobs),
                jobs_seen=len(seen_ids),
                jobs_missing=len(jobs) - len(seen_ids),
                jobs_reopened=reopened,
                jobs_marked_possibly_closed=possibly_closed,
                jobs_closed=closed,
            )
        except Exception:
            self.session.rollback()
            raise

    def mark_explicitly_closed(
        self,
        job_id: int,
        *,
        closed_at: datetime | None = None,
    ) -> ExplicitClosureResult:
        observed_at = self._observed_at(closed_at)
        try:
            job = self.repository.get(job_id)
            if job is None:
                raise JobLifecycleJobNotFoundError(f"Job {job_id} was not found")
            transitioned = job.lifecycle_status != "closed"
            if transitioned:
                job.lifecycle_status = "closed"
                job.updated_at = observed_at
                self.session.commit()
            return ExplicitClosureResult(job=job, transitioned=transitioned)
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _observed_at(value: datetime | None) -> datetime:
        observed_at = value or utc_now()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("Lifecycle timestamp must include a timezone")
        return observed_at.astimezone(timezone.utc)
