import asyncio
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.db import create_database_engine, create_session_factory, run_migrations
from app.models.companies import Company
from app.providers.jobs.base import ConnectorJob, JobConnector, JobConnectorError
from app.providers.jobs.greenhouse import GREENHOUSE_JOBS_API, GreenhouseConnector
from app.services.job_collection import JobCollectionService


class FixtureGreenhouseConnector(JobConnector):
    source_type = "greenhouse"

    async def fetch_open_jobs(self, provider_identifier: str) -> list[ConnectorJob]:
        if provider_identifier == "broken-board":
            raise JobConnectorError("Fixture board is unavailable")
        return [
            ConnectorJob(
                source_type="greenhouse",
                source_job_id="101",
                title="Mobile Engineer",
                location_text="Pune",
                description="Build mobile products.",
                job_url="https://boards.greenhouse.io/working-board/jobs/101",
            )
        ]


def test_greenhouse_connector_fetches_and_maps_open_jobs() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            request=request,
            json={
                "jobs": [
                    {
                        "id": 101,
                        "internal_job_id": 1001,
                        "title": "  Mobile   Engineer  ",
                        "location": {"name": " Pune, India "},
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/101",
                        "content": "<p>Build &amp; ship.</p><ul><li>Flutter</li></ul>",
                    },
                    {
                        "id": 102,
                        "internal_job_id": 1002,
                        "title": "React Developer",
                        "location": None,
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/102",
                        "content": "React Native &amp; web",
                    },
                    {
                        "id": 103,
                        "internal_job_id": None,
                        "title": "General Application",
                        "location": {"name": "Remote"},
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/103",
                        "content": "Prospect post",
                    },
                ],
                "meta": {"total": 3},
            },
        )

    async def scenario() -> list[ConnectorJob]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = GreenhouseConnector(client, max_response_bytes=1024 * 1024)
            return await connector.fetch_open_jobs("acme")

    jobs = asyncio.run(scenario())

    assert len(requests) == 2
    request = requests[-1]
    assert str(request.url).startswith(f"{GREENHOUSE_JOBS_API}/acme/jobs")
    assert request.url.params["content"] == "true"
    assert request.headers["Accept"] == "application/json"
    assert "Authorization" not in request.headers
    assert jobs == [
        ConnectorJob(
            source_type="greenhouse",
            source_job_id="101",
            title="Mobile Engineer",
            location_text="Pune, India",
            description="Build & ship.\nFlutter",
            job_url="https://boards.greenhouse.io/acme/jobs/101",
        ),
        ConnectorJob(
            source_type="greenhouse",
            source_job_id="102",
            title="React Developer",
            location_text="",
            description="React Native & web",
            job_url="https://boards.greenhouse.io/acme/jobs/102",
        ),
    ]


def test_greenhouse_connector_rejects_invalid_identifiers_and_payloads() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            request=request,
            content=b'{"jobs":[{"id":1}]}',
            headers={"content-type": "application/json"},
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = GreenhouseConnector(client, max_response_bytes=1024 * 1024)
            with pytest.raises(JobConnectorError, match="identifier is invalid"):
                await connector.fetch_open_jobs("../other-board")
            with pytest.raises(JobConnectorError, match="invalid jobs response"):
                await connector.fetch_open_jobs("acme")

    asyncio.run(scenario())
    assert len(requests) == 1


def test_greenhouse_source_failure_is_isolated_from_other_companies(tmp_path: Path) -> None:
    database_path = tmp_path / "m07.db"
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
                    name="Broken Greenhouse",
                    website_url="https://broken.example",
                    careers_url="https://boards.greenhouse.io/broken-board",
                    provider_type="greenhouse",
                    provider_identifier="broken-board",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Working Greenhouse",
                    website_url="https://working.example",
                    careers_url="https://boards.greenhouse.io/working-board",
                    provider_type="greenhouse",
                    provider_identifier="working-board",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Unsupported Greenhouse",
                    website_url="https://unsupported.example",
                    careers_url="https://boards.greenhouse.io/unsupported",
                    provider_type="greenhouse",
                    provider_identifier="unsupported",
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
            JobCollectionService(session, concurrency=2).collect(
                FixtureGreenhouseConnector()
            )
        )

        assert result.sources_checked == 2
        assert result.sources_succeeded == 1
        assert result.sources_failed == 1
        assert result.jobs_fetched == 1
        assert [source.company_name for source in result.source_results] == [
            "Broken Greenhouse",
            "Working Greenhouse",
        ]
        assert result.source_results[0].status == "failed"
        assert result.source_results[0].jobs == ()
        assert result.source_results[0].error_message == "Fixture board is unavailable"
        assert result.source_results[1].status == "success"
        assert result.source_results[1].error_message is None
        assert result.source_results[1].jobs[0].source_job_id == "101"
    finally:
        session.close()
        engine.dispose()
