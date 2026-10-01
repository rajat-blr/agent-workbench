from sqlalchemy import Connection

STATEMENTS = (
    """
    CREATE TABLE run_artifacts (
        id INTEGER NOT NULL PRIMARY KEY,
        run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE,
        artifact_type VARCHAR(64) NOT NULL,
        relative_path VARCHAR NOT NULL UNIQUE,
        sha256 VARCHAR(64) NOT NULL,
        byte_size INTEGER NOT NULL,
        metadata_json JSON NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    "CREATE INDEX ix_run_artifacts_run_id ON run_artifacts (run_id)",
    "CREATE INDEX ix_run_artifacts_type ON run_artifacts (artifact_type)",
)

FINGERPRINT = "\n".join(statement.strip() for statement in STATEMENTS)


def upgrade(connection: Connection) -> None:
    for statement in STATEMENTS:
        connection.exec_driver_sql(statement)
