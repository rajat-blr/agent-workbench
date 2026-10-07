from sqlalchemy import Connection

STATEMENTS = (
    """CREATE TABLE eval_experiment_events (
        id INTEGER NOT NULL PRIMARY KEY,
        experiment_id INTEGER NOT NULL REFERENCES eval_experiments(id) ON DELETE CASCADE,
        event_type VARCHAR(100) NOT NULL, payload JSON NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)""",
    "CREATE INDEX ix_eval_experiment_events_experiment_id ON eval_experiment_events (experiment_id)",
)

FINGERPRINT = "\n".join(statement.strip() for statement in STATEMENTS)


def upgrade(connection: Connection) -> None:
    for statement in STATEMENTS:
        connection.exec_driver_sql(statement)
