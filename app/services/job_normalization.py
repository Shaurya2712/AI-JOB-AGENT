from dataclasses import dataclass
from hashlib import sha256
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.providers.jobs.base import ConnectorJob


MAX_JOB_DESCRIPTION_CHARS = 2_000_000
_SOURCE_TYPE_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
_TRACKING_QUERY_KEYS = frozenset(
    {"gh_src", "ref", "referrer", "source", "trackingid"}
)


class JobNormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedConnectorJob:
    source_type: str
    source_job_id: str
    canonical_url: str
    title: str
    normalized_title: str
    location_text: str
    description: str
    description_hash: str
    dedupe_signature: str


def normalize_connector_job(company_id: int, job: ConnectorJob) -> NormalizedConnectorJob:
    if company_id <= 0:
        raise JobNormalizationError("Company identifier is invalid")

    source_type = job.source_type.strip().casefold()
    source_job_id = job.source_job_id.strip()
    title = _display_text(job.title)
    normalized_title = _identity_text(title)
    location = _display_text(job.location_text)
    description = _description_text(job.description)

    if not _SOURCE_TYPE_PATTERN.fullmatch(source_type):
        raise JobNormalizationError("Job source type is invalid")
    if not source_job_id or len(source_job_id) > 255 or _has_control_character(source_job_id):
        raise JobNormalizationError("Source job identifier is invalid")
    if not title or len(title) > 1000 or not normalized_title:
        raise JobNormalizationError("Job title is invalid")
    if len(location) > 1000:
        raise JobNormalizationError("Job location is too long")
    if len(description) > MAX_JOB_DESCRIPTION_CHARS:
        raise JobNormalizationError("Job description is too long")

    canonical_url = normalize_job_url(job.job_url)
    description_hash = _hash_text(_identity_description(description))
    signature_value = "\0".join(
        (
            str(company_id),
            normalized_title,
            _identity_text(location),
            description_hash,
        )
    )
    return NormalizedConnectorJob(
        source_type=source_type,
        source_job_id=source_job_id,
        canonical_url=canonical_url,
        title=title,
        normalized_title=normalized_title,
        location_text=location,
        description=description,
        description_hash=description_hash,
        dedupe_signature=_hash_text(signature_value),
    )


def normalize_job_url(raw_url: str) -> str:
    candidate = raw_url.strip()
    if not candidate or len(candidate) > 4000:
        raise JobNormalizationError("Job URL is invalid")
    try:
        parts = urlsplit(candidate)
        scheme = parts.scheme.casefold()
        hostname = (parts.hostname or "").casefold().rstrip(".")
        if (
            scheme not in {"http", "https"}
            or not hostname
            or parts.username
            or parts.password
        ):
            raise JobNormalizationError("Job URL is invalid")
        port = parts.port
        netloc = f"[{hostname}]" if ":" in hostname else hostname
        if port and not (
            (scheme == "http" and port == 80)
            or (scheme == "https" and port == 443)
        ):
            netloc = f"{hostname}:{port}"

        parameters = [
            (key, value)
            for key, value in parse_qsl(
                parts.query,
                keep_blank_values=True,
                max_num_fields=100,
            )
            if not key.casefold().startswith("utm_")
            and key.casefold() not in _TRACKING_QUERY_KEYS
        ]
        parameters.sort(key=lambda item: (item[0].casefold(), item[0], item[1]))
        path = parts.path or "/"
        if path != "/":
            path = path.rstrip("/") or "/"
        normalized = urlunsplit((scheme, netloc, path, urlencode(parameters), ""))
    except (TypeError, ValueError) as error:
        raise JobNormalizationError("Job URL is invalid") from error

    if len(normalized) > 4000:
        raise JobNormalizationError("Job URL is invalid")
    return normalized


def _display_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _description_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return "\n".join(
        " ".join(line.split())
        for line in normalized.splitlines()
        if line.strip()
    )


def _identity_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w+#.]+", " ", normalized).split())


def _identity_description(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _has_control_character(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)
