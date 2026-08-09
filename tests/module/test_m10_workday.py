import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.db import create_database_engine, create_session_factory, run_migrations
from app.models.companies import Company
from app.providers.jobs.base import ConnectorJob, JobConnector, JobConnectorError
from app.providers.jobs.workday import WORKDAY_PAGE_SIZE, WorkdayConnector
from app.services.ats_detection import AtsDetectionService, AtsUrlDetector
from app.services.job_collection import JobCollectionService


WORKDAY_IDENTIFIER = "acme.wd5.myworkdayjobs.com/acme/External_Careers"


class FixtureWorkdayConnector(JobConnector):
    source_type = "workday"

    async def fetch_open_jobs(self, provider_identifier: str) -> list[ConnectorJob]:
        if provider_identifier.endswith("/broken"):
            raise JobConnectorError("Fixture Workday site is unavailable")
        return [
            ConnectorJob(
                source_type="workday",
                source_job_id="opaque-workday-id",
                title="Python Engineer",
                location_text="Pune, India",
                description="Build reliable services.",
                job_url=(
                    "https://working.wd5.myworkdayjobs.com/External/job/Pune/"
                    "Python-Engineer_REQ-101"
                ),
            )
        ]


def _summary(index: int) -> dict[str, str]:
    return {
        "title": f"Role {index}",
        "externalPath": f"/job/Pune/Role-{index}_REQ-{index}",
    }


def test_workday_connector_paginates_and_maps_open_job_details() -> None:
    requests: list[httpx.Request] = []
    detail_attempts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            offset = body["offset"]
            postings = (
                [_summary(index) for index in range(1, WORKDAY_PAGE_SIZE + 1)]
                if offset == 0
                else [_summary(WORKDAY_PAGE_SIZE + 1)]
            )
            return httpx.Response(
                200,
                request=request,
                json={"total": WORKDAY_PAGE_SIZE + 1, "jobPostings": postings},
            )

        job_number = request.url.path.split("Role-")[1].split("_")[0]
        detail_attempts[job_number] = detail_attempts.get(job_number, 0) + 1
        if job_number == "1" and detail_attempts[job_number] == 1:
            return httpx.Response(503, request=request)

        is_open = job_number != str(WORKDAY_PAGE_SIZE + 1)
        return httpx.Response(
            200,
            request=request,
            json={
                "jobPostingInfo": {
                    "id": f"opaque-{job_number}",
                    "title": (
                        "  Principal   Python Engineer "
                        if job_number == "1"
                        else f"Role {job_number}"
                    ),
                    "jobDescription": (
                        "<p>Build <b>reliable</b> services.</p>"
                        "<ul><li>Ship safely.</li></ul>"
                    ),
                    "location": "  Pune,   India ",
                    "posted": is_open,
                    "canApply": is_open,
                }
            },
        )

    async def scenario() -> list[ConnectorJob]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = WorkdayConnector(
                client,
                max_response_bytes=1024 * 1024,
                request_concurrency=3,
            )
            return await connector.fetch_open_jobs(WORKDAY_IDENTIFIER)

    jobs = asyncio.run(scenario())

    listing_requests = [request for request in requests if request.method == "POST"]
    assert [json.loads(request.content)["offset"] for request in listing_requests] == [0, 20]
    assert all(json.loads(request.content)["limit"] == 20 for request in listing_requests)
    assert all(json.loads(request.content)["appliedFacets"] == {} for request in listing_requests)
    assert all(json.loads(request.content)["searchText"] == "" for request in listing_requests)
    assert all(request.headers["Accept"] == "application/json" for request in requests)
    assert all("Authorization" not in request.headers for request in requests)
    assert detail_attempts["1"] == 2
    assert len(jobs) == WORKDAY_PAGE_SIZE
    assert jobs[0] == ConnectorJob(
        source_type="workday",
        source_job_id="opaque-1",
        title="Principal Python Engineer",
        location_text="Pune, India",
        description="Build reliable services.\nShip safely.",
        job_url=(
            "https://acme.wd5.myworkdayjobs.com/External_Careers/job/Pune/"
            "Role-1_REQ-1"
        ),
    )
    assert all(job.source_job_id != "opaque-21" for job in jobs)


