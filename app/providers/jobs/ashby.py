import json
import re
from urllib.parse import quote, unquote, urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.providers.jobs.base import ConnectorJob, JobConnector, JobConnectorError


ASHBY_JOB_BOARD_API = "https://api.ashbyhq.com/posting-api/job-board"
MAX_ASHBY_JOBS = 5000
_BOARD_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}")
_SOURCE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]{0,254}")


class _AshbyJob(BaseModel):
    title: str = Field(min_length=1, max_length=1000)
    location: str | None = Field(default=None, max_length=1000)
    description_plain: str = Field(
        default="",
        alias="descriptionPlain",
        max_length=2_000_000,
    )
    job_url: str = Field(alias="jobUrl", min_length=1, max_length=4000)
    is_listed: bool = Field(alias="isListed")


class _AshbyResponse(BaseModel):
    api_version: str = Field(alias="apiVersion", min_length=1, max_length=20)
    jobs: list[_AshbyJob] = Field(max_length=MAX_ASHBY_JOBS)


class AshbyConnector(JobConnector):
    source_type = "ashby"

    def __init__(self, client: httpx.AsyncClient, *, max_response_bytes: int) -> None:
        self.client = client
        self.max_response_bytes = max_response_bytes

    async def fetch_open_jobs(self, provider_identifier: str) -> list[ConnectorJob]:
        board_name = provider_identifier.strip()
        if not _BOARD_NAME_PATTERN.fullmatch(board_name):
            raise JobConnectorError("Ashby board identifier is invalid")

        payload = await self._request_with_one_safe_retry(board_name)
        try:
            response = _AshbyResponse.model_validate(json.loads(payload))
            return [self._map_job(job) for job in response.jobs if job.is_listed]
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as error:
            raise JobConnectorError("Ashby returned an invalid jobs response") from error

    async def _request_with_one_safe_retry(self, board_name: str) -> bytes:
        url = f"{ASHBY_JOB_BOARD_API}/{quote(board_name, safe='')}"
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                async with self.client.stream(
                    "GET",
                    url,
                    headers={"Accept": "application/json"},
                    params={"includeCompensation": "false"},
                ) as response:
                    if response.status_code >= 500 and attempt == 0:
                        continue
                    if response.is_error:
                        raise JobConnectorError(
                            f"Ashby request failed with HTTP {response.status_code}"
                        )

                    content_type = response.headers.get("content-type", "")
                    if content_type and "application/json" not in content_type.casefold():
                        raise JobConnectorError("Ashby returned a non-JSON response")

                    content_length = response.headers.get("content-length")
                    if (
                        content_length
                        and content_length.isdigit()
                        and int(content_length) > self.max_response_bytes
                    ):
                        raise JobConnectorError("Ashby response exceeds the configured limit")

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_response_bytes:
                            raise JobConnectorError("Ashby response exceeds the configured limit")
                    return bytes(body)
            except JobConnectorError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
                if attempt == 1:
                    break

        raise JobConnectorError("Ashby request failed") from last_error

    def _map_job(self, job: _AshbyJob) -> ConnectorJob:
        title = " ".join(job.title.split())
        job_url = job.job_url.strip()
        parts = urlsplit(job_url)
        path_segments = [
            unquote(segment).strip()
            for segment in parts.path.split("/")
            if unquote(segment).strip()
        ]
        source_job_id = path_segments[-1] if path_segments else ""
        if (
            not title
            or parts.scheme.casefold() not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or not _SOURCE_ID_PATTERN.fullmatch(source_job_id)
        ):
            raise JobConnectorError("Ashby returned invalid job fields")

        location = " ".join((job.location or "").split())
        description = "\n".join(
            " ".join(line.split())
            for line in job.description_plain.splitlines()
            if line.strip()
        )
        return ConnectorJob(
            source_type=self.source_type,
            source_job_id=source_job_id,
            title=title,
            location_text=location,
            description=description,
            job_url=job_url,
        )
