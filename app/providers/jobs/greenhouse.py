from html import unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.providers.jobs.base import (
    ConnectorJob,
    JobConnector,
    JobConnectorError,
    record_connector_retry,
)


GREENHOUSE_JOBS_API = "https://boards-api.greenhouse.io/v1/boards"
MAX_GREENHOUSE_JOBS = 5000
_BOARD_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)

    def text(self) -> str:
        return "\n".join(self.parts)


class _GreenhouseLocation(BaseModel):
    name: str = Field(default="", max_length=1000)


class _GreenhouseJob(BaseModel):
    id: int | str
    internal_job_id: int | str | None
    title: str = Field(min_length=1, max_length=1000)
    location: _GreenhouseLocation | None = None
    absolute_url: str = Field(min_length=1, max_length=4000)
    content: str | None = Field(default=None, max_length=2_000_000)


class _GreenhouseResponse(BaseModel):
    jobs: list[_GreenhouseJob] = Field(max_length=MAX_GREENHOUSE_JOBS)


class GreenhouseConnector(JobConnector):
    source_type = "greenhouse"

    def __init__(self, client: httpx.AsyncClient, *, max_response_bytes: int) -> None:
        self.client = client
        self.max_response_bytes = max_response_bytes

    async def fetch_open_jobs(self, provider_identifier: str) -> list[ConnectorJob]:
        board_token = provider_identifier.strip()
        if not _BOARD_TOKEN_PATTERN.fullmatch(board_token):
            raise JobConnectorError("Greenhouse board identifier is invalid")

        payload = await self._request_with_one_safe_retry(board_token)
        try:
            response = _GreenhouseResponse.model_validate(json.loads(payload))
            return [
                self._map_job(job)
                for job in response.jobs
                if job.internal_job_id is not None
            ]
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError) as error:
            raise JobConnectorError("Greenhouse returned an invalid jobs response") from error

    async def _request_with_one_safe_retry(self, board_token: str) -> bytes:
        url = f"{GREENHOUSE_JOBS_API}/{quote(board_token, safe='')}/jobs"
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                async with self.client.stream(
                    "GET",
                    url,
                    headers={"Accept": "application/json"},
                    params={"content": "true"},
                ) as response:
                    if response.status_code >= 500 and attempt == 0:
                        record_connector_retry()
                        continue
                    if response.is_error:
                        raise JobConnectorError(
                            f"Greenhouse request failed with HTTP {response.status_code}"
                        )

                    content_type = response.headers.get("content-type", "")
                    if content_type and "application/json" not in content_type.casefold():
                        raise JobConnectorError("Greenhouse returned a non-JSON response")

                    content_length = response.headers.get("content-length")
                    if (
                        content_length
                        and content_length.isdigit()
                        and int(content_length) > self.max_response_bytes
                    ):
                        raise JobConnectorError("Greenhouse response exceeds the configured limit")

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_response_bytes:
                            raise JobConnectorError(
                                "Greenhouse response exceeds the configured limit"
                            )
                    return bytes(body)
            except JobConnectorError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
                if attempt == 1:
                    break
                record_connector_retry()

        raise JobConnectorError("Greenhouse request failed") from last_error

    def _map_job(self, job: _GreenhouseJob) -> ConnectorJob:
        source_job_id = str(job.id).strip()
        title = " ".join(job.title.split())
        job_url = job.absolute_url.strip()
        parts = urlsplit(job_url)
        if (
            not source_job_id
            or len(source_job_id) > 255
            or not title
            or parts.scheme.casefold() not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise ValueError("Greenhouse job fields are invalid")

        location = ""
        if job.location is not None:
            location = " ".join(job.location.name.split())
        return ConnectorJob(
            source_type=self.source_type,
            source_job_id=source_job_id,
            title=title,
            location_text=location,
            description=self._plain_text(job.content or ""),
            job_url=job_url,
        )

    @staticmethod
    def _plain_text(content: str) -> str:
        parser = _TextExtractor()
        parser.feed(unescape(unescape(content)))
        parser.close()
        return parser.text()
