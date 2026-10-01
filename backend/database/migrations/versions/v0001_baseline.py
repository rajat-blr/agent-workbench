from sqlalchemy import Connection

# This is the frozen schema shipped before migrations were introduced. Keep it
# independent of ORM metadata so adding future models cannot rewrite history.
STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        id INTEGER NOT NULL PRIMARY KEY,
        path VARCHAR NOT NULL UNIQUE,
        name VARCHAR(200) NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER NOT NULL PRIMARY KEY,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        provider VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL,
        title VARCHAR(200),
        codex_thread_id VARCHAR(100),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT session_status_valid CHECK (
            status IN ('idle', 'running', 'stopping', 'completed', 'failed', 'cancelled')
        ),
        CONSTRAINT session_provider_valid CHECK (provider = 'codex')
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER NOT NULL PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        status VARCHAR(32) NOT NULL,
        prompt TEXT NOT NULL,
        pid INTEGER,
        return_code INTEGER,
        error TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        started_at DATETIME,
        completed_at DATETIME,
        CONSTRAINT run_status_valid CHECK (
            status IN ('queued', 'running', 'stopping', 'completed', 'failed', 'cancelled')
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER NOT NULL PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
        role VARCHAR(20) NOT NULL,
        content TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT message_role_valid CHECK (role IN ('user', 'assistant'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_events (
        id INTEGER NOT NULL PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE,
        source_event_id VARCHAR(120),
        event_type VARCHAR(100) NOT NULL,
        payload JSON NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_diffs (
        run_id INTEGER NOT NULL PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
        workspace_path VARCHAR NOT NULL,
        repo_path VARCHAR NOT NULL,
        baseline JSON,
        result JSON NOT NULL,
        status VARCHAR(32) NOT NULL,
        reason TEXT,
        final BOOLEAN NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_sessions_workspace_id ON sessions (workspace_id)",
    "CREATE INDEX IF NOT EXISTS ix_sessions_status ON sessions (status)",
    "CREATE INDEX IF NOT EXISTS ix_sessions_updated_at ON sessions (updated_at)",
    "CREATE INDEX IF NOT EXISTS ix_runs_session_id ON runs (session_id)",
    "CREATE INDEX IF NOT EXISTS ix_runs_status ON runs (status)",
    "CREATE INDEX IF NOT EXISTS ix_messages_session_id ON messages (session_id)",
    "CREATE INDEX IF NOT EXISTS ix_messages_session_id_id ON messages (session_id, id)",
    "CREATE INDEX IF NOT EXISTS ix_session_events_session_id ON session_events (session_id)",
    "CREATE INDEX IF NOT EXISTS ix_session_events_event_type ON session_events (event_type)",
    "CREATE INDEX IF NOT EXISTS ix_session_events_session_id_id ON session_events (session_id, id)",
)

FINGERPRINT = "\n".join(statement.strip() for statement in STATEMENTS)


def upgrade(connection: Connection) -> None:
    for statement in STATEMENTS:
        connection.exec_driver_sql(statement)
