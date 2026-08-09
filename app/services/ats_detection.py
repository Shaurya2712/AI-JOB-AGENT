from dataclasses import dataclass
import re
from urllib.parse import parse_qs, unquote, urlsplit

from sqlalchemy.orm import Session

from app.models.base import utc_now
from app.models.companies import Company
from app.repositories.companies import CompanyRepository


SUPPORTED_PROVIDER_TYPES = frozenset({"greenhouse", "lever", "ashby", "workday"})
RECOGNIZED_PROVIDER_TYPES = frozenset(
    {*SUPPORTED_PROVIDER_TYPES, "icims", "bamboohr", "custom", "unknown"}
)
_STORED_ATS_PROVIDER_TYPES = frozenset(
    {*SUPPORTED_PROVIDER_TYPES, "icims", "bamboohr"}
)
_GREENHOUSE_JOB_HOSTS = frozenset(
    {
        "boards.greenhouse.io",
        "boards.eu.greenhouse.io",
        "job-boards.greenhouse.io",
        "job-boards.eu.greenhouse.io",
    }
)
_GREENHOUSE_API_HOSTS = frozenset(
    {"boards-api.greenhouse.io", "boards-api.eu.greenhouse.io"}
)
_LEVER_JOB_HOSTS = frozenset({"jobs.lever.co", "jobs.eu.lever.co"})
_LEVER_API_HOSTS = frozenset({"api.lever.co", "api.eu.lever.co"})
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}")
_LOCALE_PATTERN = re.compile(r"[a-z]{2}-[a-z]{2}", flags=re.IGNORECASE)
_WORKDAY_HOST_PATTERN = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.wd[0-9]{1,4}\.myworkdayjobs\.com"
)
_WORKDAY_PATH_IDENTIFIER_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._~-]{0,127}"
)


@dataclass(frozen=True)
class AtsDetection:
    provider_type: str
    provider_identifier: str | None
    provider_supported: bool
    skip_reason: str | None


@dataclass(frozen=True)
class CompanyAtsDecision:
    company_id: int
    company_name: str
    provider_type: str
    provider_identifier: str | None
    should_use_connector: bool
    skip_reason: str | None


@dataclass(frozen=True)
class AtsClassificationResult:
    companies_checked: int
    supported_companies: int
    skipped_companies: int
    decisions: tuple[CompanyAtsDecision, ...]


