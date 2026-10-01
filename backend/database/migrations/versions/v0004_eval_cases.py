from sqlalchemy import Connection

STATEMENTS = (
    """
    CREATE TABLE eval_cases (
        id INTEGER NOT NULL PRIMARY KEY,
        title VARCHAR(200) NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE eval_case_revisions (
        id INTEGER NOT NULL PRIMARY KEY,
        case_id INTEGER NOT NULL REFERENCES eval_cases(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'draft',
        content_hash VARCHAR(64),
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
        source_run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
        base_sha VARCHAR(64),
        prompt TEXT NOT NULL,
        setup_spec_json JSON NOT NULL,
        scorer_spec_json JSON NOT NULL,
        path_policy_json JSON NOT NULL,
        starting_patch_artifact_id INTEGER REFERENCES run_artifacts(id) ON DELETE SET NULL,
        verifier_artifact_id INTEGER REFERENCES run_artifacts(id) ON DELETE SET NULL,
        validation_status VARCHAR(24) NOT NULL DEFAULT 'not_validated',
        validation_details_json JSON NOT NULL,
        published_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        CONSTRAINT eval_case_revision_status_valid CHECK (status IN ('draft', 'published')),
        CONSTRAINT eval_case_validation_status_valid CHECK (
            validation_status IN ('not_validated', 'valid', 'invalid')
        ),
        CONSTRAINT eval_case_published_fields_valid CHECK (
            status = 'draft'
            OR (
                content_hash IS NOT NULL
                AND base_sha IS NOT NULL
                AND published_at IS NOT NULL
                AND validation_status = 'valid'
            )
        ),
        UNIQUE (case_id, revision),
        UNIQUE (content_hash)
    )
    """,
    "CREATE INDEX ix_eval_cases_updated_at ON eval_cases (updated_at)",
    "CREATE INDEX ix_eval_case_revisions_case_id ON eval_case_revisions (case_id)",
    "CREATE INDEX ix_eval_case_revisions_workspace_id ON eval_case_revisions (workspace_id)",
    "CREATE INDEX ix_eval_case_revisions_source_run_id ON eval_case_revisions (source_run_id)",
    "CREATE INDEX ix_eval_case_revisions_status ON eval_case_revisions (status)",
)

FINGERPRINT = "\n".join(statement.strip() for statement in STATEMENTS)


def upgrade(connection: Connection) -> None:
    for statement in STATEMENTS:
        connection.exec_driver_sql(statement)
