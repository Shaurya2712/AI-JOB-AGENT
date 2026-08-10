import asyncio
from dataclasses import dataclass
from html import unescape
import re
from typing import Literal
import unicodedata
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit

from app.models.profiles import CandidateProfile
from app.providers.search.base import SearchProviderError, WebSearchProvider, WebSearchResult
from app.services.job_normalization import JobNormalizationError, normalize_job_url
from app.services.search_queries import (
    PORTAL_NAMES,
    PortalName,
    PortalSearchQuery,
    PortalSearchQueryGenerator,
)


_MAX_TITLE_CHARS = 1_000
_MAX_COMPANY_CHARS = 160
_MAX_LOCATION_CHARS = 1_000
_MAX_SNIPPET_CHARS = 10_000
_GENERIC_TITLES = {
    "find jobs",
    "job search",
    "jobs",
    "linkedin jobs",
    "naukri jobs",
    "search jobs",
}
_PORTAL_SUFFIXES = {
    "linkedin": re.compile(r"\s*(?:\||[-–—])\s*linkedin(?:\.com)?\s*$", re.IGNORECASE),
    "naukri": re.compile(r"\s*(?:\||[-–—])\s*naukri(?:\.com)?\s*$", re.IGNORECASE),
    "indeed": re.compile(r"\s*(?:\||[-–—])\s*indeed(?:\.com)?\s*$", re.IGNORECASE),
}


@dataclass(frozen=True)
class PortalJobCandidate:
    portal: PortalName
    source_job_id: str
    original_url: str
    title: str
    company_name: str
    location_text: str
    snippet: str
    data_completeness: Literal["partial"] = "partial"


@dataclass(frozen=True)
class PortalSourceDiscoveryResult:
    portal: PortalName
    queries_generated: int
    searches_succeeded: int
    searches_failed: int
    candidates: tuple[PortalJobCandidate, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class PortalDiscoveryRunResult:
    queries_generated: int
    searches_succeeded: int
    searches_failed: int
    candidates: tuple[PortalJobCandidate, ...]
    source_results: tuple[PortalSourceDiscoveryResult, ...]
    errors: tuple[str, ...]


class PortalJobResultRecognizer:
    def recognize(
        self,
        portal: PortalName,
        result: WebSearchResult,
    ) -> PortalJobCandidate | None:
        identity = self._job_identity(portal, result.url)
        if identity is None:
            return None
        source_job_id, original_url = identity

        metadata = self._title_metadata(portal, result.title)
        if metadata is None:
            return None
        title, company_name, location = metadata
        snippet = _clean_text(result.description)[:_MAX_SNIPPET_CHARS]
        return PortalJobCandidate(
            portal=portal,
            source_job_id=source_job_id,
            original_url=original_url,
            title=title,
            company_name=company_name,
            location_text=location,
            snippet=snippet,
        )

    @classmethod
    def _job_identity(
        cls,
        portal: PortalName,
        raw_url: str,
    ) -> tuple[str, str] | None:
        try:
            normalized_url = normalize_job_url(raw_url)
            parts = urlsplit(normalized_url)
        except (JobNormalizationError, TypeError, ValueError):
            return None

        hostname = (parts.hostname or "").casefold()
        if portal == "linkedin":
            if not _host_matches(hostname, "linkedin.com"):
                return None
            match = re.fullmatch(
                r"/jobs/view/(?:[^/]+-)?(\d{5,20})/?",
                parts.path,
                flags=re.IGNORECASE,
            )
            if match is None:
                return None
            return match.group(1), _url_without_query(parts)

        if portal == "naukri":
            if not _host_matches(hostname, "naukri.com"):
                return None
            match = re.fullmatch(
                r"/job-listings-(?:[^/]+-)?(\d{5,30})/?",
                parts.path,
                flags=re.IGNORECASE,
            )
            if match is None:
                return None
            return match.group(1), _url_without_query(parts)

        if not _host_matches(hostname, "indeed.com") or parts.path.casefold() != "/viewjob":
            return None
        try:
            identifiers = [
                value.strip()
                for key, value in parse_qsl(
                    parts.query,
                    keep_blank_values=True,
                    max_num_fields=50,
                )
                if key.casefold() == "jk"
            ]
        except ValueError:
            return None
        if len(identifiers) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{6,100}", identifiers[0]):
            return None
        source_job_id = identifiers[0]
        original_url = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode({"jk": source_job_id}), "")
        )
        return source_job_id, original_url

    @classmethod
    def _title_metadata(
        cls,
        portal: PortalName,
        raw_title: str,
    ) -> tuple[str, str, str] | None:
        title_text = _clean_text(raw_title)
        title_text = _PORTAL_SUFFIXES[portal].sub("", title_text).strip(" -|–—")
        if not title_text:
            return None

        parsed = cls._parse_portal_title(portal, title_text)
        if parsed is None:
            return None
        title, company_name, location = (_clean_text(value) for value in parsed)
        if (
            not title
            or title.casefold() in _GENERIC_TITLES
            or not company_name
            or len(title) > _MAX_TITLE_CHARS
            or len(company_name) > _MAX_COMPANY_CHARS
            or len(location) > _MAX_LOCATION_CHARS
        ):
            return None
        return title, company_name, location

    @staticmethod
    def _parse_portal_title(
        portal: PortalName,
        title_text: str,
    ) -> tuple[str, str, str] | None:
        patterns: tuple[re.Pattern[str], ...]
        if portal == "linkedin":
            patterns = (
                re.compile(
                    r"^(?P<company>.+?)\s+hiring\s+(?P<title>.+?)"
                    r"(?:\s+in\s+(?P<location>.+))?$",
                    re.IGNORECASE,
                ),
                re.compile(
                    r"^(?P<title>.+?)\s+at\s+(?P<company>.+?)"
                    r"(?:\s+in\s+(?P<location>.+))?$",
                    re.IGNORECASE,
                ),
            )
        elif portal == "naukri":
            patterns = (
                re.compile(
                    r"^(?P<title>.+?)\s+job\s+in\s+(?P<company>.+?)"
                    r"(?:\s+at\s+(?P<location>.+))?$",
                    re.IGNORECASE,
                ),
                re.compile(
                    r"^(?P<title>.+?)\s+job\s+at\s+(?P<company>.+?)"
                    r"(?:\s+in\s+(?P<location>.+))?$",
                    re.IGNORECASE,
                ),
            )
        else:
            patterns = (
                re.compile(
                    r"^(?P<title>.+?)\s+at\s+(?P<company>.+?)"
                    r"(?:\s+in\s+(?P<location>.+))?$",
                    re.IGNORECASE,
                ),
            )

        for pattern in patterns:
            match = pattern.fullmatch(title_text)
            if match is not None:
                return (
                    match.group("title"),
                    match.group("company"),
                    match.groupdict().get("location") or "",
                )

        parts = [
            part.strip()
            for part in re.split(r"\s+(?:\||[-–—])\s+", title_text)
            if part.strip()
        ]
        minimum_parts = 3 if portal == "indeed" else 2
        if len(parts) < minimum_parts:
            return None
        if len(parts) == 2:
            return parts[0], parts[1], ""
        return " - ".join(parts[:-2]), parts[-2], parts[-1]