class AtsUrlDetector:
    def detect(self, raw_url: str | None) -> AtsDetection:
        parsed = self._parse_url(raw_url)
        if parsed is None:
            return self._result("unknown", None)

        hostname, path_segments, query = parsed
        provider_type: str
        identifier: str | None

        if hostname in _GREENHOUSE_JOB_HOSTS:
            if [part.casefold() for part in path_segments[:2]] == ["embed", "job_board"]:
                identifier = self._clean_identifier(query.get("for", [None])[0])
            else:
                identifier = self._first_identifier(path_segments)
            provider_type = "greenhouse"
        elif hostname in _GREENHOUSE_API_HOSTS:
            identifier = self._identifier_after(path_segments, ["v1", "boards"])
            provider_type = "greenhouse"
        elif hostname in _LEVER_JOB_HOSTS:
            identifier = self._first_identifier(path_segments)
            provider_type = "lever"
        elif hostname in _LEVER_API_HOSTS:
            identifier = self._identifier_after(path_segments, ["v0", "postings"])
            provider_type = "lever"
        elif hostname == "jobs.ashbyhq.com":
            identifier = self._first_identifier(path_segments)
            provider_type = "ashby"
        elif hostname == "api.ashbyhq.com":
            identifier = self._identifier_after(path_segments, ["posting-api", "job-board"])
            provider_type = "ashby"
        elif hostname == "myworkdayjobs.com" or hostname.endswith(".myworkdayjobs.com"):
            identifier = self._workday_identifier(hostname, path_segments)
            provider_type = "workday"
        elif hostname == "icims.com" or hostname.endswith(".icims.com"):
            identifier = self._subdomain_identifier(hostname, "icims.com")
            provider_type = "icims"
        elif hostname == "bamboohr.com" or hostname.endswith(".bamboohr.com"):
            identifier = self._subdomain_identifier(hostname, "bamboohr.com")
            provider_type = "bamboohr"
        else:
            identifier = self._clean_identifier(hostname)
            provider_type = "custom"

        return self._result(provider_type, identifier)

    @staticmethod
    def from_stored(provider_type: str, provider_identifier: str) -> AtsDetection:
        normalized_type = provider_type.strip().casefold()
        identifier = AtsUrlDetector._clean_identifier(provider_identifier)
        if normalized_type not in RECOGNIZED_PROVIDER_TYPES or identifier is None:
            return AtsUrlDetector()._result("unknown", None)
        if normalized_type == "workday" and not AtsUrlDetector._is_workday_identifier(
            identifier
        ):
            return AtsUrlDetector()._result("unknown", None)
        return AtsUrlDetector()._result(normalized_type, identifier)

    @staticmethod
    def _is_workday_identifier(identifier: str) -> bool:
        parts = identifier.split("/")
        return (
            len(parts) == 3
            and _WORKDAY_HOST_PATTERN.fullmatch(parts[0]) is not None
            and _WORKDAY_PATH_IDENTIFIER_PATTERN.fullmatch(parts[1]) is not None
            and _WORKDAY_PATH_IDENTIFIER_PATTERN.fullmatch(parts[2]) is not None
        )

    @staticmethod
    def _parse_url(
        raw_url: str | None,
    ) -> tuple[str, list[str], dict[str, list[str]]] | None:
        if not raw_url:
            return None
        try:
            parts = urlsplit(raw_url.strip())
            if (
                parts.scheme.casefold() not in {"http", "https"}
                or not parts.hostname
                or parts.username
                or parts.password
            ):
                return None
            path_segments = [
                unquote(segment).strip()
                for segment in parts.path.split("/")
                if unquote(segment).strip()
            ][:12]
            query = parse_qs(parts.query, keep_blank_values=False, max_num_fields=20)
            return parts.hostname.casefold(), path_segments, query
        except (TypeError, ValueError):
            return None

    @classmethod
    def _result(cls, provider_type: str, identifier: str | None) -> AtsDetection:
        supported = provider_type in SUPPORTED_PROVIDER_TYPES and identifier is not None
        if supported:
            reason = None
        elif provider_type in SUPPORTED_PROVIDER_TYPES:
            reason = "missing provider identifier"
        elif provider_type == "unknown":
            reason = "invalid or missing career URL"
        elif provider_type == "custom":
            reason = "custom source requires the generic career-page fallback"
        else:
            reason = f"{provider_type} connector is unsupported in V1"
        return AtsDetection(
            provider_type=provider_type,
            provider_identifier=identifier,
            provider_supported=supported,
            skip_reason=reason,
        )

    @classmethod
    def _first_identifier(cls, path_segments: list[str]) -> str | None:
        return cls._clean_identifier(path_segments[0] if path_segments else None)

    @classmethod
    def _identifier_after(cls, path_segments: list[str], prefix: list[str]) -> str | None:
        prefix_length = len(prefix)
        if [part.casefold() for part in path_segments[:prefix_length]] != prefix:
            return None
        if len(path_segments) <= prefix_length:
            return None
        return cls._clean_identifier(path_segments[prefix_length])

    @classmethod
    def _workday_identifier(cls, hostname: str, path_segments: list[str]) -> str | None:
        if not _WORKDAY_HOST_PATTERN.fullmatch(hostname):
            return None
        tenant = hostname.removesuffix(".myworkdayjobs.com").split(".")[0]
        tenant = cls._clean_identifier(tenant)
        if tenant is None:
            return None

        if [segment.casefold() for segment in path_segments[:2]] == ["wday", "cxs"]:
            if len(path_segments) < 4:
                return None
            url_tenant = cls._clean_identifier(path_segments[2])
            site = cls._clean_identifier(path_segments[3])
            if url_tenant and site:
                return cls._clean_identifier(f"{hostname}/{url_tenant}/{site}")
            return None

        site_index = 1 if path_segments and _LOCALE_PATTERN.fullmatch(path_segments[0]) else 0
        if len(path_segments) <= site_index:
            return None
        site = cls._clean_identifier(path_segments[site_index])
        return cls._clean_identifier(f"{hostname}/{tenant}/{site}") if site else None

    @classmethod
    def _subdomain_identifier(cls, hostname: str, suffix: str) -> str | None:
        subdomain = hostname.removesuffix(f".{suffix}")
        if subdomain == hostname:
            return None
        return cls._clean_identifier(subdomain)

    @staticmethod
    def _clean_identifier(value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip().strip("/")
        if not candidate or not _IDENTIFIER_PATTERN.fullmatch(candidate):
            return None
        return candidate


class AtsDetectionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = CompanyRepository(session)
        self.detector = AtsUrlDetector()

    def classify_active_companies(self) -> AtsClassificationResult:
        companies = self.repository.list_active_companies()
        decisions: list[CompanyAtsDecision] = []
        supported = 0
        skipped = 0

        try:
            for company in companies:
                detection = self._detect_company(company)
                if (
                    company.provider_type != detection.provider_type
                    or company.provider_identifier != detection.provider_identifier
                    or company.provider_supported != detection.provider_supported
                ):
                    company.provider_type = detection.provider_type
                    company.provider_identifier = detection.provider_identifier
                    company.provider_supported = detection.provider_supported
                    company.updated_at = utc_now()

                if detection.provider_supported:
                    supported += 1
                else:
                    skipped += 1
                decisions.append(
                    CompanyAtsDecision(
                        company_id=company.id,
                        company_name=company.name,
                        provider_type=detection.provider_type,
                        provider_identifier=detection.provider_identifier,
                        should_use_connector=detection.provider_supported,
                        skip_reason=detection.skip_reason,
                    )
                )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return AtsClassificationResult(
            companies_checked=len(companies),
            supported_companies=supported,
            skipped_companies=skipped,
            decisions=tuple(decisions),
        )

    def _detect_company(self, company: Company) -> AtsDetection:
        stored_type = (company.provider_type or "").strip().casefold()
        if stored_type in _STORED_ATS_PROVIDER_TYPES and company.provider_identifier:
            stored = self.detector.from_stored(
                stored_type,
                company.provider_identifier,
            )
            if stored.provider_type != "unknown":
                return stored
        return self.detector.detect(company.careers_url or company.website_url)
