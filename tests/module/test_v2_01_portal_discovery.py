import asyncio

import pytest

from app.models.profiles import CandidateProfile
from app.providers.search.base import SearchProviderError, WebSearchProvider, WebSearchResult
from app.services.portal_discovery import PortalDiscoveryService, PortalJobResultRecognizer
from app.services.search_queries import PortalSearchQueryGenerator
from app.services.web_discovery import SearchDiscoveryParser


def profile(
    *,
    roles: list[str] | None = None,
    synonyms: list[str] | None = None,
    locations: list[str] | None = None,
    work_modes: list[str] | None = None,
) -> CandidateProfile:
    return CandidateProfile(
        id=7,
        name="Primary",
        is_active=True,
        years_experience=5,
        target_roles_json=roles or ["Flutter Developer"],
        role_synonyms_json=synonyms or [],
        skills_json=[],
        preferred_locations_json=locations or [],
        work_modes_json=work_modes or [],
        excluded_keywords_json=[],
    )


class SelectiveSearchProvider(WebSearchProvider):
    name = "selective"

    def __init__(self) -> None:
        self.queries: list[str] = []

    @property
    def is_configured(self) -> bool:
        return True

    async def search(self, query: str) -> list[WebSearchResult]:
        self.queries.append(query)
        if query.startswith("site:linkedin.com"):
            raise SearchProviderError("LinkedIn search unavailable")
        if query.startswith("site:naukri.com"):
            return [
                WebSearchResult(
                    title="Flutter Developer Job at Beta Labs in Pune - Naukri.com",
                    url=(
                        "https://www.naukri.com/"
                        "job-listings-flutter-developer-beta-labs-pune-12082025123456"
                    ),
                    description="Build and maintain mobile applications for our product team.",
                )
            ]
        return [
            WebSearchResult(
                title="React Native Developer - Gamma Ltd - Remote | Indeed.com",
                url="https://in.indeed.com/viewjob?jk=abc123xyz789",
                description="Develop reliable cross-platform mobile features.",
            )
        ]


class UnconfiguredSearchProvider(WebSearchProvider):
    name = "disabled-fixture"

    def __init__(self) -> None:
        self.calls = 0

    @property
    def is_configured(self) -> bool:
        return False

    async def search(self, query: str) -> list[WebSearchResult]:
        self.calls += 1
        raise AssertionError(f"search should not be called: {query}")


def test_portal_queries_are_round_robin_deterministic_and_bounded() -> None:
    candidate_profile = profile(
        roles=["Flutter Developer", "flutter developer"],
        synonyms=["Mobile Engineer"],
        locations=["Pune"],
        work_modes=["Remote"],
    )

    queries = PortalSearchQueryGenerator(max_queries=8).generate([candidate_profile])

    assert [(query.profile_id, query.portal, query.text) for query in queries] == [
        (7, "linkedin", 'site:linkedin.com/jobs/view "Flutter Developer" "Pune"'),
        (7, "naukri", 'site:naukri.com/job-listings "Flutter Developer" "Pune"'),
        (7, "indeed", 'site:indeed.com/viewjob "Flutter Developer" "Pune"'),
        (7, "linkedin", 'site:linkedin.com/jobs/view "Flutter Developer" "Remote"'),
        (7, "naukri", 'site:naukri.com/job-listings "Flutter Developer" "Remote"'),
        (7, "indeed", 'site:indeed.com/viewjob "Flutter Developer" "Remote"'),
        (7, "linkedin", 'site:linkedin.com/jobs/view "Mobile Engineer" "Pune"'),
        (7, "naukri", 'site:naukri.com/job-listings "Mobile Engineer" "Pune"'),
    ]
    assert all(len(query.text) <= 400 for query in queries)
    assert all(len(query.text.split()) <= 50 for query in queries)


@pytest.mark.parametrize(
    ("portal", "result", "expected"),
    [
        (
            "linkedin",
            WebSearchResult(
                title="Acme hiring <b>Senior Mobile Engineer</b> in Bengaluru | LinkedIn",
                url=(
                    "https://in.linkedin.com/jobs/view/"
                    "senior-mobile-engineer-4035123456?trackingId=ignored"
                ),
                description="Build&nbsp;mobile products with Flutter and Kotlin.",
            ),
            (
                "4035123456",
                "https://in.linkedin.com/jobs/view/senior-mobile-engineer-4035123456",
                "Senior Mobile Engineer",
                "Acme",
                "Bengaluru",
                "Build mobile products with Flutter and Kotlin.",
            ),
        ),
        (
            "naukri",
            WebSearchResult(
                title="Flutter Developer Job at Beta Labs in Pune - Naukri.com",
                url=(
                    "https://www.naukri.com/"
                    "job-listings-flutter-developer-beta-labs-pune-12082025123456"
                    "?utm_source=search"
                ),
                description="Work on customer-facing Android and iOS applications.",
            ),
            (
                "12082025123456",
                (
                    "https://www.naukri.com/"
                    "job-listings-flutter-developer-beta-labs-pune-12082025123456"
                ),
                "Flutter Developer",
                "Beta Labs",
                "Pune",
                "Work on customer-facing Android and iOS applications.",
            ),
        ),
        (
            "indeed",
            WebSearchResult(
                title="React Native Developer - Gamma Ltd - Remote | Indeed.com",
                url="https://in.indeed.com/viewjob?jk=abc123xyz789&from=web",
                description="Develop reliable cross-platform mobile features.",
            ),
            (
                "abc123xyz789",
                "https://in.indeed.com/viewjob?jk=abc123xyz789",
                "React Native Developer",
                "Gamma Ltd",
                "Remote",
                "Develop reliable cross-platform mobile features.",
            ),
        ),
    ],
)
def test_recognizer_accepts_only_job_detail_shapes_and_normalizes_metadata(
    portal,
    result: WebSearchResult,
    expected: tuple[str, str, str, str, str, str],
) -> None:
    candidate = PortalJobResultRecognizer().recognize(portal, result)

    assert candidate is not None
    assert (
        candidate.source_job_id,
        candidate.original_url,
        candidate.title,
        candidate.company_name,
        candidate.location_text,
        candidate.snippet,
    ) == expected
    assert candidate.portal == portal
    assert candidate.data_completeness == "partial"


