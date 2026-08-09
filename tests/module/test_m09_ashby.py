import asyncio
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.db import create_database_engine, create_session_factory, run_migrations
from app.models.companies import Company
from app.providers.jobs.ashby import ASHBY_JOB_BOARD_API, AshbyConnector
from app.providers.jobs.base import ConnectorJob, JobConnector, JobConnectorError
from app.services.job_collection import JobCollectionService


class FixtureAshbyConnector(JobConnector):
    source_type = "ashby"

    async def fetch_open_jobs(self, provider_identifier: str) -> list[ConnectorJob]:
        if provider_identifier == "broken-board":
            raise JobConnectorError("Fixture board is unavailable")
        return [
            ConnectorJob(
                source_type="ashby",
                source_job_id="ashby-101",
                title="Flutter Engineer",
                location_text="Remote",
                description="Build mobile products.",
                job_url="https://jobs.ashbyhq.com/working-board/ashby-101",
            )
        ]


def test_ashby_connector_fetches_and_maps_listed_jobs() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            request=request,
            json={
                "apiVersion": "1",
                "jobs": [
                    {
                        "title": "  Flutter   Engineer ",
                        "location": " Pune, India ",
                        "descriptionPlain": "Build mobile products.\n\n Ship reliable software.",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/ashby-101",
                        "isListed": True,
                    },
                    {
                        "title": "React Developer",
                        "location": None,
                        "descriptionPlain": "Build web products.",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/ashby-102",
                        "isListed": True,
                    },
                    {
                        "title": "Unlisted Role",
                        "location": "Remote",
                        "descriptionPlain": "Direct-link only.",
                        "jobUrl": "https://jobs.ashbyhq.com/acme/ashby-103",
                        "isListed": False,
                    },
                ],
            },
        )

    async def scenario() -> list[ConnectorJob]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = AshbyConnector(client, max_response_bytes=1024 * 1024)
            return await connector.fetch_open_jobs("acme")

    jobs = asyncio.run(scenario())

    assert len(requests) == 2
    request = requests[-1]
    assert str(request.url).startswith(f"{ASHBY_JOB_BOARD_API}/acme")
    assert request.url.params["includeCompensation"] == "false"
    assert request.headers["Accept"] == "application/json"
    assert "Authorization" not in request.headers
    assert jobs == [
        ConnectorJob(
            source_type="ashby",
            source_job_id="ashby-101",
            title="Flutter Engineer",
            location_text="Pune, India",
            description="Build mobile products.\nShip reliable software.",
            job_url="https://jobs.ashbyhq.com/acme/ashby-101",
        ),
        ConnectorJob(
            source_type="ashby",
            source_job_id="ashby-102",
            title="React Developer",
            location_text="",
            description="Build web products.",
            job_url="https://jobs.ashbyhq.com/acme/ashby-102",
        ),
    ]


def test_ashby_connector_rejects_invalid_identifiers_and_payloads() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            request=request,
            json={"apiVersion": "1", "jobs": [{"title": "Missing fields"}]},
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = AshbyConnector(client, max_response_bytes=1024 * 1024)
            with pytest.raises(JobConnectorError, match="identifier is invalid"):
                await connector.fetch_open_jobs("../other-board")
            with pytest.raises(JobConnectorError, match="invalid jobs response"):
                await connector.fetch_open_jobs("acme")

    asyncio.run(scenario())
    assert len(requests) == 1


def test_ashby_source_failure_is_isolated_from_other_companies(tmp_path: Path) -> None:
    database_path = tmp_path / "m09.db"
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
                    name="Broken Ashby",
                    website_url="https://broken-ashby.example",
                    careers_url="https://jobs.ashbyhq.com/broken-board",
                    provider_type="ashby",
                    provider_identifier="broken-board",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Working Ashby",
                    website_url="https://working-ashby.example",
                    careers_url="https://jobs.ashbyhq.com/working-board",
                    provider_type="ashby",
                    provider_identifier="working-board",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Unsupported Ashby",
                    website_url="https://unsupported-ashby.example",
                    careers_url="https://jobs.ashbyhq.com/unsupported-board",
                    provider_type="ashby",
                    provider_identifier="unsupported-board",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=False,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Lever Co",
                    website_url="https://lever.example",
                    careers_url="https://jobs.lever.co/lever-co",
                    provider_type="lever",
                    provider_identifier="lever-co",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                ),
            ]
        )
        session.commit()

        result = asyncio.run(
            JobCollectionService(session, concurrency=2).collect(FixtureAshbyConnector())
        )

        assert result.sources_checked == 2
        assert result.sources_succeeded == 1
        assert result.sources_failed == 1
        assert result.jobs_fetched == 1
        assert [source.company_name for source in result.source_results] == [
            "Broken Ashby",
            "Working Ashby",
        ]
        assert result.source_results[0].status == "failed"
        assert result.source_results[0].jobs == ()
        assert result.source_results[0].error_message == "Fixture board is unavailable"
        assert result.source_results[1].status == "success"
        assert result.source_results[1].jobs[0].source_type == "ashby"
    finally:
        session.close()
        engine.dispose()
