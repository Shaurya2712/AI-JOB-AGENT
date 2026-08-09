from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url

from app.config import PROJECT_ROOT, Settings


MIGRATIONS_DIR = PROJECT_ROOT / "migrations"
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "alembic.ini"


def _ensure_database_directory(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        return
    if url.database == ":memory:":
        return
    Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def create_database_engine(database_url: str) -> Engine:
    _ensure_database_directory(database_url)
    url = make_url(database_url)
    connect_args = {"timeout": 5.0} if url.get_backend_name() == "sqlite" else {}
    engine = create_engine(database_url, connect_args=connect_args)

    if url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine


def run_migrations(settings: Settings) -> None:
    _ensure_database_directory(settings.database_url)
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.attributes["database_url"] = settings.database_url
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def database_is_ready(engine: Engine) -> bool:
    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1
