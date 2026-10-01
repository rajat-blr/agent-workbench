from sqlalchemy import Connection

STATEMENTS = (
    """CREATE TABLE eval_steps (
        id INTEGER NOT NULL PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        source_event_start_id INTEGER NOT NULL REFERENCES run_events(id) ON DELETE CASCADE,
        source_event_end_id INTEGER NOT NULL REFERENCES run_events(id) ON DELETE CASCADE,
        source_item_id VARCHAR(120), kind VARCHAR(32) NOT NULL,
        title VARCHAR(300) NOT NULL, status VARCHAR(24) NOT NULL,
        duration_ms INTEGER, signature VARCHAR(64) NOT NULL,
        flags_json JSON NOT NULL, summary TEXT NOT NULL,
        normalizer_version INTEGER NOT NULL DEFAULT 1,
        UNIQUE (run_id, sequence))""",
    "CREATE INDEX ix_eval_steps_run_id ON eval_steps (run_id)",
)

FINGERPRINT = "\n".join(statement.strip() for statement in STATEMENTS)


def upgrade(connection: Connection) -> None:
    for statement in STATEMENTS:
        connection.exec_driver_sql(statement)
