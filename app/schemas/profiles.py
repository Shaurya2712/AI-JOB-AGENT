from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_TARGET_ROLES = [
    "Flutter Developer",
    "React Native Developer",
    "React Developer",
    "Software Developer",
    "AI Developer",
    "Software Engineer — Mobile App Development",
]

DEFAULT_ROLE_SYNONYMS = [
    "Mobile Developer",
    "Mobile Engineer",
    "Software Engineer — Mobile",
    "Cross-platform Developer",
    "Application Developer",
    "Frontend Mobile Engineer",
]

ALLOWED_WORK_MODES = {"Remote", "Hybrid", "Onsite"}


def normalize_entries(entries: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        value = entry.strip()
        key = value.casefold()
        if value and key not in seen:
            values.append(value)
            seen.add(key)
    return values


def parse_entries(raw_value: str) -> list[str]:
    return normalize_entries(raw_value.replace(",", "\n").splitlines())


class CandidateProfileInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    is_active: bool = True
    years_experience: float = Field(default=0, ge=0, le=80)
    target_roles: list[str]
    role_synonyms: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    work_modes: list[str] = Field(default_factory=list)
    minimum_salary: Decimal | None = Field(default=None, ge=0, le=1_000_000_000)
    salary_currency: str = Field(default="INR", min_length=3, max_length=3)
    excluded_keywords: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=5000)

    @field_validator(
        "target_roles",
        "role_synonyms",
        "skills",
        "preferred_locations",
        "work_modes",
        "excluded_keywords",
    )
    @classmethod
    def clean_entries(cls, value: list[str]) -> list[str]:
        cleaned = normalize_entries(value)
        if len(cleaned) > 100 or any(len(item) > 120 for item in cleaned):
            raise ValueError("each list supports up to 100 values of 120 characters")
        return cleaned

    @field_validator("salary_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_profile(self) -> "CandidateProfileInput":
        if not self.target_roles:
            raise ValueError("at least one target role is required")
        unknown_modes = set(self.work_modes) - ALLOWED_WORK_MODES
        if unknown_modes:
            raise ValueError("work modes must be Remote, Hybrid, or Onsite")
        return self


class ProfileSuggestionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    suggestion_type: Literal["skill", "role"]
    value: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=2000)
