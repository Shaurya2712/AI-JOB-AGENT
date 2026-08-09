from app.models.jobs import Job
from app.models.profiles import CandidateProfile
from app.services.job_qualification import qualify_job


def _profile(
    *,
    target_roles: list[str] | None = None,
    role_synonyms: list[str] | None = None,
    skills: list[str] | None = None,
    years_experience: float = 5,
    excluded_keywords: list[str] | None = None,
) -> CandidateProfile:
    return CandidateProfile(
        name="Candidate",
        is_active=True,
        target_roles_json=(
            target_roles if target_roles is not None else ["Software Engineer"]
        ),
        role_synonyms_json=(
            role_synonyms if role_synonyms is not None else ["Backend Developer"]
        ),
        skills_json=(skills if skills is not None else ["Python", "PostgreSQL", "AWS"]),
        years_experience=years_experience,
        preferred_locations_json=[],
        work_modes_json=[],
        excluded_keywords_json=(
            excluded_keywords if excluded_keywords is not None else []
        ),
        notes="",
    )


def _job(
    title: str,
    *,
    description: str = "Build and operate reliable software products.",
    employment_type: str | None = None,
    experience_min: float | None = None,
    skills: list[str] | None = None,
) -> Job:
    return Job(
        company_id=1,
        source_type="greenhouse",
        source_job_id=title.casefold().replace(" ", "-"),
        canonical_url="https://jobs.example.com/role",
        title=title,
        normalized_title=title.casefold(),
        location_text="Remote",
        description=description,
        description_hash="a" * 64,
        dedupe_signature="b" * 64,
        experience_min=experience_min,
        skills_json=skills if skills is not None else [],
        employment_type=employment_type,
        consecutive_missing_scans=0,
        lifecycle_status="open",
    )


def test_internships_and_obviously_unrelated_roles_are_rejected() -> None:
    profile = _profile()

    internship = qualify_job(profile, _job("Software Engineering Intern"))
    internal_tools = qualify_job(profile, _job("Internal Tools Engineer"))
    unrelated = qualify_job(profile, _job("Sales Engineer"))

    assert internship.qualified is False
    assert "internship" in internship.rejection_reasons
    assert internal_tools.qualified is True
    assert unrelated.qualified is False
    assert "unrelated_role" in unrelated.rejection_reasons


def test_management_is_rejected_only_when_not_targeted() -> None:
    engineering_profile = _profile()
    management_profile = _profile(
        target_roles=["Engineering Manager"],
        role_synonyms=[],
    )
    job = _job("Engineering Manager")

    inappropriate = qualify_job(engineering_profile, job)
    targeted = qualify_job(management_profile, job)

    assert inappropriate.qualified is False
    assert "management_only" in inappropriate.rejection_reasons
    assert targeted.qualified is True


def test_experience_filter_is_flexible_but_rejects_obvious_mismatches() -> None:
    profile = _profile(years_experience=5)

    flexible = qualify_job(
        profile,
        _job("Senior Software Engineer", experience_min=8),
    )
    structured_mismatch = qualify_job(
        profile,
        _job("Lead Software Engineer", experience_min=9),
    )
    parsed_mismatch = qualify_job(
        profile,
        _job(
            "Principal Software Engineer",
            description="For this role, 10 years of professional experience is required.",
        ),
    )
    preferred_only = qualify_job(
        profile,
        _job(
            "Senior Software Engineer",
            description="10+ years of professional experience preferred, but not required.",
        ),
    )

    assert flexible.qualified is True
    assert structured_mismatch.rejection_reasons == ("experience_mismatch",)
    assert parsed_mismatch.rejection_reasons == ("experience_mismatch",)
    assert preferred_only.qualified is True


def test_senior_lead_partial_skills_and_user_exclusions_are_handled_safely() -> None:
    profile = _profile(
        skills=["Python", "PostgreSQL", "AWS", "Kubernetes"],
        excluded_keywords=["contract role"],
    )

    partial_skill_match = qualify_job(
        profile,
        _job("Technical Lead", skills=["Python"]),
    )
    excluded = qualify_job(
        profile,
        _job(
            "Senior Software Engineer",
            description="This is a six-month contract role on the platform team.",
            skills=["Python"],
        ),
    )

    assert partial_skill_match.qualified is True
    assert excluded.qualified is False
    assert excluded.rejection_reasons == ("excluded_keyword",)
