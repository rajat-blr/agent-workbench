"""Read-only evidence audit of a finished evaluation comparison (no agent reruns)."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path


def audit_result(record: dict, database: Path, artifacts: Path, manifest: Path) -> dict:
    cases = {
        c["case_revision_id"]: c for c in json.loads(manifest.read_text())["cases"]
    }
    audits = []
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        for attempt in record["attempts"]:
            slug = attempt["case_revision_id"]
            commands = []
            artifact_audits = []
            for artifact in attempt["artifacts"]:
                row = db.execute(
                    "SELECT relative_path FROM run_artifacts WHERE id=?",
                    (artifact["id"],),
                ).fetchone()
                path = (artifacts / row[0]).resolve()
                if not path.is_relative_to(artifacts.resolve()):
                    raise ValueError("Artifact escapes its root")
                content = path.read_bytes()
                verified = (
                    hashlib.sha256(content).hexdigest() == artifact["sha256"]
                    and len(content) == artifact["byte_size"]
                )
                if not verified:
                    raise ValueError("Artifact checksum/size mismatch")
                item = {
                    "id": artifact["id"],
                    "type": artifact["type"],
                    "sha256": artifact["sha256"],
                    "checksum_verified": verified,
                }
                if artifact["type"] == "raw_jsonl":
                    events = [
                        json.loads(line)
                        for line in gzip.decompress(content).splitlines()
                    ]
                    item["raw_event_count"] = len(events)
                    for event in events:
                        node = event.get("item", {})
                        if (
                            event.get("type") == "item.completed"
                            and node.get("type") == "command_execution"
                        ):
                            commands.append(
                                {
                                    "command": node.get("command"),
                                    "exit_code": node.get("exit_code"),
                                }
                            )
                artifact_audits.append(item)
            row = db.execute(
                "SELECT a.worktree_path,r.workspace_path,w.path,cr.base_sha "
                "FROM eval_attempts a JOIN runs r ON r.id=a.run_id "
                "JOIN eval_case_revisions cr ON cr.id=a.case_revision_id "
                "JOIN workspaces w ON w.id=cr.workspace_id WHERE a.id=?",
                (attempt["id"],),
            ).fetchone()
            pointer, worktree, repository, base_sha = row

            def git(*args, repository=repository):
                return subprocess.run(
                    ["git", "-C", repository, *args],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

            files = [f["path"] for f in (attempt["diff"] or {}).get("files", [])]
            audits.append(
                {
                    "attempt_id": attempt["id"],
                    "case": slug,
                    "artifacts": artifact_audits,
                    "commands": commands,
                    "worktree_path": worktree,
                    "worktree_removed": not Path(worktree).exists(),
                    "attempt_worktree_path_cleared": pointer is None,
                    "baseline_sha": base_sha,
                    "baseline_sha_matches": git("rev-parse", "HEAD") == base_sha,
                    "baseline_clean": not git("status", "--porcelain"),
                    "baseline_worktree_registration_clean": len(
                        git("worktree", "list", "--porcelain").split("worktree ")
                    )
                    == 2,
                    "changed_paths": files,
                    "changed_paths_within_scope": all(
                        p in cases[slug]["production_paths"] for p in files
                    ),
                }
            )
    return {
        "attempts": audits,
        "command_scope_review": "Pending human/agent review; checksums do not establish secrecy.",
        "ui_result_visual_verification": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    record = json.loads(args.result.read_text())
    audit = audit_result(record, args.database.resolve(), args.artifacts, args.manifest)
    destination = args.result.parent / "audit.json"
    destination.write_text(json.dumps(audit, indent=2) + "\n")
    print(
        json.dumps(
            {"audit_path": str(destination), "attempt_count": len(audit["attempts"])}
        )
    )


if __name__ == "__main__":
    main()
