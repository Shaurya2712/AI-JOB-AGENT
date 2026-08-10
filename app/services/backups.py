from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
from tempfile import mkdtemp, mkstemp
from uuid import uuid4
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.engine import make_url

from app.config import Settings
from app.db import run_migrations
from app.services.runtime_settings import (
    PORTABLE_SETTING_NAME_SET,
    RuntimeSettingsService,
)


BACKUP_FORMAT = "job-agent-backup"
BACKUP_VERSION = 1
SCHEMA_REVISION = "20260810_0011"
V1_SCHEMA_REVISION = "20260809_0010"
SUPPORTED_SCHEMA_REVISIONS = frozenset({V1_SCHEMA_REVISION, SCHEMA_REVISION})
DATABASE_ARCHIVE_PATH = "database.sqlite3"
MANIFEST_ARCHIVE_PATH = "manifest.json"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 10_000
MAX_MANIFEST_BYTES = 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024
REQUIRED_DATABASE_TABLES = frozenset(
    {
        "alembic_version",
        "candidate_profiles",
        "companies",
        "job_matches",
        "job_user_state",
        "jobs",
        "notification_destinations",
        "notification_log",
        "portal_job_sources",
        "profile_suggestions",
        "resumes",
        "scan_runs",
        "scan_source_results",
        "settings",
    }
)
V1_REQUIRED_DATABASE_TABLES = REQUIRED_DATABASE_TABLES - {"portal_job_sources"}
V1_PORTABLE_SETTING_NAME_SET = PORTABLE_SETTING_NAME_SET - {
    "portal_search_max_queries_per_run"
}


class BackupError(ValueError):
    pass


@dataclass(frozen=True)
class BackupArtifact:
    archive_path: Path
    workspace: Path
    filename: str

    def cleanup(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)


@dataclass(frozen=True)
class _ResumeEntry:
    storage_reference: str
    archive_path: str
    size: int
    checksum: str


