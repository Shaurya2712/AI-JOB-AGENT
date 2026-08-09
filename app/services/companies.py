from dataclasses import dataclass
import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.models.companies import Company
from app.repositories.companies import CompanyRepository
from app.schemas.companies import CompanySeedInput


MAX_SEED_FILE_BYTES = 1024 * 1024


class CompanySeedError(ValueError):
    pass


@dataclass(frozen=True)
class CompanySeedResult:
    created: int
    existing: int


class CompanyService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = CompanyRepository(session)

    def list_companies(self) -> list[Company]:
        return self.repository.list_companies()

    def import_seed_file(self, seed_path: Path) -> CompanySeedResult:
        path = seed_path.expanduser().resolve()
        try:
            if path.stat().st_size > MAX_SEED_FILE_BYTES:
                raise CompanySeedError("Company seed file exceeds the 1 MiB limit")
            raw_data = json.loads(path.read_text(encoding="utf-8"))
            seeds = TypeAdapter(list[CompanySeedInput]).validate_python(raw_data)
        except CompanySeedError:
            raise
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            raise CompanySeedError(f"Company seed file is invalid: {path}") from error

        created = 0
        existing = 0
        try:
            for seed in seeds:
                company = self.repository.get_by_website_url(seed.website_url)
                if company is not None:
                    existing += 1
                    self._fill_missing_seed_values(company, seed)
                    continue

                self.repository.add(
                    Company(
                        name=seed.name,
                        website_url=seed.website_url,
                        careers_url=seed.careers_url,
                        provider_type=seed.provider_type,
                        provider_identifier=seed.provider_identifier,
                        discovery_source="seed",
                        is_active=seed.is_active,
                        provider_supported=seed.provider_supported,
                        total_jobs_seen=0,
                    )
                )
                created += 1
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return CompanySeedResult(created=created, existing=existing)

    @staticmethod
    def _fill_missing_seed_values(company: Company, seed: CompanySeedInput) -> None:
        if company.careers_url is None and seed.careers_url is not None:
            company.careers_url = seed.careers_url
        if company.provider_type is None and seed.provider_type is not None:
            company.provider_type = seed.provider_type
        if company.provider_identifier is None and seed.provider_identifier is not None:
            company.provider_identifier = seed.provider_identifier
