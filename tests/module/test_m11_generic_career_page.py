import asyncio
from hashlib import sha256
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.db import create_database_engine, create_session_factory, run_migrations
from app.models.companies import Company
from app.providers.jobs.base import ConnectorJob, JobConnector, JobConnectorError
from app.providers.jobs.generic import (
    MAX_GENERIC_JOB_LINKS,
    GenericCareerPageConnector,
    UnsupportedCareerPageError,
)
from app.services.job_collection import JobCollectionService


class FixtureGenericConnector(JobConnector):
    source_type = "custom"

    def __init__(self) -> None:
        self.identifiers: list[str] = []

    async def fetch_open_jobs(self, provider_identifier: str) -> list[ConnectorJob]:
        self.identifiers.append(provider_identifier)
        if "broken" in provider_identifier:
            raise UnsupportedCareerPageError("Fixture career page is unsupported")
        return [
            ConnectorJob(
                source_type="custom",
                source_job_id="generic-101",
                title="Backend Engineer",
                location_text="Remote",
                description="Build reliable backend systems.",
                job_url="https://working.example/jobs/backend-engineer",
            )
        ]


def test_generic_connector_extracts_reliable_job_links_and_details() -> None:
    requests: list[httpx.Request] = []
    detail_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal detail_attempts
        requests.append(request)
        if request.url.path == "/careers":
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/html; charset=utf-8"},
                text="""
                    <html><body>
                      <a href="/about">About us</a>
                      <a href="/jobs/backend-engineer#top">Backend Engineer</a>
                      <a href="/jobs/backend-engineer">Backend Engineer</a>
                      <a href="/positions/designer">Product Designer</a>
                      <a href="http://127.0.0.1/jobs/private">Private Role</a>
                      <a href="https://untrusted.example/jobs/1">External Role</a>
                      <script>fetch('/jobs/hidden')</script>
                    </body></html>
                """,
            )
        if request.url.path == "/jobs/backend-engineer":
            detail_attempts += 1
            if detail_attempts == 1:
                return httpx.Response(503, request=request)
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/html"},
                text="""
                    <html><body><main>
                      <h1>  Senior   Backend Engineer </h1>
                      <div class="job-location"> Remote — India </div>
                      <section class="job-description">
                        Build reliable services for customers worldwide.
                        <p>Own delivery and improve system quality.</p>
                      </section>
                    </main></body></html>
                """,
            )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            text="<html><body><h1>Product Designer</h1><main>Too short.</main></body></html>",
        )

    async def scenario() -> list[ConnectorJob]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = GenericCareerPageConnector(
                client,
                max_response_bytes=1024 * 1024,
                request_concurrency=2,
            )
            return await connector.fetch_open_jobs("https://careers.example/careers")

    jobs = asyncio.run(scenario())
    job_url = "https://careers.example/jobs/backend-engineer"

    assert len(requests) == 4
    assert all(request.method == "GET" for request in requests)
    assert all(request.headers["Accept"] == "text/html,application/xhtml+xml" for request in requests)
    assert all("Authorization" not in request.headers for request in requests)
    assert jobs == [
        ConnectorJob(
            source_type="custom",
            source_job_id=sha256(job_url.encode("utf-8")).hexdigest(),
            title="Senior Backend Engineer",
            location_text="Remote — India",
            description=(
                "Build reliable services for customers worldwide.\n"
                "Own delivery and improve system quality."
            ),
            job_url=job_url,
        )
    ]


