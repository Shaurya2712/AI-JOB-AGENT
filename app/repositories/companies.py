from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.companies import Company


class CompanyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_companies(self) -> list[Company]:
        statement = select(Company).order_by(Company.is_active.desc(), Company.name, Company.id)
        return list(self.session.scalars(statement).all())

    def list_active_companies(self) -> list[Company]:
        statement = (
            select(Company)
            .where(Company.is_active.is_(True))
            .order_by(Company.name, Company.id)
        )
        return list(self.session.scalars(statement).all())

    def list_connector_ready_companies(self, provider_type: str) -> list[Company]:
        statement = (
            select(Company)
            .where(
                Company.is_active.is_(True),
                Company.provider_supported.is_(True),
                Company.provider_type == provider_type,
                Company.provider_identifier.is_not(None),
            )
            .order_by(Company.name, Company.id)
        )
        return list(self.session.scalars(statement).all())

    def list_generic_fallback_companies(self) -> list[Company]:
        statement = (
            select(Company)
            .where(
                Company.is_active.is_(True),
                Company.provider_type == "custom",
                Company.careers_url.is_not(None),
            )
            .order_by(Company.name, Company.id)
        )
        return list(self.session.scalars(statement).all())

    def get_by_website_url(self, website_url: str) -> Company | None:
        return self.session.scalar(select(Company).where(Company.website_url == website_url))

    def add(self, company: Company) -> None:
        self.session.add(company)
