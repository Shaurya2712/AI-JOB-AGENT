from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models.runtime_settings import RuntimeSetting


PORTABLE_SETTING_NAMES = (
    "app_name",
    "log_level",
    "resume_max_bytes",
    "search_provider",
    "search_country",
    "search_language",
    "search_results_per_query",
    "search_max_queries_per_run",
    "search_concurrency",
    "search_timeout_seconds",
    "job_source_timeout_seconds",
    "job_source_concurrency",
    "job_source_max_response_bytes",
    "job_lifecycle_close_after_missing_scans",
    "daily_action_target",
    "scan_interval_hours",
    "telegram_match_threshold",
    "telegram_timeout_seconds",
    "ai_provider",
    "ai_model",
    "ai_timeout_seconds",
    "ai_concurrency",
)
PORTABLE_SETTING_NAME_SET = frozenset(PORTABLE_SETTING_NAMES)


class RuntimeSettingsService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def save(self, settings: Settings) -> dict[str, object]:
        values = portable_settings(settings)
        with self.session_factory() as session:
            stored = {
                row.key: row
                for row in session.scalars(select(RuntimeSetting))
            }
            for key, value in values.items():
                row = stored.get(key)
                if row is None:
                    session.add(RuntimeSetting(key=key, value_json=value))
                else:
                    row.value_json = value
            for key, row in stored.items():
                if key not in PORTABLE_SETTING_NAME_SET:
                    session.delete(row)
            session.commit()
        return values

    def load(self, base_settings: Settings) -> Settings:
        with self.session_factory() as session:
            rows = tuple(session.scalars(select(RuntimeSetting)))
        stored = {
            row.key: row.value_json
            for row in rows
            if row.key in PORTABLE_SETTING_NAME_SET
            and row.key not in base_settings.model_fields_set
        }
        if not stored:
            return base_settings
        values = base_settings.model_dump()
        values.update(stored)
        return Settings.model_validate(values)


def portable_settings(settings: Settings) -> dict[str, object]:
    values = settings.model_dump(mode="json")
    return {name: values[name] for name in PORTABLE_SETTING_NAMES}