def test_workday_connector_rejects_unsupported_identifiers_and_response_variants() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            request=request,
            json={
                "total": 1,
                "jobPostings": [
                    {"title": "Unsafe path", "externalPath": "https://evil.example/job/1"}
                ],
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            connector = WorkdayConnector(
                client,
                max_response_bytes=1024 * 1024,
                request_concurrency=2,
            )
            with pytest.raises(JobConnectorError, match="identifier is unsupported"):
                await connector.fetch_open_jobs("acme/External_Careers")
            with pytest.raises(JobConnectorError, match="identifier is unsupported"):
                await connector.fetch_open_jobs(
                    "evil.example/acme/External_Careers"
                )
            with pytest.raises(JobConnectorError, match="unsupported job path"):
                await connector.fetch_open_jobs(WORKDAY_IDENTIFIER)

    asyncio.run(scenario())
    assert len(requests) == 1


def test_workday_detection_retains_the_exact_public_site_host() -> None:
    detection = AtsUrlDetector().detect(
        "https://acme.wd5.myworkdayjobs.com/en-US/External_Careers/job/Pune/REQ-101"
    )

    assert detection.provider_type == "workday"
    assert detection.provider_identifier == WORKDAY_IDENTIFIER
    assert detection.provider_supported is True


def test_workday_classification_refreshes_a_legacy_hostname_free_identifier(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "m10-legacy.db"
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
        company = Company(
            name="Legacy Workday",
            website_url="https://legacy-workday.example",
            careers_url=(
                "https://acme.wd5.myworkdayjobs.com/en-US/External_Careers"
            ),
            provider_type="workday",
            provider_identifier="acme/External_Careers",
            discovery_source="seed",
            is_active=True,
            provider_supported=True,
            total_jobs_seen=0,
        )
        session.add(company)
        session.commit()

        result = AtsDetectionService(session).classify_active_companies()
        session.refresh(company)

        assert result.supported_companies == 1
        assert company.provider_identifier == WORKDAY_IDENTIFIER
        assert company.provider_supported is True
    finally:
        session.close()
        engine.dispose()


def test_workday_source_failure_is_isolated_from_other_companies(tmp_path: Path) -> None:
    database_path = tmp_path / "m10.db"
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
                    name="Broken Workday",
                    website_url="https://broken-workday.example",
                    careers_url="https://broken.wd5.myworkdayjobs.com/broken",
                    provider_type="workday",
                    provider_identifier="broken.wd5.myworkdayjobs.com/broken/broken",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Working Workday",
                    website_url="https://working-workday.example",
                    careers_url="https://working.wd5.myworkdayjobs.com/External",
                    provider_type="workday",
                    provider_identifier="working.wd5.myworkdayjobs.com/working/External",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Unsupported Workday",
                    website_url="https://unsupported-workday.example",
                    careers_url="https://unsupported.wd5.myworkdayjobs.com/External",
                    provider_type="workday",
                    provider_identifier=(
                        "unsupported.wd5.myworkdayjobs.com/unsupported/External"
                    ),
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=False,
                    total_jobs_seen=0,
                ),
                Company(
                    name="Ashby Co",
                    website_url="https://ashby.example",
                    careers_url="https://jobs.ashbyhq.com/ashby-co",
                    provider_type="ashby",
                    provider_identifier="ashby-co",
                    discovery_source="seed",
                    is_active=True,
                    provider_supported=True,
                    total_jobs_seen=0,
                ),
            ]
        )
        session.commit()

        result = asyncio.run(
            JobCollectionService(session, concurrency=2).collect(FixtureWorkdayConnector())
        )

        assert result.sources_checked == 2
        assert result.sources_succeeded == 1
        assert result.sources_failed == 1
        assert result.jobs_fetched == 1
        assert [source.company_name for source in result.source_results] == [
            "Broken Workday",
            "Working Workday",
        ]
        assert result.source_results[0].status == "failed"
        assert result.source_results[0].jobs == ()
        assert result.source_results[0].error_message == (
            "Fixture Workday site is unavailable"
        )
        assert result.source_results[1].status == "success"
        assert result.source_results[1].jobs[0].source_type == "workday"
    finally:
        session.close()
        engine.dispose()
