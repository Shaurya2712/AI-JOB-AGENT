import asyncio
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.db import create_database_engine, create_session_factory, run_migrations
from app.models.companies import Company
from app.providers.jobs.base import ConnectorJob, JobConnector, JobConnectorError
from app.providers.jobs.lever import (
    LEVER_EU_POSTINGS_API,
    LEVER_GLOBAL_POSTINGS_API,
    LEVER_PAGE_SIZE,
    LeverConnector,
)
from app.services.job_collection import JobCollectionService


class FixtureLeverConnector(JobConnector):
    source_type = "lever"

    async def fetch_open_jobs(self, provider_identifier: str) -> list[ConnectorJob]:
        if provider_identifier == "broken-site":
            raise JobConnectorError("Fixture site is unavailable")
        return [
            ConnectorJob(
                source_type="lever",
                source_job_id="lever-101",
                title="React Developer",
                location_text="Remote",
                description="Build web products.",
                job_url="https://jobs.lever.co/working-site/lever-101",
            )
        ]


def lever_posting(index: int, *, site: str = "acme") -> dict[str, object]:
    return {
        "id": f"posting-{index}",
        "text": f"Engineer {index}",
        "categories": {"location": "Pune, India"},
        "descriptionPlain": f"Build product {index}.",
        "hostedUrl": f"https://jobs.lever.co/{site}/posting-{index}",
    }


def test_lever_connector_fetches_and_maps_published_jobs() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            request=request,
            json=[
                {
                    "id": "posting-1",
                    "text": "  React   Native Developer ",
                    "categories": {"location": " Bengaluru, India "},
                    "descriptionPlain": "Build mobile products.\n\n Ship quality software.",
                    "hostedUrl": "https://jobs.lever.co/acme/posting-1",
                },
                {
                    "id": "posting-2",
                    "text": "Frontend Engineer",
                    "categories": None,
                    "descriptionPlain": "Build the web platform.",
                    "hostedUrl": "https://jobs.lever.co/acme/posting-2",
                },
            ],
        )

    async def scenario() -> list[ConnectorJob]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = LeverConnector(client, max_response_bytes=1024 * 1024)
            return await connector.fetch_open_jobs("acme")

    jobs = asyncio.run(scenario())

    assert len(requests) == 2
    request = requests[-1]
    assert str(request.url).startswith(f"{LEVER_GLOBAL_POSTINGS_API}/acme")
    assert request.url.params["mode"] == "json"
    assert request.url.params["skip"] == "0"
    assert request.url.params["limit"] == str(LEVER_PAGE_SIZE)
    assert request.headers["Accept"] == "application/json"
    assert "Authorization" not in request.headers
    assert jobs == [
        ConnectorJob(
            source_type="lever",
            source_job_id="posting-1",
            title="React Native Developer",
            location_text="Bengaluru, India",
            description="Build mobile products.\nShip quality software.",
            job_url="https://jobs.lever.co/acme/posting-1",
        ),
        ConnectorJob(
            source_type="lever",
            source_job_id="posting-2",
            title="Frontend Engineer",
            location_text="",
            description="Build the web platform.",
            job_url="https://jobs.lever.co/acme/posting-2",
        ),
    ]


def test_lever_connector_pages_and_falls_back_to_the_eu_api() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "api.lever.co":
            return httpx.Response(404, request=request)

        skip = int(request.url.params["skip"])
        if skip == 0:
            payload = [lever_posting(index, site="acme-eu") for index in range(LEVER_PAGE_SIZE)]
        else:
            payload = [lever_posting(LEVER_PAGE_SIZE, site="acme-eu")]
        return httpx.Response(200, request=request, json=payload)

    async def scenario() -> list[ConnectorJob]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = LeverConnector(client, max_response_bytes=2 * 1024 * 1024)
            return await connector.fetch_open_jobs("acme-eu")

    jobs = asyncio.run(scenario())

    assert len(requests) == 3
    assert str(requests[0].url).startswith(f"{LEVER_GLOBAL_POSTINGS_API}/acme-eu")
    assert str(requests[1].url).startswith(f"{LEVER_EU_POSTINGS_API}/acme-eu")
    assert requests[1].url.params["skip"] == "0"
    assert requests[2].url.params["skip"] == str(LEVER_PAGE_SIZE)
    assert len(jobs) == LEVER_PAGE_SIZE + 1
    assert jobs[0].source_job_id == "posting-0"
    assert jobs[-1].source_job_id == f"posting-{LEVER_PAGE_SIZE}"


def test_lever_connector_rejects_invalid_identifiers_and_payloads() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request, json={"postings": []})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = LeverConnector(client, max_response_bytes=1024 * 1024)
            with pytest.raises(JobConnectorError, match="identifier is invalid"):
                await connector.fetch_open_jobs("../other-site")
            with pytest.raises(JobConnectorError, match="invalid postings response"):
                await connector.fetch_open_jobs("acme")

    asyncio.run(scenario())
    assert len(requests) == 1


def test_lever_source_failure_is_isolated_from_other_companies(tmp_path: Path) -> None:
    database_path = tmp_path / "m08.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        company_seed_path=tmp_path / "unused-seed.json",
        resume_storage_path=tmp_path / "resumes",
    )
    run_migrations(settings)
    engine = create_database_engine(settings.database_url)
    session = create_session_factory(engine)()

    try:
        session.add_all(
            [
                Company(
                    name="Broken Lever",
                    website_url="https://broken-lever.example",
                    careers_url="https://jobs.lever.co/broken-site",
                    provider_type="lever",
                    provider_identifier="broken-site",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Working Lever",
                    website_url="https://working-lever.example",
                    careers_url="https://jobs.lever.co/working-site",
                    provider_type="lever",
                    provider_identifier="working-site",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Unsupported Lever",
                    website_url="https://unsupported-lever.example",
                    careers_url="https://jobs.lever.co/unsupported-site",
                    provider_type="lever",
                    provider_identifier="unsupported-site",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=False,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Greenhouse Co",
                    website_url="https://greenhouse.example",
                    careers_url="https://boards.greenhouse.io/greenhouse-co",
                    provider_type="greenhouse",
                    provider_identifier="greenhouse-co",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                ),
            ]
        )
        session.commit()

        result = asyncio.run(
            JobCollectionService(session, concurrency=2).collect(FixtureLeverConnector())
        )

        assert result.sources_checked == 2
        assert result.sources_succeeded == 1
        assert result.sources_failed == 1
        assert result.jobs_fetched == 1
        assert [source.company_name for source in result.source_results] == [
            "Broken Lever",
            "Working Lever",
        ]
        assert result.source_results[0].status == "failed"
        assert result.source_results[0].jobs == ()
        assert result.source_results[0].error_message == "Fixture site is unavailable"
        assert result.source_results[1].status == "success"
        assert result.source_results[1].jobs[0].source_type == "lever"
    finally:
        session.close()
        engine.dispose()
