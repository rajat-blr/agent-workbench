from sqlalchemy import Connection

STATEMENTS = (
    """CREATE TABLE eval_suites (
        id INTEGER NOT NULL PRIMARY KEY, name VARCHAR(200) NOT NULL,
        description TEXT NOT NULL DEFAULT '', created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)""",
    """CREATE TABLE eval_suite_versions (
        id INTEGER NOT NULL PRIMARY KEY,
        suite_id INTEGER NOT NULL REFERENCES eval_suites(id) ON DELETE CASCADE,
        version INTEGER NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'draft',
        content_hash VARCHAR(64), frozen_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT eval_suite_version_status_valid CHECK (status IN ('draft', 'frozen')),
        CONSTRAINT eval_suite_frozen_fields_valid CHECK (
            status = 'draft' OR (content_hash IS NOT NULL AND frozen_at IS NOT NULL)),
        UNIQUE (suite_id, version), UNIQUE (content_hash))""",
    """CREATE TABLE eval_suite_version_cases (
        suite_version_id INTEGER NOT NULL REFERENCES eval_suite_versions(id) ON DELETE CASCADE,
        case_revision_id INTEGER NOT NULL REFERENCES eval_case_revisions(id) ON DELETE RESTRICT,
        ordinal INTEGER NOT NULL, PRIMARY KEY (suite_version_id, case_revision_id),
        UNIQUE (suite_version_id, ordinal))""",
    """CREATE TABLE eval_configs (
        id INTEGER NOT NULL PRIMARY KEY, name VARCHAR(200) NOT NULL,
        description TEXT NOT NULL DEFAULT '', created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)""",
    """CREATE TABLE eval_config_snapshots (
        id INTEGER NOT NULL PRIMARY KEY,
        config_id INTEGER NOT NULL REFERENCES eval_configs(id) ON DELETE CASCADE,
        content_hash VARCHAR(64) NOT NULL, model VARCHAR(100),
        reasoning_effort VARCHAR(32), instructions_json JSON NOT NULL,
        codex_config_json JSON NOT NULL, sandbox_policy_json JSON NOT NULL,
        cli_version VARCHAR(100), uncontrolled_inputs_json JSON NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)""",
    "CREATE INDEX ix_eval_suites_updated_at ON eval_suites (updated_at)",
    "CREATE INDEX ix_eval_suite_versions_suite_id ON eval_suite_versions (suite_id)",
    "CREATE INDEX ix_eval_suite_versions_status ON eval_suite_versions (status)",
    "CREATE INDEX ix_eval_config_snapshots_config_id ON eval_config_snapshots (config_id)",
    "CREATE INDEX ix_eval_config_snapshots_content_hash ON eval_config_snapshots (content_hash)",
)

FINGERPRINT = "\n".join(statement.strip() for statement in STATEMENTS)


def upgrade(connection: Connection) -> None:
    for statement in STATEMENTS:
        connection.exec_driver_sql(statement)