class BackupService:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        runtime_settings: RuntimeSettingsService,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.runtime_settings = runtime_settings
        self.database_path = _sqlite_database_path(settings.database_url)
        configured_resume_root = settings.resume_storage_path.expanduser()
        if configured_resume_root.is_symlink():
            raise BackupError("Resume storage path is unsafe")
        self.resume_root = configured_resume_root.resolve()
        if (
            self.resume_root.parent == self.resume_root
            or (self.resume_root.exists() and not self.resume_root.is_dir())
        ):
            raise BackupError("Resume storage path is unsafe")

    def create_archive(self) -> BackupArtifact:
        portable_values = self.runtime_settings.save(self.settings)
        workspace = Path(mkdtemp(prefix="job-agent-backup-"))
        snapshot_path = workspace / DATABASE_ARCHIVE_PATH
        archive_path = workspace / "job-agent-backup.zip"
        try:
            _sqlite_backup(self.database_path, snapshot_path)
            database_size = snapshot_path.stat().st_size
            resume_entries = self._resume_entries(snapshot_path)
            total_size = database_size + sum(item.size for item in resume_entries)
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise BackupError("Backup contents exceed the configured safety limit")
            if len(resume_entries) + 2 > MAX_ARCHIVE_FILES:
                raise BackupError("Backup contains too many files")

            manifest = {
                "format": BACKUP_FORMAT,
                "version": BACKUP_VERSION,
                "schema_revision": SCHEMA_REVISION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "database": {
                    "path": DATABASE_ARCHIVE_PATH,
                    "size": database_size,
                    "sha256": _file_sha256(snapshot_path),
                },
                "resumes": [
                    {
                        "storage_reference": item.storage_reference,
                        "path": item.archive_path,
                        "size": item.size,
                        "sha256": item.checksum,
                    }
                    for item in resume_entries
                ],
                "settings": portable_values,
            }
            manifest_bytes = json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            with ZipFile(
                archive_path,
                "w",
                compression=ZIP_DEFLATED,
                compresslevel=6,
                allowZip64=True,
            ) as archive:
                archive.write(snapshot_path, DATABASE_ARCHIVE_PATH)
                for entry in resume_entries:
                    archive.write(
                        self.resume_root / entry.storage_reference,
                        entry.archive_path,
                    )
                archive.writestr(MANIFEST_ARCHIVE_PATH, manifest_bytes)
            if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
                raise BackupError("Backup archive exceeds the upload safety limit")
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            return BackupArtifact(
                archive_path=archive_path,
                workspace=workspace,
                filename=f"job-agent-backup-{timestamp}.zip",
            )
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

    def restore_archive(self, archive_path: Path) -> dict[str, object]:
        if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise BackupError("Backup archive exceeds the upload safety limit")
        database_stage = _temporary_file(self.database_path.parent, ".restore-db-")
        self.resume_root.parent.mkdir(parents=True, exist_ok=True)
        resume_stage = Path(
            mkdtemp(prefix=".resume-restore-", dir=self.resume_root.parent)
        )
        rollback_database = _temporary_file(
            self.database_path.parent,
            ".rollback-db-",
        )
        rollback_resume = self.resume_root.parent / (
            f".{self.resume_root.name}.rollback-{uuid4().hex}"
        )
        database_replaced = False
        resume_replaced = False
        had_resume_root = self.resume_root.exists()
        try:
            settings_values = self._stage_and_validate(
                archive_path,
                database_stage,
                resume_stage,
            )
            _sqlite_backup(self.database_path, rollback_database)
            self.engine.dispose()
            _remove_sqlite_sidecars(self.database_path)
            os.replace(database_stage, self.database_path)
            database_replaced = True

            if had_resume_root:
                os.replace(self.resume_root, rollback_resume)
            os.replace(resume_stage, self.resume_root)
            resume_replaced = True
            _validate_database(self.database_path, settings_values)

            rollback_database.unlink(missing_ok=True)
            if rollback_resume.exists():
                shutil.rmtree(rollback_resume)
            return settings_values
        except BackupError:
            if database_replaced:
                self._restore_database_rollback(rollback_database)
            if database_replaced or resume_replaced:
                self._restore_resume_rollback(
                    rollback_resume,
                    had_resume_root=had_resume_root,
                )
            raise
        except Exception as error:
            if database_replaced:
                self._restore_database_rollback(rollback_database)
            if database_replaced or resume_replaced:
                self._restore_resume_rollback(
                    rollback_resume,
                    had_resume_root=had_resume_root,
                )
            raise BackupError("Backup restore failed safely") from error
        finally:
            database_stage.unlink(missing_ok=True)
            rollback_database.unlink(missing_ok=True)
            if resume_stage.exists():
                shutil.rmtree(resume_stage, ignore_errors=True)
            if rollback_resume.exists():
                shutil.rmtree(rollback_resume, ignore_errors=True)

    def _resume_entries(self, snapshot_path: Path) -> tuple[_ResumeEntry, ...]:
        with sqlite3.connect(snapshot_path) as connection:
            references = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT file_path FROM resumes ORDER BY file_path"
                )
            )
        entries: list[_ResumeEntry] = []
        for reference in references:
            storage_reference = _safe_storage_reference(str(reference))
            storage_path = self.resume_root / storage_reference
            source = storage_path.resolve()
            if (
                source.parent != self.resume_root
                or not source.is_file()
                or storage_path.is_symlink()
            ):
                raise BackupError(
                    f"Stored resume {storage_reference} is missing or unsafe"
                )
            entries.append(
                _ResumeEntry(
                    storage_reference=storage_reference,
                    archive_path=f"resumes/{storage_reference}",
                    size=source.stat().st_size,
                    checksum=_file_sha256(source),
                )
            )
        return tuple(entries)

    def _stage_and_validate(
        self,
        archive_path: Path,
        database_stage: Path,
        resume_stage: Path,
    ) -> dict[str, object]:
        try:
            with ZipFile(archive_path) as archive:
                infos = archive.infolist()
                _validate_archive_infos(infos)
                manifest = _read_manifest(archive)
                manifest_settings, resume_entries, schema_revision = _validate_manifest(
                    manifest,
                    self.settings,
                )
                expected_names = {
                    MANIFEST_ARCHIVE_PATH,
                    DATABASE_ARCHIVE_PATH,
                    *(item.archive_path for item in resume_entries),
                }
                if {info.filename for info in infos} != expected_names:
                    raise BackupError("Backup archive contents do not match its manifest")

                database_info = archive.getinfo(DATABASE_ARCHIVE_PATH)
                database_manifest = manifest["database"]
                _extract_checked(
                    archive,
                    database_info,
                    database_stage,
                    expected_size=database_manifest["size"],
                    expected_checksum=database_manifest["sha256"],
                )
                required_tables = (
                    REQUIRED_DATABASE_TABLES
                    if schema_revision == SCHEMA_REVISION
                    else V1_REQUIRED_DATABASE_TABLES
                )
                _validate_database(
                    database_stage,
                    manifest_settings,
                    schema_revision=schema_revision,
                    required_tables=required_tables,
                )
                settings_values = dict(manifest_settings)
                if schema_revision == V1_SCHEMA_REVISION:
                    settings_values = self._migrate_v1_database(
                        database_stage,
                        settings_values,
                    )
                    _validate_database(database_stage, settings_values)
                _checkpoint_sqlite(database_stage)

                with sqlite3.connect(database_stage) as connection:
                    database_resumes = {
                        str(row[0])
                        for row in connection.execute("SELECT file_path FROM resumes")
                    }
                manifest_resumes = {
                    item.storage_reference for item in resume_entries
                }
                if database_resumes != manifest_resumes:
                    raise BackupError(
                        "Backup resume files do not match the database records"
                    )
                for entry in resume_entries:
                    destination = resume_stage / entry.storage_reference
                    _extract_checked(
                        archive,
                        archive.getinfo(entry.archive_path),
                        destination,
                        expected_size=entry.size,
                        expected_checksum=entry.checksum,
                    )
                return settings_values
        except BackupError:
            raise
        except (BadZipFile, KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BackupError("Backup archive is invalid or unreadable") from error

    def _migrate_v1_database(
        self,
        database_path: Path,
        settings_values: dict[str, object],
    ) -> dict[str, object]:
        migrated_settings = dict(settings_values)
        if "portal_search_max_queries_per_run" not in migrated_settings:
            portal_query_cap = self.settings.portal_search_max_queries_per_run
            migrated_settings["portal_search_max_queries_per_run"] = portal_query_cap
            try:
                with sqlite3.connect(database_path) as connection:
                    connection.execute(
                        "INSERT INTO settings (key, value_json) VALUES (?, ?)",
                        (
                            "portal_search_max_queries_per_run",
                            json.dumps(portal_query_cap),
                        ),
                    )
                    connection.commit()
            except sqlite3.DatabaseError as error:
                raise BackupError("V1 backup settings could not be migrated") from error

        migration_values = self.settings.model_dump()
        migration_values.update(migrated_settings)
        migration_values["database_url"] = f"sqlite:///{database_path.as_posix()}"
        try:
            run_migrations(Settings.model_validate(migration_values))
        except Exception as error:
            raise BackupError("V1 backup database could not be migrated") from error
        return migrated_settings

    def _restore_database_rollback(self, rollback_database: Path) -> None:
        self.engine.dispose()
        _remove_sqlite_sidecars(self.database_path)
        if rollback_database.exists():
            os.replace(rollback_database, self.database_path)

    def _restore_resume_rollback(
        self,
        rollback_resume: Path,
        *,
        had_resume_root: bool,
    ) -> None:
        if self.resume_root.exists():
            shutil.rmtree(self.resume_root)
        if had_resume_root and rollback_resume.exists():
            os.replace(rollback_resume, self.resume_root)


def _validate_archive_infos(infos: list[ZipInfo]) -> None:
    if len(infos) > MAX_ARCHIVE_FILES:
        raise BackupError("Backup archive contains too many files")
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise BackupError("Backup archive contains duplicate paths")
    total_size = 0
    for info in infos:
        path = PurePosixPath(info.filename)
        mode = (info.external_attr >> 16) & 0o170000
        if (
            info.is_dir()
            or not info.filename
            or "\\" in info.filename
            or path.is_absolute()
            or ".." in path.parts
            or mode == stat.S_IFLNK
        ):
            raise BackupError("Backup archive contains an unsafe path")
        if info.flag_bits & 0x1:
            raise BackupError("Encrypted backup entries are not supported")
        if not (
            info.filename in {MANIFEST_ARCHIVE_PATH, DATABASE_ARCHIVE_PATH}
            or (
                len(path.parts) == 2
                and path.parts[0] == "resumes"
                and path.name == path.parts[1]
            )
        ):
            raise BackupError("Backup archive contains an unexpected file")
        total_size += info.file_size
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise BackupError("Backup expands beyond the configured safety limit")


def _read_manifest(archive: ZipFile) -> dict[str, object]:
    info = archive.getinfo(MANIFEST_ARCHIVE_PATH)
    if info.file_size > MAX_MANIFEST_BYTES:
        raise BackupError("Backup manifest is too large")
    payload = json.loads(archive.read(info))
    if not isinstance(payload, dict):
        raise BackupError("Backup manifest is invalid")
    return payload


def _validate_manifest(
    manifest: dict[str, object],
    base_settings: Settings,
) -> tuple[dict[str, object], tuple[_ResumeEntry, ...], str]:
    schema_revision = manifest.get("schema_revision")
    if (
        manifest.get("format") != BACKUP_FORMAT
        or manifest.get("version") != BACKUP_VERSION
        or schema_revision not in SUPPORTED_SCHEMA_REVISIONS
    ):
        raise BackupError("Backup format or schema version is unsupported")
    database = manifest.get("database")
    settings_values = manifest.get("settings")
    resumes = manifest.get("resumes")
    if (
        not isinstance(database, dict)
        or database.get("path") != DATABASE_ARCHIVE_PATH
        or not isinstance(database.get("size"), int)
        or not _valid_checksum(database.get("sha256"))
        or not isinstance(settings_values, dict)
        or not isinstance(resumes, list)
    ):
        raise BackupError("Backup manifest is invalid")
    setting_names = set(settings_values)
    valid_setting_names = (
        (PORTABLE_SETTING_NAME_SET,)
        if schema_revision == SCHEMA_REVISION
        else (PORTABLE_SETTING_NAME_SET, V1_PORTABLE_SETTING_NAME_SET)
    )
    if setting_names not in valid_setting_names:
        raise BackupError("Backup settings contain missing or unsupported keys")
    try:
        validation_values = base_settings.model_dump()
        validation_values.update(settings_values)
        Settings.model_validate(validation_values)
    except ValidationError as error:
        raise BackupError("Backup settings are invalid") from error

    entries: list[_ResumeEntry] = []
    seen_references: set[str] = set()
    for item in resumes:
        if not isinstance(item, dict):
            raise BackupError("Backup resume manifest is invalid")
        reference = _safe_storage_reference(str(item.get("storage_reference", "")))
        archive_path = item.get("path")
        size = item.get("size")
        checksum = item.get("sha256")
        if (
            archive_path != f"resumes/{reference}"
            or not isinstance(size, int)
            or size < 0
            or not _valid_checksum(checksum)
            or reference in seen_references
        ):
            raise BackupError("Backup resume manifest is invalid")
        seen_references.add(reference)
        entries.append(
            _ResumeEntry(
                storage_reference=reference,
                archive_path=archive_path,
                size=size,
                checksum=checksum,
            )
        )
    return dict(settings_values), tuple(entries), str(schema_revision)


def _validate_database(
    database_path: Path,
    expected_settings: dict[str, object],
    *,
    schema_revision: str = SCHEMA_REVISION,
    required_tables: frozenset[str] = REQUIRED_DATABASE_TABLES,
) -> None:
    try:
        with sqlite3.connect(database_path) as connection:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if quick_check != ("ok",):
                raise BackupError("Backup database failed its integrity check")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if not required_tables.issubset(tables):
                raise BackupError("Backup database is missing required tables")
            revision = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            if revision != (schema_revision,):
                raise BackupError("Backup database schema version is unsupported")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise BackupError("Backup database contains broken references")
            rows = tuple(connection.execute("SELECT key, value_json FROM settings"))
            stored_settings = {
                key: _decode_sqlite_json(value_json) for key, value_json in rows
            }
            if stored_settings != expected_settings:
                raise BackupError("Backup settings do not match the database")
    except BackupError:
        raise
    except (sqlite3.DatabaseError, json.JSONDecodeError, TypeError) as error:
        raise BackupError("Backup database is invalid or unreadable") from error


def _extract_checked(
    archive: ZipFile,
    info: ZipInfo,
    destination: Path,
    *,
    expected_size: object,
    expected_checksum: object,
) -> None:
    if info.file_size != expected_size or not _valid_checksum(expected_checksum):
        raise BackupError("Backup file metadata does not match its manifest")
    digest = sha256()
    written = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as source, destination.open("wb") as target:
        while chunk := source.read(COPY_CHUNK_BYTES):
            written += len(chunk)
            if written > info.file_size:
                raise BackupError("Backup entry exceeds its declared size")
            digest.update(chunk)
            target.write(chunk)
    if written != info.file_size or digest.hexdigest() != expected_checksum:
        raise BackupError("Backup file checksum validation failed")


def _sqlite_database_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise BackupError("Backup and restore require a file-backed SQLite database")
    path = Path(url.database).expanduser().resolve()
    if path.parent == path:
        raise BackupError("Database path cannot be a filesystem root")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _sqlite_backup(source_path: Path, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(
            f"file:{source_path.as_posix()}?mode=ro",
            uri=True,
        ) as source, sqlite3.connect(destination_path) as destination:
            source.backup(destination)
    except sqlite3.DatabaseError as error:
        raise BackupError("SQLite backup could not be created") from error


def _remove_sqlite_sidecars(database_path: Path) -> None:
    Path(f"{database_path}-wal").unlink(missing_ok=True)
    Path(f"{database_path}-shm").unlink(missing_ok=True)


def _checkpoint_sqlite(database_path: Path) -> None:
    try:
        with sqlite3.connect(database_path) as connection:
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint is not None and checkpoint[0] != 0:
                raise BackupError("Backup database could not be checkpointed safely")
    except BackupError:
        raise
    except sqlite3.DatabaseError as error:
        raise BackupError("Backup database could not be checkpointed safely") from error
    _remove_sqlite_sidecars(database_path)


def _temporary_file(parent: Path, prefix: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = mkstemp(prefix=prefix, suffix=".sqlite3", dir=parent)
    os.close(descriptor)
    return Path(name)


def _safe_storage_reference(value: str) -> str:
    if (
        not value
        or Path(value).name != value
        or PurePosixPath(value).name != value
        or "\\" in value
        or len(value) > 255
    ):
        raise BackupError("Backup contains an unsafe resume storage reference")
    return value


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(COPY_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_checksum(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _decode_sqlite_json(value: object) -> object:
    # SQLite can return scalar JSON numbers directly even though strings and
    # compound values remain serialized JSON text.
    if isinstance(value, str):
        return json.loads(value)
    return value
