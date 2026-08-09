from dataclasses import dataclass

from app.models.profiles import CandidateProfile


@dataclass(frozen=True)
class ProfileSearchQuery:
    profile_id: int
    text: str


class ProfileSearchQueryGenerator:
    def __init__(self, max_queries: int) -> None:
        self.max_queries = max_queries

    def generate(self, profiles: list[CandidateProfile]) -> list[ProfileSearchQuery]:
        queries: list[ProfileSearchQuery] = []
        seen: set[str] = set()

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
                    query = self._build_query(role, location)
                    key = query.casefold()
                    if key in seen:
                        continue
                    queries.append(ProfileSearchQuery(profile_id=profile.id, text=query))
                    seen.add(key)
                    if len(queries) >= self.max_queries:
                        return queries

        return queries

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

    @staticmethod
    def _build_query(role: str, location: str | None) -> str:
        query = f'"{role}" jobs careers'
        if location:
            query = f'{query} "{location}"'
        words = query.split()[:50]
        return " ".join(words)[:400].strip()
