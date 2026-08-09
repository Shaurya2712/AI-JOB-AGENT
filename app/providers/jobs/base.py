from abc import ABC, abstractmethod
from dataclasses import dataclass


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
