from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Connection, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from .versions import (
    V1_FINGERPRINT,
    V2_FINGERPRINT,
    V3_FINGERPRINT,
    V4_FINGERPRINT,
    V5_FINGERPRINT,
    V6_FINGERPRINT,
    V7_FINGERPRINT,
    V8_FINGERPRINT,
    upgrade_v1,
    upgrade_v2,
    upgrade_v3,
    upgrade_v4,
    upgrade_v5,
    upgrade_v6,
    upgrade_v7,
    upgrade_v8,
)


class MigrationError(RuntimeError):
    """Raised when the on-disk schema cannot be migrated safely."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    upgrade: Callable[[Connection], None]
    fingerprint: str = ""
    destructive: bool = False
    disable_foreign_keys: bool = False

    @property
    def checksum(self) -> str:
        identity = f"{self.version}:{self.name}:{self.fingerprint}".encode()
        return hashlib.sha256(identity).hexdigest()


def _default_migrations() -> tuple[Migration, ...]:
    # Version 1 is deliberately idempotent: it baselines databases created by the
    # shipped v1 app and creates the same schema for a fresh install.
    return (
        Migration(1, "v1_baseline", upgrade_v1, V1_FINGERPRINT),
        Migration(
            2,
            "run_origins_and_events",
            upgrade_v2,
            V2_FINGERPRINT,
            destructive=True,
            disable_foreign_keys=True,
        ),
        Migration(3, "run_artifacts", upgrade_v3, V3_FINGERPRINT),
        Migration(4, "eval_cases", upgrade_v4, V4_FINGERPRINT),
        Migration(5, "eval_suites_and_configs", upgrade_v5, V5_FINGERPRINT),
        Migration(6, "eval_experiments", upgrade_v6, V6_FINGERPRINT),
        Migration(7, "eval_steps", upgrade_v7, V7_FINGERPRINT),
        Migration(8, "eval_progress_events", upgrade_v8, V8_FINGERPRINT),
    )


def _database_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database:
        return None
    if url.database == ":memory:":
        return None
    return Path(url.database).expanduser().resolve()


def _backup_database(database_path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = database_path.with_name(f"{database_path.name}.{timestamp}.bak")
    try:
        with (
            sqlite3.connect(database_path) as source,
            sqlite3.connect(backup_path) as destination,
        ):
            source.backup(destination)
    except sqlite3.Error as exc:
        backup_path.unlink(missing_ok=True)
        raise MigrationError(
            f"Could not back up database before schema migration: {exc}"
        ) from exc
    return backup_path


def _validate_migrations(migrations: Sequence[Migration]) -> None:
    versions = [migration.version for migration in migrations]
    if versions != sorted(versions) or len(versions) != len(set(versions)):
        raise MigrationError("Migrations must have unique, increasing versions")
    if versions and versions[0] < 1:
        raise MigrationError("Migration versions must be positive integers")


async def run_migrations(
    engine: AsyncEngine,
    *,
    migrations: Sequence[Migration] | None = None,
    database_url: str | None = None,
) -> Path | None:
    """Apply ordered migrations and return a backup path when one was required."""

    ordered = tuple(_default_migrations() if migrations is None else migrations)
    _validate_migrations(ordered)

    async with engine.begin() as connection:
        existing_table_count = await connection.scalar(
            text(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "AND name != 'schema_migrations'"
            )
        )
        await connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, "
                "name TEXT NOT NULL, "
                "checksum TEXT NOT NULL, "
                "applied_at TEXT NOT NULL"
                ")"
            )
        )

    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT version, name, checksum "
                    "FROM schema_migrations ORDER BY version"
                )
            )
        ).all()
    applied = {row.version: (row.name, row.checksum) for row in rows}
    known = {migration.version: migration for migration in ordered}

    unknown = sorted(set(applied) - set(known))
    if unknown:
        raise MigrationError(
            "Database schema is newer than this application "
            f"(unknown migrations: {unknown})"
        )
    for version, (name, checksum) in applied.items():
        migration = known[version]
        if (name, checksum) != (migration.name, migration.checksum):
            raise MigrationError(f"Migration {version} does not match application code")

    pending = [migration for migration in ordered if migration.version not in applied]
    backup_path: Path | None = None
    if existing_table_count and any(migration.destructive for migration in pending):
        path = _database_path(database_url or str(engine.url))
        if path is None or not path.exists():
            raise MigrationError(
                "A file-backed SQLite database is required for destructive migrations"
            )
        backup_path = _backup_database(path)

    for migration in pending:
        try:
            async with engine.connect() as connection:
                if migration.disable_foreign_keys:
                    await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                    await connection.commit()
                try:
                    async with connection.begin():
                        await connection.run_sync(migration.upgrade)
                        await connection.execute(
                            text(
                                "INSERT INTO schema_migrations "
                                "(version, name, checksum, applied_at) "
                                "VALUES (:version, :name, :checksum, :applied_at)"
                            ),
                            {
                                "version": migration.version,
                                "name": migration.name,
                                "checksum": migration.checksum,
                                "applied_at": datetime.now(UTC).isoformat(),
                            },
                        )
                        if migration.disable_foreign_keys:
                            violations = (
                                await connection.exec_driver_sql(
                                    "PRAGMA foreign_key_check"
                                )
                            ).all()
                            if violations:
                                raise MigrationError(
                                    f"Migration {migration.version} produced invalid foreign keys"
                                )
                finally:
                    if migration.disable_foreign_keys:
                        if connection.in_transaction():
                            await connection.rollback()
                        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                        await connection.commit()
        except Exception as exc:
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) failed"
            ) from exc

    return backup_path
