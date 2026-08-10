from dataclasses import dataclass
from typing import Literal

from app.models.profiles import CandidateProfile


PortalName = Literal["linkedin", "naukri", "indeed"]
PORTAL_NAMES: tuple[PortalName, ...] = ("linkedin", "naukri", "indeed")
_PORTAL_QUERY_PREFIXES = {
    "linkedin": "site:linkedin.com/jobs/view",
    "naukri": "site:naukri.com/job-listings",
    "indeed": "site:indeed.com/viewjob",
}


@dataclass(frozen=True)
class ProfileSearchTarget:
    profile_id: int
    role: str
    location: str | None


@dataclass(frozen=True)
class ProfileSearchQuery:
    profile_id: int
    text: str


class ProfileSearchTargetGenerator:
    def generate(
        self,
        profiles: list[CandidateProfile],
        *,
        max_targets: int,
    ) -> list[ProfileSearchTarget]:
        targets: list[ProfileSearchTarget] = []
        seen: set[tuple[str, str]] = set()
        for profile in profiles:
            roles = self._ordered_unique(
                [*profile.target_roles_json, *profile.role_synonyms_json]
            )
            locations: list[str | None] = list(
                self._ordered_unique(profile.preferred_locations_json)
            )
            if any(mode.casefold() == "remote" for mode in profile.work_modes_json):
                if not any(location.casefold() == "remote" for location in locations):
                    locations.append("Remote")
            if not locations:
                locations = [None]

            for role in roles:
                for location in locations:
                    key = (role.casefold(), (location or "").casefold())
                    if key in seen:
                        continue
                    targets.append(
                        ProfileSearchTarget(
                            profile_id=profile.id,
                            role=role,
                            location=location,
                        )
                    )
                    seen.add(key)
                    if len(targets) >= max_targets:
                        return targets
        return targets

    @staticmethod
    def _ordered_unique(values: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for raw_value in values:
            value = " ".join(raw_value.replace('"', " ").split())
            key = value.casefold()
            if value and key not in seen:
                unique.append(value)
                seen.add(key)
        return unique


class ProfileSearchQueryGenerator:
    def __init__(self, max_queries: int) -> None:
        self.max_queries = max_queries
        self.target_generator = ProfileSearchTargetGenerator()

    def generate(self, profiles: list[CandidateProfile]) -> list[ProfileSearchQuery]:
        queries: list[ProfileSearchQuery] = []
        for target in self.target_generator.generate(
            profiles,
            max_targets=self.max_queries,
        ):
            queries.append(
                ProfileSearchQuery(
                    profile_id=target.profile_id,
                    text=self._build_query(target.role, target.location),
                )
            )
            if len(queries) >= self.max_queries:
                break
        return queries

    @staticmethod
    def _build_query(role: str, location: str | None) -> str:
        query = f'"{role}" jobs careers'
        if location:
            query = f'{query} "{location}"'
        return _bounded_query(query)


@dataclass(frozen=True)
class PortalSearchQuery:
    profile_id: int
    portal: PortalName
    text: str


class PortalSearchQueryGenerator:
    def __init__(self, max_queries: int) -> None:
        self.max_queries = max_queries
        self.target_generator = ProfileSearchTargetGenerator()

    def generate(self, profiles: list[CandidateProfile]) -> list[PortalSearchQuery]:
        queries: list[PortalSearchQuery] = []
        target_limit = (self.max_queries + len(PORTAL_NAMES) - 1) // len(PORTAL_NAMES)
        for target in self.target_generator.generate(
            profiles,
            max_targets=target_limit,
        ):
            for portal in PORTAL_NAMES:
                query = f'{_PORTAL_QUERY_PREFIXES[portal]} "{target.role}"'
                if target.location:
                    query = f'{query} "{target.location}"'
                queries.append(
                    PortalSearchQuery(
                        profile_id=target.profile_id,
                        portal=portal,
                        text=_bounded_query(query),
                    )
                )
                if len(queries) >= self.max_queries:
                    return queries
        return queries


def _bounded_query(query: str) -> str:
    words = query.split()[:50]
    return " ".join(words)[:400].strip()