@pytest.mark.parametrize(
    ("portal", "url"),
    [
        ("linkedin", "https://www.linkedin.com/"),
        ("linkedin", "https://www.linkedin.com/jobs/search?keywords=python"),
        ("linkedin", "https://www.linkedin.com/company/acme/jobs"),
        ("linkedin", "https://www.linkedin.com/in/recruiter"),
        ("linkedin", "https://www.linkedin.com/help/linkedin/article/123"),
        ("linkedin", "https://www.linkedin.com/pulse/job-search-guide"),
        ("naukri", "https://www.naukri.com/"),
        ("naukri", "https://www.naukri.com/jobs-in-india"),
        ("naukri", "https://www.naukri.com/acme-company-overview"),
        ("naukri", "https://www.naukri.com/recruiters/acme"),
        ("naukri", "https://www.naukri.com/faq/job-seeker"),
        ("naukri", "https://www.naukri.com/blog/job-search-guide"),
        ("indeed", "https://in.indeed.com/"),
        ("indeed", "https://in.indeed.com/jobs?q=python"),
        ("indeed", "https://in.indeed.com/cmp/acme/jobs"),
        ("indeed", "https://profile.indeed.com/"),
        ("indeed", "https://in.indeed.com/career-advice/finding-a-job"),
        ("indeed", "https://support.indeed.com/hc/en-in"),
    ],
)
def test_recognizer_rejects_non_job_portal_pages(portal, url: str) -> None:
    result = WebSearchResult(
        title="Mobile Engineer - Acme - Pune | Indeed.com",
        url=url,
        description="A realistic-looking result must still have a job-detail URL.",
    )

    assert PortalJobResultRecognizer().recognize(portal, result) is None


@pytest.mark.parametrize(
    ("portal", "result"),
    [
        (
            "linkedin",
            WebSearchResult(
                title="Software Engineer | LinkedIn",
                url="https://linkedin.com/jobs/view/software-engineer-4035123456",
            ),
        ),
        (
            "naukri",
            WebSearchResult(
                title="Software Engineer Jobs - Naukri.com",
                url="https://naukri.com/job-listings-software-engineer-12082025123456",
            ),
        ),
        (
            "indeed",
            WebSearchResult(
                title="Software Engineer - Pune | Indeed.com",
                url="https://indeed.com/viewjob?jk=abc123xyz789",
            ),
        ),
        (
            "indeed",
            WebSearchResult(
                title="Software Engineer - Acme - Pune | Indeed.com",
                url="https://indeed.com.evil.example/viewjob?jk=abc123xyz789",
            ),
        ),
    ],
)
def test_recognizer_rejects_missing_employer_or_spoofed_host(portal, result) -> None:
    assert PortalJobResultRecognizer().recognize(portal, result) is None


def test_portal_failure_is_isolated_and_candidates_are_deduplicated() -> None:
    provider = SelectiveSearchProvider()
    service = PortalDiscoveryService(provider, max_queries=6, concurrency=2)

    result = asyncio.run(
        service.discover(
            [profile(locations=["Pune"], work_modes=["Remote"])]
        )
    )

    by_portal = {source.portal: source for source in result.source_results}
    assert result.queries_generated == 6
    assert result.searches_succeeded == 4
    assert result.searches_failed == 2
    assert len(result.candidates) == 2
    assert by_portal["linkedin"].searches_failed == 2
    assert by_portal["linkedin"].candidates == ()
    assert by_portal["naukri"].searches_succeeded == 2
    assert len(by_portal["naukri"].candidates) == 1
    assert by_portal["indeed"].searches_succeeded == 2
    assert len(by_portal["indeed"].candidates) == 1
    assert all("linkedin:" in error for error in result.errors)


def test_unconfigured_provider_returns_bounded_source_errors_without_searching() -> None:
    provider = UnconfiguredSearchProvider()
    service = PortalDiscoveryService(provider, max_queries=3, concurrency=2)

    result = asyncio.run(service.discover([profile()]))

    assert provider.calls == 0
    assert result.queries_generated == 3
    assert result.searches_succeeded == 0
    assert result.searches_failed == 0
    assert result.candidates == ()
    assert [source.portal for source in result.source_results] == [
        "linkedin",
        "naukri",
        "indeed",
    ]
    assert all(source.errors == ("disabled-fixture search is not configured",) for source in result.source_results)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/jobs/view/mobile-engineer-4035123456",
        "https://www.naukri.com/job-listings-mobile-engineer-acme-12082025123456",
        "https://in.indeed.com/viewjob?jk=abc123xyz789",
    ],
)
def test_company_discovery_still_rejects_portal_job_urls(url: str) -> None:
    result = WebSearchResult(
        title="Acme Careers and Jobs",
        url=url,
        description="View open careers at Acme.",
    )

    assert SearchDiscoveryParser().parse(result) is None
