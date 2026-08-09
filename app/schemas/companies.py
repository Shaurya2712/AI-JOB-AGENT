from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_company_url(value: str) -> str:
    candidate = value.strip()
    parts = urlsplit(candidate)
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        raise ValueError("company URLs must be absolute HTTP or HTTPS URLs")
    if parts.username or parts.password:
        raise ValueError("company URLs must not contain credentials")

    scheme = parts.scheme.casefold()
    hostname = parts.hostname.casefold()
    port = parts.port
    netloc = hostname
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


class CompanySeedInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    website_url: str = Field(max_length=500)
    careers_url: str | None = Field(default=None, max_length=1000)
    provider_type: str | None = Field(default=None, max_length=40)
    provider_identifier: str | None = Field(default=None, max_length=255)
    provider_supported: bool = False
    is_active: bool = True

    @field_validator("website_url", "careers_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return normalize_company_url(value) if value else None