class PortalDiscoveryService:
    def __init__(
        self,
        provider: WebSearchProvider,
        *,
        max_queries: int,
        concurrency: int,
    ) -> None:
        self.provider = provider
        self.query_generator = PortalSearchQueryGenerator(max_queries=max_queries)
        self.recognizer = PortalJobResultRecognizer()
        self.concurrency = concurrency

    async def discover(self, profiles: list[CandidateProfile]) -> PortalDiscoveryRunResult:
        queries = self.query_generator.generate(profiles)
        if not queries:
            return self._result(queries, (), {})
        if not self.provider.is_configured:
            errors = {
                portal: (f"{self.provider.name} search is not configured",)
                for portal in PORTAL_NAMES
                if any(query.portal == portal for query in queries)
            }
            return self._result(queries, (), errors)

        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_search(
            query: PortalSearchQuery,
        ) -> tuple[PortalSearchQuery, list[WebSearchResult] | None, str | None]:
            async with semaphore:
                try:
                    return query, await self.provider.search(query.text), None
                except SearchProviderError as error:
                    return query, None, f"{self.provider.name}: {error}"
                except Exception:
                    return query, None, f"{self.provider.name}: unexpected search failure"

        outcomes = tuple(await asyncio.gather(*(run_search(query) for query in queries)))
        return self._result(queries, outcomes, {})

    def _result(
        self,
        queries: list[PortalSearchQuery],
        outcomes: tuple[
            tuple[PortalSearchQuery, list[WebSearchResult] | None, str | None],
            ...,
        ],
        configuration_errors: dict[PortalName, tuple[str, ...]],
    ) -> PortalDiscoveryRunResult:
        source_results: list[PortalSourceDiscoveryResult] = []
        all_candidates: list[PortalJobCandidate] = []
        all_errors: list[str] = []

        for portal in PORTAL_NAMES:
            portal_queries = [query for query in queries if query.portal == portal]
            portal_outcomes = [outcome for outcome in outcomes if outcome[0].portal == portal]
            candidates: dict[str, PortalJobCandidate] = {}
            errors = list(configuration_errors.get(portal, ()))
            searches_succeeded = 0
            searches_failed = 0

            for _query, results, error in portal_outcomes:
                if error is not None:
                    searches_failed += 1
                    errors.append(error)
                    continue
                searches_succeeded += 1
                for result in results or ():
                    candidate = self.recognizer.recognize(portal, result)
                    if candidate is not None:
                        candidates.setdefault(candidate.source_job_id, candidate)

            bounded_errors = tuple(errors[:20])
            portal_candidates = tuple(candidates.values())
            source_results.append(
                PortalSourceDiscoveryResult(
                    portal=portal,
                    queries_generated=len(portal_queries),
                    searches_succeeded=searches_succeeded,
                    searches_failed=searches_failed,
                    candidates=portal_candidates,
                    errors=bounded_errors,
                )
            )
            all_candidates.extend(portal_candidates)
            all_errors.extend(f"{portal}: {error}" for error in bounded_errors)

        return PortalDiscoveryRunResult(
            queries_generated=len(queries),
            searches_succeeded=sum(result.searches_succeeded for result in source_results),
            searches_failed=sum(result.searches_failed for result in source_results),
            candidates=tuple(all_candidates),
            source_results=tuple(source_results),
            errors=tuple(all_errors[:20]),
        )


def _host_matches(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def _url_without_query(parts: SplitResult) -> str:
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _clean_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", unescape(value))
    without_tags = re.sub(r"<[^>]*>", " ", normalized)
    return " ".join(without_tags.split())
