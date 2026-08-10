import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.db import create_database_engine, create_session_factory, run_migrations
from app.main import create_app
from app.models.profiles import CandidateProfile
from app.providers.search.base import (
    SearchProviderError,
    SearchProviderNotConfigured,
    WebSearchProvider,
    WebSearchResult,
)
from app.providers.search.brave import BraveSearchProvider
from app.providers.search.factory import open_search_provider
from app.providers.search.tavily import TAVILY_SEARCH_URL, TavilySearchProvider
from app.schemas.profiles import CandidateProfileInput
from app.services.portal_discovery import PortalDiscoveryService
from app.services.profiles import ProfileService
from app.services.web_discovery import CompanyDiscoveryService


def run_search(
    handler,
    *,
    api_key: str | None = "tavily-test-key",
    results_per_query: int = 7,
) -> list[WebSearchResult]:
    async def scenario() -> list[WebSearchResult]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = TavilySearchProvider(
                client,
                api_key=api_key,
                results_per_query=results_per_query,
            )
            return await provider.search('site:linkedin.com/jobs/view "Mobile Engineer" "Pune"')

    return asyncio.run(scenario())


def test_tavily_provider_without_key_reports_unconfigured() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: None)) as client:
            provider = TavilySearchProvider(client, api_key="  ", results_per_query=10)
            assert provider.is_configured is False
            with pytest.raises(SearchProviderNotConfigured, match="Tavily Search is not configured"):
                await provider.search("mobile jobs")

    asyncio.run(scenario())


def test_tavily_request_retries_once_and_maps_bounded_results() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            request=request,
            json={
                "results": [
                    {
                        "title": f"Role {index}",
                        "url": f"https://example.test/jobs/{index}",
                        "content": f"Snippet {index}",
                        "score": 0.9,
                        "raw_content": "ignored",
                    }
                    for index in range(9)
                ],
                "answer": "ignored",
            },
        )

    results = run_search(handler, results_per_query=7)

    assert len(requests) == 2
    request = requests[-1]
    assert request.method == "POST"
    assert str(request.url) == TAVILY_SEARCH_URL
    assert request.headers["Authorization"] == "Bearer tavily-test-key"
    assert request.headers["Content-Type"].startswith("application/json")
    assert json.loads(request.content) == {
        "query": 'site:linkedin.com/jobs/view "Mobile Engineer" "Pune"',
        "search_depth": "basic",
        "topic": "general",
        "include_answer": False,
        "include_raw_content": False,
        "max_results": 7,
        "auto_parameters": False,
    }
    assert results == [
        WebSearchResult(
            title=f"Role {index}",
            url=f"https://example.test/jobs/{index}",
            description=f"Snippet {index}",
        )
        for index in range(7)
    ]


def test_tavily_empty_results_are_supported() -> None:
    results = run_search(lambda request: httpx.Response(200, request=request, json={"results": []}))

    assert results == []


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        json.dumps({"results": [{"url": "https://example.test/job", "content": "Missing title"}]}).encode(),
        json.dumps({"results": "not-a-list"}).encode(),
    ],
)
def test_tavily_malformed_responses_are_safe(payload: bytes) -> None:
    with pytest.raises(SearchProviderError, match="Tavily Search returned an invalid response"):
        run_search(lambda request: httpx.Response(200, request=request, content=payload))


@pytest.mark.parametrize("status_code", [400, 401, 429])
def test_tavily_client_errors_are_reported_without_retry(status_code: int) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, request=request)

    with pytest.raises(
        SearchProviderError,
        match=f"Tavily Search request failed with HTTP {status_code}",
    ):
        run_search(handler)

    assert len(requests) == 1


def test_tavily_timeout_uses_one_safe_retry_then_reports_provider_error() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(SearchProviderError, match="Tavily Search request failed"):
        run_search(handler)

    assert len(requests) == 2


def test_tavily_persistent_server_error_retries_once() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(502, request=request)

    with pytest.raises(SearchProviderError, match="Tavily Search request failed with HTTP 502"):
        run_search(handler)

    assert len(requests) == 2


