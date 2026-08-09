from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "job_agent.db"


class Settings(BaseSettings):
    app_name: str = "Job Agent"
    environment: Literal["local", "test", "production"] = "local"
    database_url: str = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="JOB_AGENT_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
