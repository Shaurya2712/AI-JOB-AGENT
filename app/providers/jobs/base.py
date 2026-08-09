from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class _RetryCounter:
    count: int = 0


_source_retry_counter: ContextVar[_RetryCounter | None] = ContextVar(
    "job_source_retry_counter",
    default=None,
)


def reset_connector_retry_count() -> None:
    _source_retry_counter.set(_RetryCounter())


def record_connector_retry() -> None:
    counter = _source_retry_counter.get()
    if counter is not None:
        counter.count += 1


def connector_retry_count() -> int:
    counter = _source_retry_counter.get()
    return counter.count if counter is not None else 0


@dataclass(frozen=True)
class ConnectorJob:
    source_type: str
    source_job_id: str
    title: str
    location_text: str
    description: str
    job_url: str


class JobConnectorError(RuntimeError):
    pass


class JobConnector(ABC):
    source_type: str

    @abstractmethod
    async def fetch_open_jobs(self, provider_identifier: str) -> list[ConnectorJob]:
        raise NotImplementedError
