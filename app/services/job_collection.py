import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.companies import Company
from app.providers.jobs.base import (
    ConnectorJob,
    JobConnector,
    JobConnectorError,
    connector_retry_count,
    reset_connector_retry_count,
)
from app.repositories.companies import CompanyRepository


MAX_SOURCE_ERROR_CHARS = 500


@dataclass(frozen=True)
class ConnectorSourceResult:
    company_id: int
    company_name: str
    source_type: str
    status: Literal["success", "failed"]
    jobs: tuple[ConnectorJob, ...]
    error_message: str | None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    retry_count: int = 0


@dataclass(frozen=True)
class ConnectorCollectionResult:
    sources_checked: int
    sources_succeeded: int
    sources_failed: int
    jobs_fetched: int
    source_results: tuple[ConnectorSourceResult, ...]


class JobCollectionService:
    def __init__(self, session: Session, *, concurrency: int) -> None:
        if not 1 <= concurrency <= 5:
            raise ValueError("Job-source concurrency must be between one and five")
        self.repository = CompanyRepository(session)
        self.concurrency = concurrency

    async def collect(self, connector: JobConnector) -> ConnectorCollectionResult:
        is_generic_fallback = connector.source_type == "custom"
        companies = (
            self.repository.list_generic_fallback_companies()
            if is_generic_fallback
            else self.repository.list_connector_ready_companies(connector.source_type)
        )
        semaphore = asyncio.Semaphore(self.concurrency)

        async def fetch(company: Company) -> ConnectorSourceResult:
            async with semaphore:
                started_at = utc_now()
                reset_connector_retry_count()
                try:
                    source_identifier = (
                        company.careers_url
                        if is_generic_fallback
                        else company.provider_identifier
                    )
                    jobs = await connector.fetch_open_jobs(source_identifier or "")
                    return ConnectorSourceResult(
                        company_id=company.id,
                        company_name=company.name,
                        source_type=connector.source_type,
                        status="success",
                        jobs=tuple(jobs),
                        error_message=None,
                        started_at=started_at,
                        finished_at=utc_now(),
                        retry_count=connector_retry_count(),
                    )
                except JobConnectorError as error:
                    message = str(error)[:MAX_SOURCE_ERROR_CHARS]
                except Exception:
                    message = "Unexpected connector failure"

                return ConnectorSourceResult(
                    company_id=company.id,
                    company_name=company.name,
                    source_type=connector.source_type,
                    status="failed",
                    jobs=(),
                    error_message=message,
                    started_at=started_at,
                    finished_at=utc_now(),
                    retry_count=connector_retry_count(),
                )

        results = tuple(await asyncio.gather(*(fetch(company) for company in companies)))
        succeeded = sum(result.status == "success" for result in results)
        failed = len(results) - succeeded
        return ConnectorCollectionResult(
            sources_checked=len(results),
            sources_succeeded=succeeded,
            sources_failed=failed,
            jobs_fetched=sum(len(result.jobs) for result in results),
            source_results=results,
        )
