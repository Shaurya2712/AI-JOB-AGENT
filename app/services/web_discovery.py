import asyncio
from dataclasses import dataclass
from html import unescape
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.models.companies import Company
from app.providers.search.base import SearchProviderError, WebSearchProvider, WebSearchResult
from app.repositories.companies import CompanyRepository
from app.repositories.profiles import ProfileRepository
from app.schemas.companies import normalize_company_url
from app.services.search_queries import ProfileSearchQuery, ProfileSearchQueryGenerator


_CAREER_TERMS = ("career", "jobs", "join us", "open positions", "openings", "vacancies")
_BLOCKED_HOSTS = (
    "facebook.com",
    "glassdoor.com",
    "google.com",
    "indeed.com",
    "linkedin.com",
    "monster.com",
    "naukri.com",
    "wellfound.com",
)
_TRACKING_PARAMETERS = {"gh_src", "ref", "referrer", "source"}
_COMMON_SECOND_LEVEL_SUFFIXES = {"co.in", "co.uk", "com.au", "com.br", "com.sg"}


@dataclass(frozen=True)
class CompanyDiscoveryCandidate:
    name: str
    website_url: str
    careers_url: str
    identity_key: str


@dataclass(frozen=True)
class DiscoveryRunResult:
    queries_generated: int
    searches_succeeded: int
    searches_failed: int
    companies_created: int
    companies_existing: int
    known_companies: tuple[Company, ...]
    errors: tuple[str, ...]


class SearchDiscoveryParser:
    def parse(self, result: WebSearchResult) -> CompanyDiscoveryCandidate | None:
        careers_url = self._normalize_result_url(result.url)
        if careers_url is None:
            return None

        parts = urlsplit(careers_url)
        hostname = (parts.hostname or "").casefold()
        if self._host_is_blocked(hostname):
            return None

        signal_text = f"{parts.path} {result.title} {result.description}".casefold()
        if not any(term in signal_text for term in _CAREER_TERMS):
            return None

        website_url = self._website_identity_url(careers_url)
        identity_key = self.identity_key(careers_url)
        name = self._company_name(result.title, hostname)
        if not name:
            return None
        return CompanyDiscoveryCandidate(
            name=name,
            website_url=website_url,
            careers_url=careers_url,
            identity_key=identity_key,
        )

    @staticmethod
    def _normalize_result_url(raw_url: str) -> str | None:
        try:
            parts = urlsplit(raw_url.strip())
            parameters = [
                (key, value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True, max_num_fields=50)
                if not key.casefold().startswith("utm_")
                and key.casefold() not in _TRACKING_PARAMETERS
            ]
            cleaned = urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urlencode(parameters), "")
            )
            return normalize_company_url(cleaned)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _host_is_blocked(hostname: str) -> bool:
        host = hostname.removeprefix("www.")
        return any(host == blocked or host.endswith(f".{blocked}") for blocked in _BLOCKED_HOSTS)

    @classmethod
    def _website_identity_url(cls, careers_url: str) -> str:
        parts = urlsplit(careers_url)
        path_segments = [segment for segment in parts.path.split("/") if segment]
        first_label = (parts.hostname or "").split(".")[0].casefold()
        path = f"/{path_segments[0]}" if first_label in {"boards", "jobs"} and path_segments else ""
        return normalize_company_url(urlunsplit((parts.scheme, parts.netloc, path, "", "")))

    @classmethod
    def identity_key(cls, url: str) -> str:
        parts = urlsplit(url)
        hostname = (parts.hostname or "").casefold().removeprefix("www.")
        path_segments = [segment.casefold() for segment in parts.path.split("/") if segment]
        first_label = hostname.split(".")[0] if hostname else ""
        if first_label in {"boards", "jobs"} and path_segments:
            return f"{hostname}/{path_segments[0]}"

        labels = hostname.split(".")
        if len(labels) >= 3 and ".".join(labels[-2:]) in _COMMON_SECOND_LEVEL_SUFFIXES:
            return ".".join(labels[-3:])
        return ".".join(labels[-2:]) if len(labels) >= 2 else hostname

    @staticmethod
    def _company_name(raw_title: str, hostname: str) -> str:
        title = " ".join(unescape(raw_title).split())
        title = re.sub(r"<[^>]+>", "", title).strip()

        for pattern in (
            r"^(?:careers|jobs|open positions)\s+(?:at\s+)?([^|–—]+)",
            r"^(.+?)\s+(?:careers|jobs)(?:\s*[|–—].*)?$",
        ):
            match = re.search(pattern, title, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1).strip(" -|–—")
                if candidate:
                    return candidate[:160]

        labels = hostname.removeprefix("www.").split(".")
        label = next(
            (item for item in labels if item not in {"boards", "career", "careers", "jobs"}),
            "",
        )
        return label.replace("-", " ").title()[:160]


