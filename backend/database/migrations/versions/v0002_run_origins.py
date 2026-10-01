from sqlalchemy import Connection

STATEMENTS = (
    """
    CREATE TABLE runs_v2 (
        id INTEGER NOT NULL PRIMARY KEY,
        kind VARCHAR(16) NOT NULL DEFAULT 'chat',
        session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
        eval_attempt_id INTEGER,
        workspace_path VARCHAR NOT NULL,
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
        ),
        CONSTRAINT run_kind_valid CHECK (kind IN ('chat', 'eval')),
        CONSTRAINT run_origin_valid CHECK (
            (kind = 'chat' AND session_id IS NOT NULL AND eval_attempt_id IS NULL)
            OR
            (kind = 'eval' AND session_id IS NULL AND eval_attempt_id IS NOT NULL)
        )
    )
    """,
    """
    INSERT INTO runs_v2 (
        id, kind, session_id, eval_attempt_id, workspace_path, status, prompt,
        pid, return_code, error, created_at, started_at, completed_at
    )
    SELECT
        runs.id, 'chat', runs.session_id, NULL, workspaces.path, runs.status,
        runs.prompt, runs.pid, runs.return_code, runs.error, runs.created_at,
        runs.started_at, runs.completed_at
    FROM runs
    JOIN sessions ON sessions.id = runs.session_id
    JOIN workspaces ON workspaces.id = sessions.workspace_id
    """,
    "DROP TABLE runs",
    "ALTER TABLE runs_v2 RENAME TO runs",
    "CREATE INDEX ix_runs_session_id ON runs (session_id)",
    "CREATE UNIQUE INDEX ix_runs_eval_attempt_id ON runs (eval_attempt_id)",
    "CREATE INDEX ix_runs_status ON runs (status)",
    """
    CREATE TABLE run_events (
        id INTEGER NOT NULL PRIMARY KEY,
        run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE,
        session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
        source_event_id VARCHAR(120),
        event_type VARCHAR(100) NOT NULL,
        payload JSON NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT run_event_origin_valid CHECK (
            run_id IS NOT NULL OR session_id IS NOT NULL
        )
    )
    """,
    """
    INSERT INTO run_events (
        id, run_id, session_id, source_event_id, event_type, payload, created_at
    )
    SELECT id, run_id, session_id, source_event_id, event_type, payload, created_at
    FROM session_events
    """,
    "DROP TABLE session_events",
    "CREATE INDEX ix_run_events_run_id ON run_events (run_id)",
    "CREATE INDEX ix_run_events_run_id_id ON run_events (run_id, id)",
    "CREATE INDEX ix_run_events_session_id ON run_events (session_id)",
    "CREATE INDEX ix_run_events_session_id_id ON run_events (session_id, id)",
    "CREATE INDEX ix_run_events_event_type ON run_events (event_type)",
)

FINGERPRINT = "\n".join(statement.strip() for statement in STATEMENTS)


def upgrade(connection: Connection) -> None:
    for statement in STATEMENTS:
        connection.exec_driver_sql(statement)
