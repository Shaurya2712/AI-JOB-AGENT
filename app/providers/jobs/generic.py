import asyncio
from dataclasses import dataclass, field
from hashlib import sha256
from ipaddress import ip_address
import re
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
import httpx

from app.providers.jobs.base import (
    ConnectorJob,
    JobConnector,
    JobConnectorError,
    record_connector_retry,
)


MAX_GENERIC_JOB_LINKS = 50
MIN_GENERIC_DESCRIPTION_CHARS = 40
MAX_GENERIC_DESCRIPTION_CHARS = 2_000_000
_JOB_PATH_PATTERN = re.compile(
    r"/(?:job|jobs|position|positions|opening|openings|vacancy|vacancies)"
    r"(?:/|[-_])[^/?#]+",
    flags=re.IGNORECASE,
)
_JOB_QUERY_KEYS = frozenset(
    {"gh_jid", "job_id", "jobid", "posting_id", "postingid", "req_id", "reqid"}
)
_GENERIC_LINK_TEXT = frozenset(
    {
        "apply",
        "apply now",
        "careers",
        "details",
        "jobs",
        "learn more",
        "open positions",
        "open role",
        "view",
        "view job",
        "view role",
    }
)
_KNOWN_EXTERNAL_JOB_HOSTS = frozenset(
    {
        "boards.greenhouse.io",
        "boards.eu.greenhouse.io",
        "job-boards.greenhouse.io",
        "job-boards.eu.greenhouse.io",
        "jobs.ashbyhq.com",
        "jobs.lever.co",
        "jobs.eu.lever.co",
    }
)
_WORKDAY_JOB_HOST_PATTERN = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.wd[0-9]{1,4}\.myworkdayjobs\.com"
)
_PUBLIC_HOSTNAME_PATTERN = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
)


class UnsupportedCareerPageError(JobConnectorError):
    pass


class _ResponseLimitError(JobConnectorError):
    pass


@dataclass(frozen=True)
class _JobLink:
    url: str
    title: str


@dataclass
class _ResponseBudget:
    limit: int
    used: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def add(self, size: int) -> None:
        async with self.lock:
            if self.used + size > self.limit:
                self.used = self.limit
                raise _ResponseLimitError(
                    "Generic career-page responses exceed the configured limit"
                )
            self.used += size

    async def ensure_available(self) -> None:
        async with self.lock:
            if self.used >= self.limit:
                raise _ResponseLimitError(
                    "Generic career-page responses exceed the configured limit"
                )