class CompanyDiscoveryService:
    def __init__(
        self,
        session: Session,
        provider: WebSearchProvider,
        *,
        max_queries: int,
        concurrency: int,
    ) -> None:
        self.session = session
        self.provider = provider
        self.company_repository = CompanyRepository(session)
        self.profile_repository = ProfileRepository(session)
        self.query_generator = ProfileSearchQueryGenerator(max_queries=max_queries)
        self.parser = SearchDiscoveryParser()
        self.concurrency = concurrency

    async def discover(self) -> DiscoveryRunResult:
        known_before = self.company_repository.list_companies()
        profiles = self.profile_repository.list_active_profiles()
        queries = self.query_generator.generate(profiles)

        if not queries:
            return self._result(queries, 0, 0, 0, 0, known_before, ())
        if not self.provider.is_configured:
            return self._result(
                queries,
                0,
                0,
                0,
                0,
                known_before,
                (f"{self.provider.name} search is not configured",),
            )

        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_search(
            query: ProfileSearchQuery,
        ) -> tuple[list[WebSearchResult] | None, str | None]:
            async with semaphore:
                try:
                    return await self.provider.search(query.text), None
                except SearchProviderError as error:
                    return None, f"{self.provider.name}: {error}"
                except Exception:
                    return None, f"{self.provider.name}: unexpected search failure"

        outcomes = await asyncio.gather(*(run_search(query) for query in queries))
        successful_results = [results for results, error in outcomes if error is None and results is not None]
        errors = tuple(error for _results, error in outcomes if error is not None)

        candidates: dict[str, CompanyDiscoveryCandidate] = {}
        for results in successful_results:
            for search_result in results:
                candidate = self.parser.parse(search_result)
                if candidate is not None:
                    candidates.setdefault(candidate.identity_key, candidate)

        created, existing = self._persist_candidates(list(candidates.values()))
        known_after = self.company_repository.list_companies()
        return self._result(
            queries,
            len(successful_results),
            len(errors),
            created,
            existing,
            known_after,
            errors[:20],
        )

    def _persist_candidates(self, candidates: list[CompanyDiscoveryCandidate]) -> tuple[int, int]:
        companies = self.company_repository.list_companies()
        by_identity: dict[str, Company] = {}
        by_careers_url: dict[str, Company] = {}
        for company in companies:
            by_identity[self.parser.identity_key(company.website_url)] = company
            if company.careers_url:
                by_identity[self.parser.identity_key(company.careers_url)] = company
                by_careers_url[company.careers_url] = company

        created = 0
        existing = 0
        try:
            for candidate in candidates:
                company = by_careers_url.get(candidate.careers_url) or by_identity.get(
                    candidate.identity_key
                )
                if company is not None:
                    existing += 1
                    if company.careers_url is None:
                        company.careers_url = candidate.careers_url
                    by_careers_url[candidate.careers_url] = company
                    continue

                company = Company(
                    name=candidate.name,
                    website_url=candidate.website_url,
                    careers_url=candidate.careers_url,
                    provider_type=None,
                    provider_identifier=None,
                    discovery_source=f"web:{self.provider.name}",
                    is_active=True,
                    provider_supported=False,
                    total_jobs_seen=0,
                )
                self.company_repository.add(company)
                by_identity[candidate.identity_key] = company
                by_careers_url[candidate.careers_url] = company
                created += 1
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return created, existing

    @staticmethod
    def _result(
        queries: list[ProfileSearchQuery],
        searches_succeeded: int,
        searches_failed: int,
        companies_created: int,
        companies_existing: int,
        known_companies: list[Company],
        errors: tuple[str, ...],
    ) -> DiscoveryRunResult:
        return DiscoveryRunResult(
            queries_generated=len(queries),
            searches_succeeded=searches_succeeded,
            searches_failed=searches_failed,
            companies_created=companies_created,
            companies_existing=companies_existing,
            known_companies=tuple(known_companies),
            errors=errors,
        )
