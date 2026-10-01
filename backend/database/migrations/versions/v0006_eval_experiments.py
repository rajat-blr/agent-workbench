from sqlalchemy import Connection

STATEMENTS = (
    """CREATE TABLE eval_experiments (
        id INTEGER NOT NULL PRIMARY KEY, name VARCHAR(200) NOT NULL,
        suite_version_id INTEGER NOT NULL REFERENCES eval_suite_versions(id) ON DELETE RESTRICT,
        status VARCHAR(20) NOT NULL DEFAULT 'ready', samples_per_case INTEGER NOT NULL DEFAULT 1,
        concurrency INTEGER NOT NULL DEFAULT 1, timeout_seconds INTEGER NOT NULL DEFAULT 1800,
        cancel_requested BOOLEAN NOT NULL DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        started_at DATETIME, completed_at DATETIME,
        CONSTRAINT eval_experiment_status_valid CHECK (
            status IN ('ready', 'running', 'completed', 'cancelled', 'failed')))""",
    """CREATE TABLE eval_experiment_configs (
        experiment_id INTEGER NOT NULL REFERENCES eval_experiments(id) ON DELETE CASCADE,
        config_snapshot_id INTEGER NOT NULL REFERENCES eval_config_snapshots(id) ON DELETE RESTRICT,
        ordinal INTEGER NOT NULL, PRIMARY KEY (experiment_id, config_snapshot_id),
        UNIQUE (experiment_id, ordinal))""",
    """CREATE TABLE eval_attempts (
        id INTEGER NOT NULL PRIMARY KEY,
        experiment_id INTEGER NOT NULL REFERENCES eval_experiments(id) ON DELETE CASCADE,
        case_revision_id INTEGER NOT NULL REFERENCES eval_case_revisions(id) ON DELETE RESTRICT,
        config_snapshot_id INTEGER NOT NULL REFERENCES eval_config_snapshots(id) ON DELETE RESTRICT,
        sample_index INTEGER NOT NULL, retry_index INTEGER NOT NULL DEFAULT 0,
        run_id INTEGER UNIQUE REFERENCES runs(id) ON DELETE SET NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'queued', outcome VARCHAR(24),
        failure_category VARCHAR(64), worktree_path VARCHAR,
        setup_duration_ms INTEGER, agent_duration_ms INTEGER, scoring_duration_ms INTEGER,
        input_tokens INTEGER, cached_input_tokens INTEGER, output_tokens INTEGER,
        reasoning_output_tokens INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        started_at DATETIME, completed_at DATETIME,
        CONSTRAINT eval_attempt_status_valid CHECK (
            status IN ('queued', 'running', 'completed', 'cancelled', 'interrupted')),
        UNIQUE (experiment_id, case_revision_id, config_snapshot_id, sample_index, retry_index))""",
    "CREATE INDEX ix_eval_experiments_suite_version_id ON eval_experiments (suite_version_id)",
    "CREATE INDEX ix_eval_experiments_status ON eval_experiments (status)",
    "CREATE INDEX ix_eval_attempts_experiment_id ON eval_attempts (experiment_id)",
    "CREATE INDEX ix_eval_attempts_case_revision_id ON eval_attempts (case_revision_id)",
    "CREATE INDEX ix_eval_attempts_config_snapshot_id ON eval_attempts (config_snapshot_id)",
    "CREATE INDEX ix_eval_attempts_status ON eval_attempts (status)",
    """CREATE TABLE eval_scores (
        id INTEGER NOT NULL PRIMARY KEY,
        attempt_id INTEGER NOT NULL REFERENCES eval_attempts(id) ON DELETE CASCADE,
        scorer_key VARCHAR(100) NOT NULL, required BOOLEAN NOT NULL DEFAULT 1,
        passed BOOLEAN, value_json JSON NOT NULL, summary TEXT NOT NULL,
        evidence_json JSON NOT NULL, artifact_id INTEGER REFERENCES run_artifacts(id) ON DELETE SET NULL,
        UNIQUE (attempt_id, scorer_key))""",
    "CREATE INDEX ix_eval_scores_attempt_id ON eval_scores (attempt_id)",
)

FINGERPRINT = "\n".join(statement.strip() for statement in STATEMENTS)


def upgrade(connection: Connection) -> None:
    for statement in STATEMENTS:
        connection.exec_driver_sql(statement)
