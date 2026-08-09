import json
import re
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from app.providers.jobs.base import ConnectorJob, JobConnector, JobConnectorError


LEVER_GLOBAL_POSTINGS_API = "https://api.lever.co/v0/postings"
LEVER_EU_POSTINGS_API = "https://api.eu.lever.co/v0/postings"
LEVER_PAGE_SIZE = 100
MAX_LEVER_JOBS = 5000
_SITE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}")


class _LeverCategories(BaseModel):
    location: str | None = Field(default=None, max_length=1000)


class _LeverJob(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=1000)
    categories: _LeverCategories | None = None
    description_plain: str = Field(
        default="",
        alias="descriptionPlain",
        max_length=2_000_000,
    )
    hosted_url: str = Field(alias="hostedUrl", min_length=1, max_length=4000)


_LEVER_PAGE_ADAPTER = TypeAdapter(list[_LeverJob])


class _LeverHttpError(JobConnectorError):
    def __init__(self, status_code: int, skip: int) -> None:
        super().__init__(f"Lever request failed with HTTP {status_code}")
        self.status_code = status_code
        self.skip = skip


class LeverConnector(JobConnector):
    source_type = "lever"

    def __init__(self, client: httpx.AsyncClient, *, max_response_bytes: int) -> None:
        self.client = client
        self.max_response_bytes = max_response_bytes

    async def fetch_open_jobs(self, provider_identifier: str) -> list[ConnectorJob]:
        site = provider_identifier.strip()
        if not _SITE_PATTERN.fullmatch(site):
            raise JobConnectorError("Lever site identifier is invalid")

        try:
            return await self._fetch_all_pages(LEVER_GLOBAL_POSTINGS_API, site)
        except _LeverHttpError as error:
            if error.status_code != 404 or error.skip != 0:
                raise
        return await self._fetch_all_pages(LEVER_EU_POSTINGS_API, site)

    async def _fetch_all_pages(self, api_base_url: str, site: str) -> list[ConnectorJob]:
        jobs: list[ConnectorJob] = []
        response_bytes = 0

        for skip in range(0, MAX_LEVER_JOBS + LEVER_PAGE_SIZE, LEVER_PAGE_SIZE):
            payload = await self._request_page_with_one_safe_retry(api_base_url, site, skip)
            response_bytes += len(payload)
            if response_bytes > self.max_response_bytes:
                raise JobConnectorError("Lever response exceeds the configured limit")

            page = self._parse_page(payload)
            if skip >= MAX_LEVER_JOBS:
                if page:
                    raise JobConnectorError("Lever source exceeds the 5,000-job limit")
                return jobs
            jobs.extend(self._map_job(job) for job in page)
            if len(page) < LEVER_PAGE_SIZE:
                return jobs

        raise JobConnectorError("Lever pagination did not terminate")

    async def _request_page_with_one_safe_retry(
        self,
        api_base_url: str,
        site: str,
        skip: int,
    ) -> bytes:
        url = f"{api_base_url}/{quote(site, safe='')}"
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                async with self.client.stream(
                    "GET",
                    url,
                    headers={"Accept": "application/json"},
                    params={
                        "mode": "json",
                        "skip": skip,
                        "limit": LEVER_PAGE_SIZE,
                    },
                ) as response:
                    if response.status_code >= 500 and attempt == 0:
                        continue
                    if response.is_error:
                        raise _LeverHttpError(response.status_code, skip)

                    content_type = response.headers.get("content-type", "")
                    if content_type and "application/json" not in content_type.casefold():
                        raise JobConnectorError("Lever returned a non-JSON response")

                    content_length = response.headers.get("content-length")
                    if (
                        content_length
                        and content_length.isdigit()
                        and int(content_length) > self.max_response_bytes
                    ):
                        raise JobConnectorError("Lever response exceeds the configured limit")

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_response_bytes:
                            raise JobConnectorError("Lever response exceeds the configured limit")
                    return bytes(body)
            except JobConnectorError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
                if attempt == 1:
                    break

        raise JobConnectorError("Lever request failed") from last_error

    @staticmethod
    def _parse_page(payload: bytes) -> list[_LeverJob]:
        try:
            page = _LEVER_PAGE_ADAPTER.validate_python(json.loads(payload))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as error:
            raise JobConnectorError("Lever returned an invalid postings response") from error
        if len(page) > LEVER_PAGE_SIZE:
            raise JobConnectorError("Lever returned more postings than the requested page size")
        return page

    def _map_job(self, job: _LeverJob) -> ConnectorJob:
        source_job_id = job.id.strip()
        title = " ".join(job.text.split())
        job_url = job.hosted_url.strip()
        parts = urlsplit(job_url)
        if (
            not source_job_id
            or not title
            or parts.scheme.casefold() not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise JobConnectorError("Lever returned invalid posting fields")

        location = ""
        if job.categories is not None and job.categories.location:
            location = " ".join(job.categories.location.split())
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
