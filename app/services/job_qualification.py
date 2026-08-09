from dataclasses import dataclass
import re

from app.models.jobs import Job
from app.models.profiles import CandidateProfile


EXPERIENCE_FLEXIBILITY_YEARS = 3.0

_TOKEN_PATTERN = re.compile(r"[a-z0-9+#.]+")
_INTERNSHIP_TOKENS = frozenset({"intern", "internship", "internships"})
_MANAGEMENT_TOKENS = frozenset(
    {
        "chief",
        "director",
        "head",
        "management",
        "manager",
        "president",
        "supervisor",
        "vp",
    }
)
_ROLE_QUALIFIER_TOKENS = frozenset(
    {
        "associate",
        "entry",
        "i",
        "ii",
        "iii",
        "iv",
        "jr",
        "junior",
        "lead",
        "level",
        "mid",
        "principal",
        "senior",
        "sr",
        "staff",
    }
)
_ROLE_FILLER_TOKENS = frozenset({"a", "and", "for", "of", "the"})
_ROLE_ALIASES = {
    "developers": "engineer",
    "developer": "engineer",
    "development": "engineer",
    "engineers": "engineer",
    "engineering": "engineer",
    "programmer": "engineer",
    "programmers": "engineer",
    "tech": "software",
    "technical": "software",
    "technology": "software",
}
_OBVIOUSLY_UNRELATED_DOMAINS = frozenset(
    {
        "accountant",
        "accounting",
        "chemical",
        "civil",
        "hr",
        "legal",
        "lawyer",
        "marketing",
        "mechanical",
        "nurse",
        "nursing",
        "physician",
        "recruiter",
        "recruiting",
        "recruitment",
        "sales",
        "structural",
    }
)
_PREFERRED_CONTEXT_PATTERN = re.compile(
    r"\b(?:desirable|nice\s+to\s+have|preferred)\b",
    re.IGNORECASE,
)
_EXPERIENCE_PATTERNS = (
    re.compile(
        r"\b(?P<years>\d{1,2}(?:\.\d+)?)\s*\+\s*(?:years?|yrs?)"
        r"(?:\s+of)?(?:\s+[a-z][a-z/-]*){0,5}\s+experience\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:at\s+least|minimum(?:\s+of)?)\s+"
        r"(?P<years>\d{1,2}(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)"
        r"(?:\s+of)?(?:\s+[a-z][a-z/-]*){0,5}\s+experience\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:requires?|required|must\s+have)(?:\s+at\s+least)?\s+"
        r"(?P<years>\d{1,2}(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)"
        r"(?:\s+of)?(?:\s+[a-z][a-z/-]*){0,5}\s+experience\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<years>\d{1,2}(?:\.\d+)?)\s*(?:-|–|—|to)\s*"
        r"\d{1,2}(?:\.\d+)?\s*(?:years?|yrs?)"
        r"(?:\s+of)?(?:\s+[a-z][a-z/-]*){0,5}\s+experience\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bexperience\s*:\s*(?P<years>\d{1,2}(?:\.\d+)?)\s*\+?\s*"
        r"(?:years?|yrs?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<years>\d{1,2}(?:\.\d+)?)\s*(?:years?|yrs?)"
        r"(?:\s+of)?(?:\s+[a-z][a-z/-]*){0,5}\s+experience"
        r"\s+(?:is\s+)?required\b",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class QualificationResult:
    qualified: bool
    rejection_reasons: tuple[str, ...]


def qualify_job(profile: CandidateProfile, job: Job) -> QualificationResult:
    reasons: list[str] = []

    if _contains_excluded_keyword(profile, job):
        reasons.append("excluded_keyword")
    if _is_internship(job):
        reasons.append("internship")

    job_role_tokens = _role_tokens(job.title)
    if _is_management_role(job.title) and not _management_is_targeted(
        profile,
        job_role_tokens,
    ):
        reasons.append("management_only")
    if not _role_is_related(profile, job_role_tokens):
        reasons.append("unrelated_role")

    required_experience = _required_experience(job)
    if (
        required_experience is not None
        and required_experience
        > max(0.0, profile.years_experience) + EXPERIENCE_FLEXIBILITY_YEARS
    ):
        reasons.append("experience_mismatch")

    return QualificationResult(
        qualified=not reasons,
        rejection_reasons=tuple(reasons),
    )


def _is_internship(job: Job) -> bool:
    title_tokens = set(_tokens(job.title))
    employment_tokens = set(_tokens(job.employment_type or ""))
    return bool((title_tokens | employment_tokens) & _INTERNSHIP_TOKENS)


def _contains_excluded_keyword(profile: CandidateProfile, job: Job) -> bool:
    searchable_text = "\n".join(
        (job.title, job.employment_type or "", job.description)
    ).casefold()
    for keyword in profile.excluded_keywords_json or []:
        keyword_tokens = _tokens(keyword)
        if not keyword_tokens:
            continue
        pattern = r"(?<![\w+#.])" + r"[^\w+#.]+".join(
            re.escape(token) for token in keyword_tokens
        ) + r"(?![\w+#.])"
        if re.search(pattern, searchable_text):
            return True
    return False


def _is_management_role(title: str) -> bool:
    return bool(set(_tokens(title)) & _MANAGEMENT_TOKENS)


def _management_is_targeted(
    profile: CandidateProfile,
    job_role_tokens: set[str],
) -> bool:
    for role in _profile_roles(profile):
        if not (set(_tokens(role)) & _MANAGEMENT_TOKENS):
            continue
        target_tokens = _role_tokens(role)
        if not target_tokens or target_tokens & job_role_tokens:
            return True
    return False


def _role_is_related(
    profile: CandidateProfile,
    job_role_tokens: set[str],
) -> bool:
    profile_role_tokens: set[str] = set()
    for role in _profile_roles(profile):
        profile_role_tokens.update(_role_tokens(role))
    if not profile_role_tokens:
        return True

    unrelated_domains = job_role_tokens & _OBVIOUSLY_UNRELATED_DOMAINS
    if unrelated_domains - profile_role_tokens:
        return False
    return bool(job_role_tokens & profile_role_tokens)


def _profile_roles(profile: CandidateProfile) -> tuple[str, ...]:
    return tuple(
        [
            *(profile.target_roles_json or []),
            *(profile.role_synonyms_json or []),
        ]
    )


def _role_tokens(value: str) -> set[str]:
    ignored = _ROLE_QUALIFIER_TOKENS | _MANAGEMENT_TOKENS | _ROLE_FILLER_TOKENS
    return {
        _ROLE_ALIASES.get(token, token)
        for token in _tokens(value)
        if token not in ignored
    }


def _required_experience(job: Job) -> float | None:
    if job.experience_min is not None and job.experience_min > 0:
        return job.experience_min

    requirements: list[float] = []
    for pattern in _EXPERIENCE_PATTERNS:
        for match in pattern.finditer(job.description):
            context = job.description[
                max(0, match.start() - 30) : min(len(job.description), match.end() + 30)
            ]
            if _PREFERRED_CONTEXT_PATTERN.search(context):
                continue
            requirements.append(float(match.group("years")))
    return max(requirements, default=None)


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN_PATTERN.findall(value.casefold()))
