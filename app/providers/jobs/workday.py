import asyncio
from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
import re
from urllib.parse import quote, unquote, urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.providers.jobs.base import ConnectorJob, JobConnector, JobConnectorError


WORKDAY_PAGE_SIZE = 20
MAX_WORKDAY_JOBS = 5000
_WORKDAY_HOST_PATTERN = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.wd[0-9]{1,4}\.myworkdayjobs\.com"
)
_PATH_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]{0,127}")


class _TextExtractor(HTMLParser):
    _BLOCK_TAGS = frozenset(
        {"br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "tr"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[list[str]] = [[]]

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.casefold() in self._BLOCK_TAGS:
            self._line_break()

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._BLOCK_TAGS:
            self._line_break()

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.lines[-1].append(value)

    def _line_break(self) -> None:
        if self.lines[-1]:
            self.lines.append([])

    def text(self) -> str:
        return "\n".join(" ".join(line) for line in self.lines if line)


class _WorkdayJobSummary(BaseModel):
    title: str = Field(min_length=1, max_length=1000)
    external_path: str = Field(alias="externalPath", min_length=1, max_length=4000)


class _WorkdayJobsPage(BaseModel):
    total: int = Field(ge=0)
    job_postings: list[_WorkdayJobSummary] = Field(
        alias="jobPostings",
        max_length=WORKDAY_PAGE_SIZE,
    )


class _WorkdayJobInfo(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=1000)
    job_description: str = Field(alias="jobDescription", max_length=2_000_000)
    location: str = Field(default="", max_length=1000)
    posted: bool
    can_apply: bool = Field(alias="canApply")


class _WorkdayJobDetail(BaseModel):
    job_posting_info: _WorkdayJobInfo = Field(alias="jobPostingInfo")


@dataclass(frozen=True)
class _WorkdayIdentifier:
    hostname: str
    tenant: str
    site: str


@dataclass
class _ResponseBudget:
    limit: int
    used: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def add(self, size: int) -> None:
        async with self.lock:
            self.used += size
            if self.used > self.limit:
                raise JobConnectorError("Workday responses exceed the configured limit")


class WorkdayConnector(JobConnector):
    source_type = "workday"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_response_bytes: int,
        request_concurrency: int,
    ) -> None:
        if not 1 <= request_concurrency <= 5:
            raise ValueError("Workday request concurrency must be between one and five")
        self.client = client
        self.max_response_bytes = max_response_bytes
        self.request_semaphore = asyncio.Semaphore(request_concurrency)

    async def fetch_open_jobs(self, provider_identifier: str) -> list[ConnectorJob]:
        identifier = self._parse_identifier(provider_identifier)
        budget = _ResponseBudget(self.max_response_bytes)
        jobs: list[ConnectorJob] = []
        offset = 0
        expected_total: int | None = None

        while expected_total is None or offset < expected_total:
            payload = await self._request_json_with_one_safe_retry(
                "POST",
                self._jobs_url(identifier),
                budget,
                json_body={
                    "appliedFacets": {},
                    "limit": WORKDAY_PAGE_SIZE,
                    "offset": offset,
                    "searchText": "",
                },
            )
            page = self._parse_jobs_page(payload)
            if page.total > MAX_WORKDAY_JOBS:
                raise JobConnectorError("Workday source exceeds the 5,000-job limit")
            if expected_total is None:
                expected_total = page.total
            if not page.job_postings:
                if offset < expected_total:
                    raise JobConnectorError("Workday pagination ended before the reported total")
                return jobs

            detail_results = await asyncio.gather(
                *(
                    self._fetch_job_detail(identifier, summary.external_path, budget)
                    for summary in page.job_postings
                ),
                return_exceptions=True,
            )
            for result in detail_results:
                if isinstance(result, JobConnectorError):
                    raise result
                if isinstance(result, Exception):
                    raise JobConnectorError("Workday job-detail request failed") from result
                if result is not None:
                    jobs.append(result)

            offset += len(page.job_postings)
            if offset >= expected_total:
                return jobs

        return jobs

    async def _fetch_job_detail(
        self,
        identifier: _WorkdayIdentifier,
        external_path: str,
        budget: _ResponseBudget,
    ) -> ConnectorJob | None:
        path = self._validate_external_path(external_path)
        payload = await self._request_json_with_one_safe_retry(
            "GET",
            self._detail_url(identifier, path),
            budget,
        )
        try:
            detail = _WorkdayJobDetail.model_validate(json.loads(payload))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as error:
            raise JobConnectorError("Workday returned an invalid job-detail response") from error

        info = detail.job_posting_info
        if not info.posted or not info.can_apply:
            return None
        return self._map_job(identifier, path, info)

    async def _request_json_with_one_safe_retry(
        self,
        method: str,
        url: str,
        budget: _ResponseBudget,
        *,
        json_body: dict[str, object] | None = None,
    ) -> bytes:
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                async with self.request_semaphore:
                    async with self.client.stream(
                        method,
                        url,
                        headers={"Accept": "application/json"},
                        json=json_body,
                    ) as response:
                        if response.status_code >= 500 and attempt == 0:
                            continue
                        if response.is_error:
                            raise JobConnectorError(
                                f"Workday request failed with HTTP {response.status_code}"
                            )

                        content_type = response.headers.get("content-type", "")
                        if content_type and "application/json" not in content_type.casefold():
                            raise JobConnectorError("Workday returned a non-JSON response")

                        content_length = response.headers.get("content-length")
                        if (
                            content_length
                            and content_length.isdigit()
                            and int(content_length) > self.max_response_bytes
                        ):
                            raise JobConnectorError(
                                "Workday response exceeds the configured limit"
                            )

                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > self.max_response_bytes:
                                raise JobConnectorError(
                                    "Workday response exceeds the configured limit"
                                )
                payload = bytes(body)
                await budget.add(len(payload))
                return payload
            except JobConnectorError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
                if attempt == 1:
                    break

        raise JobConnectorError("Workday request failed") from last_error

    @staticmethod
    def _parse_identifier(provider_identifier: str) -> _WorkdayIdentifier:
        parts = provider_identifier.strip().split("/")
        if len(parts) != 3:
            raise JobConnectorError("Workday provider identifier is unsupported")
        hostname, tenant, site = parts
        hostname = hostname.casefold()
        if (
            not _WORKDAY_HOST_PATTERN.fullmatch(hostname)
            or not _PATH_IDENTIFIER_PATTERN.fullmatch(tenant)
            or not _PATH_IDENTIFIER_PATTERN.fullmatch(site)
        ):
            raise JobConnectorError("Workday provider identifier is unsupported")
        return _WorkdayIdentifier(hostname=hostname, tenant=tenant, site=site)

    @staticmethod
    def _parse_jobs_page(payload: bytes) -> _WorkdayJobsPage:
        try:
            page = _WorkdayJobsPage.model_validate(json.loads(payload))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as error:
            raise JobConnectorError("Workday returned an invalid jobs response") from error
        if page.total == 0 and page.job_postings:
            raise JobConnectorError("Workday returned an inconsistent jobs response")
        return page

    @staticmethod
    def _validate_external_path(external_path: str) -> str:
        path = external_path.strip()
        parts = urlsplit(path)
        segments = [unquote(segment) for segment in parts.path.split("/") if segment]
        if (
            parts.scheme
            or parts.netloc
            or parts.query
            or parts.fragment
            or not parts.path.startswith("/job/")
            or any(segment in {".", ".."} for segment in segments)
        ):
            raise JobConnectorError("Workday returned an unsupported job path")
        return parts.path

    @staticmethod
    def _jobs_url(identifier: _WorkdayIdentifier) -> str:
        tenant = quote(identifier.tenant, safe="")
        site = quote(identifier.site, safe="")
        return f"https://{identifier.hostname}/wday/cxs/{tenant}/{site}/jobs"

    @staticmethod
    def _detail_url(identifier: _WorkdayIdentifier, external_path: str) -> str:
        tenant = quote(identifier.tenant, safe="")
        site = quote(identifier.site, safe="")
        return (
            f"https://{identifier.hostname}/wday/cxs/{tenant}/{site}{external_path}"
        )

    def _map_job(
        self,
        identifier: _WorkdayIdentifier,
        external_path: str,
        info: _WorkdayJobInfo,
    ) -> ConnectorJob:
        source_job_id = info.id.strip()
        title = " ".join(info.title.split())
        if not source_job_id or not title:
            raise JobConnectorError("Workday returned invalid job fields")

        parser = _TextExtractor()
        parser.feed(info.job_description)
        parser.close()
        location = " ".join(info.location.split())
        site = quote(identifier.site, safe="")
        return ConnectorJob(
            source_type=self.source_type,
            source_job_id=source_job_id,
            title=title,
            location_text=location,
            description=parser.text(),
            job_url=f"https://{identifier.hostname}/{site}{external_path}",
        )
