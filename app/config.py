from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "job_agent.db"
DEFAULT_RESUME_STORAGE_PATH = PROJECT_ROOT / "data" / "resumes"
DEFAULT_COMPANY_SEED_PATH = PROJECT_ROOT / "data" / "seeds" / "companies.json"


class Settings(BaseSettings):
    app_name: str = "Job Agent"
    environment: Literal["local", "test", "production"] = "local"
    database_url: str = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
    log_level: str = "INFO"
    resume_storage_path: Path = DEFAULT_RESUME_STORAGE_PATH
    resume_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1, le=25 * 1024 * 1024)
    company_seed_path: Path = DEFAULT_COMPANY_SEED_PATH

    model_config = SettingsConfigDict(
        env_prefix="JOB_AGENT_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
