import gzip
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from tools.audit_eval_experiment import audit_result


def fixture(tmp_path, monkeypatch, *, checksum=None, relative="trace.gz"):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    content = gzip.compress(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "git diff --check",
                    "exit_code": 0,
                },
            }
        ).encode()
        + b"\n"
    )
    (artifacts / "trace.gz").write_bytes(content)
    database = tmp_path / "state.db"
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE run_artifacts (id INTEGER, relative_path TEXT);
            CREATE TABLE eval_attempts (id INTEGER, worktree_path TEXT, run_id INTEGER, case_revision_id INTEGER);
            CREATE TABLE runs (id INTEGER, workspace_path TEXT);
            CREATE TABLE eval_case_revisions (id INTEGER, workspace_id INTEGER, base_sha TEXT);
            CREATE TABLE workspaces (id INTEGER, path TEXT);
        """)
        db.execute("INSERT INTO run_artifacts VALUES (1,?)", (relative,))
        db.execute("INSERT INTO eval_attempts VALUES (1,NULL,1,1)")
        db.execute(
            "INSERT INTO runs VALUES (1,?)", (str(tmp_path / "removed-worktree"),)
        )
        db.execute("INSERT INTO eval_case_revisions VALUES (1,1,'pinned')")
        db.execute("INSERT INTO workspaces VALUES (1,?)", (str(tmp_path / "baseline"),))
    manifest = tmp_path / "cases.json"
    manifest.write_text(
        json.dumps(
            {"cases": [{"case_revision_id": 1, "production_paths": ["cache.ts"]}]}
        )
    )
    record = {
        "attempts": [
            {
                "id": 1,
                "case_revision_id": 1,
                "case": {"title": "Example regression"},
                "diff": {"files": [{"path": "cache.ts"}]},
                "artifacts": [
                    {
                        "id": 1,
                        "type": "raw_jsonl",
                        "byte_size": len(content),
                        "sha256": checksum or hashlib.sha256(content).hexdigest(),
                    }
                ],
            }
        ]
    }

    def git(argv, **kwargs):
        if "rev-parse" in argv:
            return SimpleNamespace(stdout="pinned\n")
        if "status" in argv:
            return SimpleNamespace(stdout="")
        return SimpleNamespace(
            stdout=f"worktree {tmp_path / 'baseline'}\nHEAD pinned\n"
        )

    monkeypatch.setattr("tools.audit_eval_experiment.subprocess.run", git)
    return record, database, artifacts, manifest


def test_audit_verifies_trace_and_cleanup(tmp_path, monkeypatch):
    result = audit_result(*fixture(tmp_path, monkeypatch))["attempts"][0]
    assert result["artifacts"][0]["checksum_verified"]
    assert result["artifacts"][0]["raw_event_count"] == 1
    assert result["commands"] == [{"command": "git diff --check", "exit_code": 0}]
    for flag in (
        "baseline_clean",
        "baseline_sha_matches",
        "worktree_removed",
        "attempt_worktree_path_cleared",
        "changed_paths_within_scope",
        "baseline_worktree_registration_clean",
    ):
        assert result[flag]


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"checksum": "tampered"}, "checksum/size mismatch"),
        ({"relative": "../../outside.gz"}, "escapes its root"),
    ],
)
def test_audit_rejects_tampering_and_path_escape(
    tmp_path, monkeypatch, kwargs, message
):
    with pytest.raises(ValueError, match=message):
        audit_result(*fixture(tmp_path, monkeypatch, **kwargs))