def test_generic_connector_enforces_url_type_size_and_reliability_boundaries() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/json":
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "application/json"},
                json={"jobs": []},
            )
        if request.url.path == "/large":
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/html", "content-length": "10000"},
                text="<html></html>",
            )
        if request.url.path == "/budget":
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/html"},
                text="".join(
                    f'<a href="/jobs/budget-{index}">Budget Role {index}</a>'
                    for index in range(3)
                ),
            )
        if request.url.path.startswith("/jobs/budget-"):
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/html"},
                text=(
                    "<html><body><main><h1>Budget Role</h1><p>"
                    + ("A" * 300)
                    + "</p></main></body></html>"
                ),
            )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            text="<html><body><a href='/about'>About</a></body></html>",
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = GenericCareerPageConnector(
                client,
                max_response_bytes=1000,
                request_concurrency=1,
            )
            with pytest.raises(UnsupportedCareerPageError, match="URL is unsupported"):
                await connector.fetch_open_jobs("http://127.0.0.1/careers")
            with pytest.raises(UnsupportedCareerPageError, match="non-HTML"):
                await connector.fetch_open_jobs("https://careers.example/json")
            with pytest.raises(UnsupportedCareerPageError, match="no reliable"):
                await connector.fetch_open_jobs("https://careers.example/empty")
            with pytest.raises(JobConnectorError, match="exceeds the configured limit"):
                await connector.fetch_open_jobs("https://careers.example/large")

            budget_connector = GenericCareerPageConnector(
                client,
                max_response_bytes=700,
                request_concurrency=1,
            )
            with pytest.raises(JobConnectorError, match="exceed the configured limit"):
                await budget_connector.fetch_open_jobs("https://careers.example/budget")

    asyncio.run(scenario())
    assert [request.url.path for request in requests] == [
        "/json",
        "/empty",
        "/large",
        "/budget",
        "/jobs/budget-0",
        "/jobs/budget-1",
    ]


def test_generic_connector_caps_links_and_never_crawls_detail_page_links() -> None:
    requests: list[httpx.Request] = []
    index_links = "".join(
        f'<a href="/jobs/role-{index}">Role {index}</a>'
        for index in range(MAX_GENERIC_JOB_LINKS + 5)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/careers":
            html = f"<html><body>{index_links}</body></html>"
        else:
            html = """
                <html><body><main>
                  <h1>Software Engineer</h1>
                  <p>This is a sufficiently detailed public job description for testing.</p>
                  <a href="/jobs/should-not-be-crawled">Nested role</a>
                </main></body></html>
            """
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            text=html,
        )

    async def scenario() -> list[ConnectorJob]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = GenericCareerPageConnector(
                client,
                max_response_bytes=1024 * 1024,
                request_concurrency=3,
            )
            return await connector.fetch_open_jobs("https://careers.example/careers")

    jobs = asyncio.run(scenario())

    assert len(jobs) == MAX_GENERIC_JOB_LINKS
    assert len(requests) == MAX_GENERIC_JOB_LINKS + 1
    assert all(request.url.path != "/jobs/should-not-be-crawled" for request in requests)


def test_generic_source_selection_uses_career_urls_and_isolates_failures(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "m11.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        company_seed_path=tmp_path / "unused-seed.json",
        resume_storage_path=tmp_path / "resumes",
    )
    run_migrations(settings)
    engine = create_database_engine(settings.database_url)
    session = create_session_factory(engine)()
    connector = FixtureGenericConnector()

    try:
        session.add_all(
            [
                Company(
                    name="Broken Custom",
                    website_url="https://broken.example",
                    careers_url="https://broken.example/careers",
                    provider_type="custom",
                    provider_identifier="broken.example",
                    discovery_source="web:fake",
                    is_active=True,
                    provider_supported=False,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Working Custom",
                    website_url="https://working.example",
                    careers_url="https://working.example/careers",
                    provider_type="custom",
                    provider_identifier="working.example",
                    discovery_source="web:fake",
                    is_active=True,
                    provider_supported=False,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Inactive Custom",
                    website_url="https://inactive.example",
                    careers_url="https://inactive.example/careers",
                    provider_type="custom",
                    provider_identifier="inactive.example",
                    discovery_source="web:fake",
                    is_active=False,
                    provider_supported=False,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Greenhouse Co",
                    website_url="https://greenhouse.example",
                    careers_url="https://boards.greenhouse.io/acme",
                    provider_type="greenhouse",
                    provider_identifier="acme",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                ),
            ]
        )
        session.commit()

        result = asyncio.run(JobCollectionService(session, concurrency=2).collect(connector))

        assert connector.identifiers == [
            "https://broken.example/careers",
            "https://working.example/careers",
        ]
        assert result.sources_checked == 2
        assert result.sources_succeeded == 1
        assert result.sources_failed == 1
        assert result.jobs_fetched == 1
        assert result.source_results[0].status == "failed"
        assert result.source_results[0].error_message == (
            "Fixture career page is unsupported"
        )
        assert result.source_results[1].status == "success"
        assert result.source_results[1].jobs[0].source_type == "custom"
    finally:
        session.close()
        engine.dispose()
