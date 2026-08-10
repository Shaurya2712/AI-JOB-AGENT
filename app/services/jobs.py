from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.companies import Company
from app.models.jobs import Job
from app.providers.jobs.base import ConnectorJob
from app.repositories.jobs import JobRepository
from app.services.job_normalization import (
    NormalizedConnectorJob,
    cross_source_signature,
    normalize_connector_job,
)


class JobCompanyNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class JobUpsertResult:
    job: Job
    created: bool
    updated: bool
    materially_changed: bool
    upgraded_to_full: bool = False


class JobUpsertService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = JobRepository(session)

    def upsert(
        self,
        company_id: int,
        connector_job: ConnectorJob,
        *,
        seen_at: datetime | None = None,
    ) -> JobUpsertResult:
        return self.upsert_many(
            company_id,
            [connector_job],
            seen_at=seen_at,
        )[0]

    def upsert_many(
        self,
        company_id: int,
        connector_jobs: list[ConnectorJob],
        *,
        seen_at: datetime | None = None,
    ) -> tuple[JobUpsertResult, ...]:
        company = self.session.get(Company, company_id)
        if company is None:
            raise JobCompanyNotFoundError(f"Company {company_id} was not found")
        observed_at = self._observed_at(seen_at)

        try:
            results = tuple(
                self._upsert_normalized(
                    company,
                    normalize_connector_job(company_id, connector_job),
                    observed_at,
                )
                for connector_job in connector_jobs
            )
            self.session.commit()
            for result in results:
                self.session.refresh(result.job)
            return results
        except Exception:
            self.session.rollback()
            raise

    def _upsert_normalized(
        self,
        company: Company,
        normalized: NormalizedConnectorJob,
        observed_at: datetime,
    ) -> JobUpsertResult:
        signature = cross_source_signature(
            company.name,
            normalized.title,
            normalized.location_text,
        )
        job = self.repository.find_match(
            company.id,
            source_type=normalized.source_type,
            source_job_id=normalized.source_job_id,
            canonical_url=normalized.canonical_url,
            dedupe_signature=normalized.dedupe_signature,
            allow_fallback=bool(normalized.description),
        )
        if job is None and signature is not None:
            job = self.repository.find_unique_partial_cross_source_match(signature)
        if job is None:
            job = Job(
                company_id=company.id,
                company_name=company.name,
                source_type=normalized.source_type,
                source_job_id=normalized.source_job_id,
                canonical_url=normalized.canonical_url,
                title=normalized.title,
                normalized_title=normalized.normalized_title,
                location_text=normalized.location_text,
                description=normalized.description,
                description_hash=normalized.description_hash,
                dedupe_signature=normalized.dedupe_signature,
                cross_source_signature=signature,
                data_completeness="full",
                discovered_at=observed_at,
                last_seen_at=observed_at,
                consecutive_missing_scans=0,
                lifecycle_status="open",
                created_at=observed_at,
                updated_at=observed_at,
            )
            self.repository.add(job)
            return JobUpsertResult(
                job=job,
                created=True,
                updated=False,
                materially_changed=True,
            )

        upgraded_to_full = job.data_completeness == "partial"
        identity_changed = (
            job.company_id != company.id
            or job.company_name != company.name
            or job.source_type != normalized.source_type
            or job.source_job_id != normalized.source_job_id
            or job.canonical_url != normalized.canonical_url
            or job.data_completeness != "full"
        )
        material_changed = (
            job.title != normalized.title
            or job.normalized_title != normalized.normalized_title
            or job.location_text != normalized.location_text
            or job.description_hash != normalized.description_hash
            or job.cross_source_signature != signature
            or job.data_completeness != "full"
        )
        updated = identity_changed or material_changed

        job.company_id = company.id
        job.company = company
        job.company_name = company.name
        job.source_type = normalized.source_type
        job.source_job_id = normalized.source_job_id
        job.canonical_url = normalized.canonical_url
        job.title = normalized.title
        job.normalized_title = normalized.normalized_title
        job.location_text = normalized.location_text
        job.description = normalized.description
        job.description_hash = normalized.description_hash
        job.dedupe_signature = normalized.dedupe_signature
        job.cross_source_signature = signature
        job.data_completeness = "full"
        job.last_seen_at = self._latest(job.last_seen_at, observed_at)
        job.updated_at = observed_at
        return JobUpsertResult(
            job=job,
            created=False,
            updated=updated,
            materially_changed=material_changed,
            upgraded_to_full=upgraded_to_full,
        )

    @staticmethod
    def _observed_at(value: datetime | None) -> datetime:
        observed_at = value or utc_now()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("Job observation timestamp must include a timezone")
        return observed_at.astimezone(timezone.utc)

    @staticmethod
    def _latest(current: datetime, observed: datetime) -> datetime:
        if current.tzinfo is None or current.utcoffset() is None:
            current = current.replace(tzinfo=timezone.utc)
        return max(current.astimezone(timezone.utc), observed)
