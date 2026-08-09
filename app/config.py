from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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
    search_provider: Literal["brave", "disabled"] = "brave"
    brave_search_api_key: SecretStr | None = None
    search_country: str = Field(default="IN", min_length=2, max_length=2)
    search_language: str = Field(default="en", min_length=2, max_length=10)
    search_results_per_query: int = Field(default=10, ge=1, le=20)
    search_max_queries_per_run: int = Field(default=30, ge=1, le=100)
    search_concurrency: int = Field(default=3, ge=1, le=5)
    search_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    job_source_timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    job_source_concurrency: int = Field(default=3, ge=1, le=5)
    job_source_max_response_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=1024,
        le=25 * 1024 * 1024,
    )
    job_lifecycle_close_after_missing_scans: int = Field(default=3, ge=3, le=20)
    daily_action_target: int = Field(default=10, ge=1, le=100)
    ai_provider: Literal["disabled", "openai", "anthropic", "gemini"] = "disabled"
    ai_model: str = Field(default="", max_length=120)
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    ai_timeout_seconds: float = Field(default=45.0, ge=5.0, le=120.0)
    ai_concurrency: int = Field(default=2, ge=1, le=3)

    model_config = SettingsConfigDict(
        env_prefix="JOB_AGENT_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