class GenericCareerPageConnector(JobConnector):
    source_type = "custom"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_response_bytes: int,
        request_concurrency: int,
    ) -> None:
        if not 1 <= request_concurrency <= 5:
            raise ValueError("Generic page concurrency must be between one and five")
        self.client = client
        self.max_response_bytes = max_response_bytes
        self.request_semaphore = asyncio.Semaphore(request_concurrency)

    async def fetch_open_jobs(self, provider_identifier: str) -> list[ConnectorJob]:
        careers_url = self._public_url(provider_identifier)
        if careers_url is None:
            raise UnsupportedCareerPageError("Generic career-page URL is unsupported")

        budget = _ResponseBudget(self.max_response_bytes)
        index_payload = await self._request_html_with_one_safe_retry(careers_url, budget)
        links = self._extract_job_links(index_payload, careers_url)
        if not links:
            raise UnsupportedCareerPageError(
                "Generic career page has no reliable job-detail links"
            )

        outcomes = await asyncio.gather(
            *(self._fetch_job(link, budget) for link in links),
            return_exceptions=True,
        )
        jobs: list[ConnectorJob] = []
        for outcome in outcomes:
            if isinstance(outcome, _ResponseLimitError):
                raise outcome
            if isinstance(outcome, ConnectorJob):
                jobs.append(outcome)

        if not jobs:
            raise UnsupportedCareerPageError(
                "Generic career page did not yield reliable job details"
            )
        return jobs

    async def _fetch_job(
        self,
        link: _JobLink,
        budget: _ResponseBudget,
    ) -> ConnectorJob:
        payload = await self._request_html_with_one_safe_retry(link.url, budget)
        return self._parse_job_detail(payload, link)

    async def _request_html_with_one_safe_retry(
        self,
        url: str,
        budget: _ResponseBudget,
    ) -> bytes:
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                async with self.request_semaphore:
                    await budget.ensure_available()
                    async with self.client.stream(
                        "GET",
                        url,
                        headers={
                            "Accept": "text/html,application/xhtml+xml",
                        },
                    ) as response:
                        if response.status_code >= 500 and attempt == 0:
                            record_connector_retry()
                            continue
                        if response.is_error:
                            raise JobConnectorError(
                                "Generic career-page request failed with "
                                f"HTTP {response.status_code}"
                            )

                        content_type = response.headers.get("content-type", "").casefold()
                        if not (
                            "text/html" in content_type
                            or "application/xhtml+xml" in content_type
                        ):
                            raise UnsupportedCareerPageError(
                                "Generic career page returned a non-HTML response"
                            )

                        content_length = response.headers.get("content-length")
                        if (
                            content_length
                            and content_length.isdigit()
                            and int(content_length) > self.max_response_bytes
                        ):
                            raise _ResponseLimitError(
                                "Generic career-page response exceeds the configured limit"
                            )

                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            await budget.add(len(chunk))
                            body.extend(chunk)
                            if len(body) > self.max_response_bytes:
                                raise _ResponseLimitError(
                                    "Generic career-page response exceeds the configured limit"
                                )
                return bytes(body)
            except JobConnectorError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
                if attempt == 1:
                    break
                record_connector_retry()

        raise JobConnectorError("Generic career-page request failed") from last_error

    def _extract_job_links(self, payload: bytes, careers_url: str) -> list[_JobLink]:
        soup = BeautifulSoup(payload, "html.parser")
        careers_host = (urlsplit(careers_url).hostname or "").casefold()
        links: list[_JobLink] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            if not isinstance(anchor, Tag):
                continue
            title = self._clean_text(anchor.get_text(" ", strip=True))
            if not self._reliable_link_title(title):
                continue

            raw_href = anchor.get("href")
            if not isinstance(raw_href, str):
                continue
            candidate = self._public_url(urljoin(careers_url, raw_href))
            if candidate is None or not self._allowed_job_host(candidate, careers_host):
                continue
            if not self._looks_like_job_url(candidate) or candidate in seen:
                continue

            seen.add(candidate)
            links.append(_JobLink(url=candidate, title=title))
            if len(links) >= MAX_GENERIC_JOB_LINKS:
                break
        return links

    def _parse_job_detail(self, payload: bytes, link: _JobLink) -> ConnectorJob:
        soup = BeautifulSoup(payload, "html.parser")
        for unwanted in soup.select("script, style, noscript, template, svg"):
            unwanted.decompose()

        heading = soup.find("h1")
        heading_text = (
            self._clean_text(heading.get_text(" ", strip=True))
            if isinstance(heading, Tag)
            else ""
        )
        title = heading_text if self._reliable_link_title(heading_text) else link.title

        description_node = self._first_tag(
            soup,
            (
                "[itemprop='description']",
                "#job-description",
                ".job-description",
                "[id*='job-description']",
                "[class*='job-description']",
                "main",
                "article",
            ),
        )
        description = (
            self._block_text(description_node) if description_node is not None else ""
        )
        if (
            not self._reliable_link_title(title)
            or len(description) < MIN_GENERIC_DESCRIPTION_CHARS
            or len(description) > MAX_GENERIC_DESCRIPTION_CHARS
        ):
            raise UnsupportedCareerPageError("Generic job detail is unreliable")

        location_node = self._first_tag(
            soup,
            (
                "[itemprop='jobLocation']",
                ".job-location",
                "[id*='job-location']",
                "[class*='job-location']",
                ".location",
            ),
        )
        location = (
            self._clean_text(location_node.get_text(" ", strip=True))
            if location_node is not None
            else ""
        )
        if len(location) > 1000:
            location = ""

        return ConnectorJob(
            source_type=self.source_type,
            source_job_id=sha256(link.url.encode("utf-8")).hexdigest(),
            title=title,
            location_text=location,
            description=description,
            job_url=link.url,
        )

    @staticmethod
    def _first_tag(soup: BeautifulSoup, selectors: tuple[str, ...]) -> Tag | None:
        for selector in selectors:
            node = soup.select_one(selector)
            if isinstance(node, Tag):
                return node
        return None

    @classmethod
    def _block_text(cls, node: Tag) -> str:
        return "\n".join(
            cls._clean_text(line)
            for line in node.get_text("\n", strip=True).splitlines()
            if cls._clean_text(line)
        )

    @staticmethod
    def _clean_text(value: str) -> str:
        return " ".join(value.split())

    @staticmethod
    def _reliable_link_title(title: str) -> bool:
        return 3 <= len(title) <= 1000 and title.casefold() not in _GENERIC_LINK_TEXT

    @staticmethod
    def _looks_like_job_url(url: str) -> bool:
        parts = urlsplit(url)
        if _JOB_PATH_PATTERN.search(parts.path):
            return True
        try:
            query_keys = {
                key.casefold()
                for key, _value in parse_qsl(
                    parts.query,
                    keep_blank_values=False,
                    max_num_fields=30,
                )
            }
        except ValueError:
            return False
        return bool(query_keys & _JOB_QUERY_KEYS)

    @staticmethod
    def _allowed_job_host(url: str, careers_host: str) -> bool:
        hostname = (urlsplit(url).hostname or "").casefold()
        return (
            hostname == careers_host
            or hostname in _KNOWN_EXTERNAL_JOB_HOSTS
            or _WORKDAY_JOB_HOST_PATTERN.fullmatch(hostname) is not None
        )

    @staticmethod
    def _public_url(raw_url: str) -> str | None:
        try:
            candidate = raw_url.strip()
            if len(candidate) > 4000:
                return None
            parts = urlsplit(candidate)
            hostname = (parts.hostname or "").casefold()
            if (
                parts.scheme.casefold() not in {"http", "https"}
                or not hostname
                or parts.username
                or parts.password
                or parts.port not in {None, 80, 443}
                or hostname == "localhost"
                or hostname.endswith((".localhost", ".local", ".internal"))
            ):
                return None
            try:
                address = ip_address(hostname.strip("[]"))
            except ValueError:
                if _PUBLIC_HOSTNAME_PATTERN.fullmatch(hostname) is None:
                    return None
            else:
                if not address.is_global:
                    return None
            return urlunsplit(
                (parts.scheme.casefold(), parts.netloc.casefold(), parts.path or "/", parts.query, "")
            )
        except (TypeError, ValueError):
            return None
