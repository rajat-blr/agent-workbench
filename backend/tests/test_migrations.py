import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from database.migrations import Migration, MigrationError, run_migrations


def _create_v1_database(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE workspaces (
                id INTEGER PRIMARY KEY,
                path VARCHAR NOT NULL UNIQUE,
                name VARCHAR(200) NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY,
                workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                provider VARCHAR(32) NOT NULL,
                status VARCHAR(32) NOT NULL,
                title VARCHAR(200),
                codex_thread_id VARCHAR(100),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                status VARCHAR(32) NOT NULL,
                prompt TEXT NOT NULL,
                pid INTEGER,
                return_code INTEGER,
                error TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                started_at DATETIME,
                completed_at DATETIME
            );
            CREATE TABLE session_events (
                id INTEGER PRIMARY KEY,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE,
                source_event_id VARCHAR(120),
                event_type VARCHAR(100) NOT NULL,
                payload JSON NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            CREATE TABLE run_diffs (
                run_id INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
                workspace_path VARCHAR NOT NULL,
                repo_path VARCHAR NOT NULL,
                baseline JSON,
                result JSON NOT NULL,
                status VARCHAR(32) NOT NULL,
                reason TEXT,
                final BOOLEAN NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            INSERT INTO workspaces (id, path, name)
            VALUES (1, '/tmp/existing-project', 'Existing project');
            INSERT INTO sessions (id, workspace_id, provider, status, title)
            VALUES (1, 1, 'codex', 'completed', 'Preserved session');
            INSERT INTO runs (id, session_id, status, prompt)
            VALUES (1, 1, 'completed', 'Preserved prompt');
            INSERT INTO session_events (
                id, session_id, run_id, event_type, payload
            ) VALUES (1, 1, 1, 'session.completed', '{"return_code": 0}');
            INSERT INTO messages (id, session_id, run_id, role, content)
            VALUES (1, 1, 1, 'user', 'Preserved prompt');
            INSERT INTO run_diffs (
                run_id, workspace_path, repo_path, result, status, final
            ) VALUES (
                1, '/tmp/existing-project', '/tmp/existing-project', '{}', 'ready', 1
            );
            """
        )


@pytest.mark.asyncio
async def test_v1_database_is_baselined_without_losing_data(tmp_path) -> None:
    database_path = tmp_path / "v1.db"
    _create_v1_database(database_path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")

    await run_migrations(engine)
    await run_migrations(engine)

    async with engine.connect() as connection:
        workspace = (
            await connection.execute(
                text("SELECT path, name FROM workspaces WHERE id = 1")
            )
        ).one()
        session_title = await connection.scalar(
            text("SELECT title FROM sessions WHERE id = 1")
        )
        migrations = (
            await connection.execute(
                text("SELECT version, name FROM schema_migrations")
            )
        ).all()
        run = (
            await connection.execute(
                text(
                    "SELECT kind, session_id, eval_attempt_id, workspace_path, prompt "
                    "FROM runs WHERE id = 1"
                )
            )
        ).one()
        event = (
            await connection.execute(
                text("SELECT id, run_id, session_id FROM run_events WHERE id = 1")
            )
        ).one()
        message_run_id = await connection.scalar(
            text("SELECT run_id FROM messages WHERE id = 1")
        )
        diff_status = await connection.scalar(
            text("SELECT status FROM run_diffs WHERE run_id = 1")
        )
        tables = {
            row[0]
            for row in (
                await connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table'")
                )
            )
        }

    assert workspace == ("/tmp/existing-project", "Existing project")
    assert session_title == "Preserved session"
    assert migrations == [
        (1, "v1_baseline"),
        (2, "run_origins_and_events"),
        (3, "run_artifacts"),
        (4, "eval_cases"),
        (5, "eval_suites_and_configs"),
        (6, "eval_experiments"),
        (7, "eval_steps"),
        (8, "eval_progress_events"),
    ]
    assert run == (
        "chat",
        1,
        None,
        "/tmp/existing-project",
        "Preserved prompt",
    )
    assert event == (1, 1, 1)
    assert message_run_id == 1
    assert diff_status == "ready"
    assert {
        "runs",
        "messages",
        "run_events",
        "run_diffs",
        "run_artifacts",
        "eval_cases",
        "eval_case_revisions",
        "eval_suites",
        "eval_suite_versions",
        "eval_suite_version_cases",
        "eval_configs",
        "eval_config_snapshots",
        "eval_experiments",
        "eval_experiment_configs",
        "eval_attempts",
        "eval_scores",
        "eval_steps",
        "eval_experiment_events",
    } <= tables
    assert "session_events" not in tables
    await engine.dispose()


@pytest.mark.asyncio
async def test_migrations_are_ordered_idempotent_and_transactional(tmp_path) -> None:
    database_path = tmp_path / "ordered.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")

    def first(connection) -> None:
        connection.execute(text("CREATE TABLE example (id INTEGER PRIMARY KEY)"))

    def failing(connection) -> None:
        connection.execute(text("INSERT INTO example (id) VALUES (1)"))
        raise RuntimeError("stop")

    migrations = (
        Migration(1, "create_example", first),
        Migration(2, "failing_change", failing),
    )
    with pytest.raises(MigrationError, match="failing_change"):
        await run_migrations(engine, migrations=migrations)

    async with engine.connect() as connection:
        applied = (
            (
                await connection.execute(
                    text("SELECT version FROM schema_migrations ORDER BY version")
                )
            )
            .scalars()
            .all()
        )
        example_rows = await connection.scalar(text("SELECT COUNT(*) FROM example"))
    assert applied == [1]
    assert example_rows == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_destructive_migration_creates_backup(tmp_path) -> None:
    database_path = tmp_path / "backup.db"
    _create_v1_database(database_path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")

    def destructive(connection) -> None:
        connection.execute(text("ALTER TABLE workspaces ADD COLUMN note TEXT"))

    backup_path = await run_migrations(
        engine,
        migrations=(Migration(1, "add_note", destructive, destructive=True),),
    )

    assert backup_path is not None and backup_path.exists()
    with sqlite3.connect(backup_path) as backup:
        assert backup.execute(
            "SELECT name FROM workspaces WHERE id = 1"
        ).fetchone() == ("Existing project",)
        columns = backup.execute("PRAGMA table_info(workspaces)").fetchall()
    assert "note" not in {column[1] for column in columns}
    await engine.dispose()
