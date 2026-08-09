import asyncio
from pathlib import Path

import httpx

from app.config import Settings
from app.db import create_database_engine, create_session_factory, run_migrations
from app.models.companies import Company
from app.models.profiles import CandidateProfile
from app.providers.search.base import SearchProviderError, WebSearchProvider, WebSearchResult
from app.providers.search.brave import BRAVE_WEB_SEARCH_URL, BraveSearchProvider
from app.schemas.profiles import CandidateProfileInput
from app.services.profiles import ProfileService
from app.services.search_queries import ProfileSearchQueryGenerator
from app.services.web_discovery import CompanyDiscoveryService


class FakeSearchProvider(WebSearchProvider):
    name = "fake"

    def __init__(self, results: list[WebSearchResult]) -> None:
        self.results = results
        self.queries: list[str] = []

    @property
    def is_configured(self) -> bool:
        return True

    async def search(self, query: str) -> list[WebSearchResult]:
        self.queries.append(query)
        return self.results


class FailingSearchProvider(WebSearchProvider):
    name = "failing"

    @property
    def is_configured(self) -> bool:
        return True

    async def search(self, query: str) -> list[WebSearchResult]:
        raise SearchProviderError("temporary provider outage")


def database_session(tmp_path: Path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'm05.db').as_posix()}",
        company_seed_path=tmp_path / "unused-seed.json",
        resume_storage_path=tmp_path / "resumes",
    )
    run_migrations(settings)
    engine = create_database_engine(settings.database_url)
    return engine, create_session_factory(engine)()


def profile_input(
    name: str,
    *,
    active: bool = True,
    roles: list[str] | None = None,
    synonyms: list[str] | None = None,
    locations: list[str] | None = None,
    work_modes: list[str] | None = None,
) -> CandidateProfileInput:
    return CandidateProfileInput(
        name=name,
        is_active=active,
        years_experience=4,
        target_roles=roles or ["Flutter Developer"],
        role_synonyms=synonyms or [],
        skills=[],
        preferred_locations=locations or [],
        work_modes=work_modes or [],
        excluded_keywords=[],
    )


def test_query_generation_uses_roles_synonyms_locations_and_bound() -> None:
    profile = CandidateProfile(
        id=7,
        name="Primary",
        is_active=True,
        target_roles_json=["Flutter Developer", "flutter developer"],
        role_synonyms_json=["Mobile Engineer"],
        skills_json=[],
        preferred_locations_json=["Pune"],
        work_modes_json=["Remote"],
        excluded_keywords_json=[],
    )

    queries = ProfileSearchQueryGenerator(max_queries=3).generate([profile])

    assert [(query.profile_id, query.text) for query in queries] == [
        (7, '"Flutter Developer" jobs careers "Pune"'),
        (7, '"Flutter Developer" jobs careers "Remote"'),
        (7, '"Mobile Engineer" jobs careers "Pune"'),
    ]


def test_discovery_persists_company_pages_without_duplicates(tmp_path: Path) -> None:
    engine, session = database_session(tmp_path)
    try:
        ProfileService(session).create_profile(
            profile_input(
                "Active",
                synonyms=["Mobile Engineer"],
                locations=["Pune"],
            )
        )
        ProfileService(session).create_profile(
            profile_input("Inactive", active=False, roles=["Java Developer"])
        )
        provider = FakeSearchProvider(
            [
                WebSearchResult(
                    title="Careers at Acme | Acme",
                    url="https://www.acme.example/careers/?utm_source=search",
                ),
                WebSearchResult(
                    title="Acme Careers",
                    url="https://acme.example/jobs",
                ),
                WebSearchResult(
                    title="Beta Careers",
                    url="https://beta.example/careers",
                ),
                WebSearchResult(
                    title="Acme jobs on LinkedIn",
                    url="https://www.linkedin.com/jobs/acme",
                ),
            ]
        )
        service = CompanyDiscoveryService(session, provider, max_queries=10, concurrency=2)

        first = asyncio.run(service.discover())
        second = asyncio.run(service.discover())

        assert first.queries_generated == 2
        assert first.searches_succeeded == 2
        assert first.searches_failed == 0
        assert first.companies_created == 2
        assert len(first.known_companies) == 2
        assert second.companies_created == 0
        assert second.companies_existing == 2
        assert len(second.known_companies) == 2
        assert all("Java Developer" not in query for query in provider.queries)

        companies = sorted(second.known_companies, key=lambda company: company.name)
        assert [company.name for company in companies] == ["Acme", "Beta"]
        assert companies[0].careers_url == "https://www.acme.example/careers"
        assert all(company.discovery_source == "web:fake" for company in companies)
        assert all(company.provider_type is None for company in companies)
    finally:
        session.close()
        engine.dispose()


def test_discovery_failure_returns_known_registry_for_scanning(tmp_path: Path) -> None:
    engine, session = database_session(tmp_path)
    try:
        ProfileService(session).create_profile(profile_input("Active"))
        session.add(
            Company(
                name="Known Co",
                website_url="https://known.example",
                careers_url="https://known.example/careers",
                discovery_source="seed",
                is_active=True,
                provider_supported=True,
                total_jobs_seen=0,
            )
        )
        session.commit()
        service = CompanyDiscoveryService(
            session,
            FailingSearchProvider(),
            max_queries=10,
            concurrency=2,
        )

        result = asyncio.run(service.discover())
        downstream_scan_input = [company.name for company in result.known_companies]

        assert result.searches_succeeded == 0
        assert result.searches_failed == 1
        assert result.companies_created == 0
        assert result.errors == ("failing: temporary provider outage",)
        assert downstream_scan_input == ["Known Co"]
    finally:
        session.close()
        engine.dispose()


def test_brave_adapter_uses_documented_request_and_parses_results() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            request=request,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Acme Careers",
                            "url": "https://acme.example/careers",
                            "description": "Open jobs at Acme",
                        }
                    ]
                }
            },
        )

    async def scenario() -> list[WebSearchResult]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = BraveSearchProvider(
                client,
                api_key="test-key",
                country="IN",
                language="en",
                results_per_query=10,
            )
            return await provider.search('"Flutter Developer" jobs careers "Pune"')

    results = asyncio.run(scenario())

    assert len(requests) == 2
    request = requests[-1]
    assert str(request.url).startswith(BRAVE_WEB_SEARCH_URL)
    assert request.headers["X-Subscription-Token"] == "test-key"
    assert request.url.params["country"] == "IN"
    assert request.url.params["search_lang"] == "en"
    assert request.url.params["count"] == "10"
    assert results == [
        WebSearchResult(
            title="Acme Careers",
            url="https://acme.example/careers",
            description="Open jobs at Acme",
        )
    ]