def test_provider_factory_selects_tavily_and_preserves_brave() -> None:
    async def scenario() -> None:
        tavily_settings = Settings(
            _env_file=None,
            search_provider="tavily",
            tavily_api_key="tavily-key",
        )
        async with open_search_provider(tavily_settings) as provider:
            assert isinstance(provider, TavilySearchProvider)
            assert provider.is_configured is True

        brave_settings = Settings(
            _env_file=None,
            search_provider="brave",
            brave_search_api_key="brave-key",
        )
        async with open_search_provider(brave_settings) as provider:
            assert isinstance(provider, BraveSearchProvider)
            assert provider.is_configured is True

    asyncio.run(scenario())


def test_application_starts_with_tavily_selected_without_key(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'startup.db').as_posix()}",
        resume_storage_path=tmp_path / "resumes",
        search_provider="tavily",
        tavily_api_key=None,
        log_level="WARNING",
    )
    application = create_app(settings)

    async def scenario() -> httpx.Response:
        async with application.router.lifespan_context(application):
            assert application.state.settings.search_provider == "tavily"
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.get("/health")

    response = asyncio.run(scenario())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


class FakeTavilyProvider(WebSearchProvider):
    name = "tavily"

    @property
    def is_configured(self) -> bool:
        return True

    async def search(self, query: str) -> list[WebSearchResult]:
        if query.startswith("site:linkedin.com"):
            return [
                WebSearchResult(
                    title="Acme hiring Mobile Engineer in Pune | LinkedIn",
                    url="https://in.linkedin.com/jobs/view/mobile-engineer-4035123456",
                    description="Build mobile applications with Flutter and Dart.",
                )
            ]
        if query.startswith("site:naukri.com"):
            return [
                WebSearchResult(
                    title="Mobile Engineer Job at Beta Labs in Pune - Naukri.com",
                    url=(
                        "https://www.naukri.com/"
                        "job-listings-mobile-engineer-beta-labs-pune-12082025123456"
                    ),
                    description="Build customer-facing mobile products.",
                )
            ]
        if query.startswith("site:indeed.com"):
            return [
                WebSearchResult(
                    title="Mobile Engineer - Gamma Ltd - Pune | Indeed.com",
                    url="https://in.indeed.com/viewjob?jk=abc123xyz789",
                    description="Deliver reliable cross-platform features.",
                )
            ]
        return [
            WebSearchResult(
                title="Careers at Acme | Acme",
                url="https://acme.example/careers",
                description="Explore careers and open jobs at Acme.",
            )
        ]


def test_company_and_portal_discovery_remain_provider_neutral(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'consumers.db').as_posix()}",
        company_seed_path=tmp_path / "missing-seed.json",
        resume_storage_path=tmp_path / "resumes",
    )
    run_migrations(settings)
    engine = create_database_engine(settings.database_url)
    session = create_session_factory(engine)()
    try:
        profile = ProfileService(session).create_profile(
            CandidateProfileInput(
                name="Mobile",
                years_experience=5,
                target_roles=["Mobile Engineer"],
                role_synonyms=[],
                skills=["Flutter", "Dart"],
                preferred_locations=["Pune"],
                work_modes=[],
                excluded_keywords=[],
            )
        )
        provider = FakeTavilyProvider()

        company_result = asyncio.run(
            CompanyDiscoveryService(session, provider, max_queries=1, concurrency=1).discover()
        )
        portal_result = asyncio.run(
            PortalDiscoveryService(provider, max_queries=3, concurrency=1).discover([profile])
        )

        assert company_result.companies_created == 1
        assert company_result.known_companies[0].discovery_source == "web:tavily"
        assert portal_result.searches_succeeded == 3
        assert {candidate.portal for candidate in portal_result.candidates} == {
            "linkedin",
            "naukri",
            "indeed",
        }
    finally:
        session.close()
        engine.dispose()
