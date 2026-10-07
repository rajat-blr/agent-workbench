"""Import the prepared T3 suite through a confirmed running app's local API.

Credentials stay in memory. Existing chats/evals are not overwritten; a consistent
SQLite backup is made first. Baseline repositories are copied out of temporary storage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.verifier_bundles import parse_verifier_bundle
from tools.prepare_t3_evals import ROOT, audit_baseline, git


def connection_for_process(pid: int, database: Path) -> tuple[str, str]:
    files = subprocess.run(
        ["lsof", "-p", str(pid), "-Fn"], check=True, capture_output=True, text=True
    ).stdout
    if f"n{database}\n" not in files:
        raise ValueError(
            "The selected backend does not have the expected database open"
        )
    # Never print the process environment or persist its authentication token.
    environment = subprocess.run(
        ["ps", "eww", "-p", str(pid), "-o", "command="],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if str(ROOT / "backend/main.py") not in environment:
        raise ValueError("Selected process is not this source-build app backend")
    token = re.search(r"(?:^|\s)LOCAL_AUTH_TOKEN=([^\s]+)", environment)
    port = re.search(r"(?:^|\s)PORT=(\d+)(?:\s|$)", environment)
    if not token or not port:
        raise ValueError("Could not locate backend connection settings")
    return f"http://127.0.0.1:{int(port[1])}", token[1]


class Rpc:
    def __init__(self, url: str, token: str) -> None:
        self.url, self.token = url, token

    def __call__(self, method: str, params: dict | None = None):
        request = urllib.request.Request(
            self.url + "/rpc",
            data=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        with urllib.request.urlopen(request, timeout=240) as response:
            result = json.load(response)
        if "error" in result:
            raise RuntimeError(f"{method}: {result['error']['message']}")
        return result["result"]


def import_live(package: Path, database: Path, pid: int, destination: Path) -> dict:
    url, token = connection_for_process(pid, database)
    rpc = Rpc(url, token)
    rpc("health.check")
    report = json.loads((package / "report.json").read_text())
    if report["status"] != "packaged_and_scorer_verified" or report["case_count"] != 5:
        raise ValueError("A verified five-case package is required")
    evidence = Path(
        tempfile.mkdtemp(prefix="uiagg-t3-live-import-", dir="/private/tmp")
    )
    backup_fd, backup_name = tempfile.mkstemp(
        prefix=database.name + ".t3-import-", suffix=".bak", dir=database.parent
    )
    os.close(backup_fd)
    backup = Path(backup_name)
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(backup) as target:
            source.backup(target)
        chat_counts = {
            table: source.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("sessions", "messages", "runs")
        }
    print(f"Consistent backup: {backup}", flush=True)
    destination.mkdir(parents=True, exist_ok=True)
    imported = []
    for item in report["cases"]:
        slug = item["id"]
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            raise ValueError("Unsafe case identifier")
        payload = json.loads(Path(item["import_payload"]).read_text())
        repository = destination / slug
        withheld = set(item["isolation_audit"]["held_out_paths_absent"])
        audit_baseline(Path(payload["repository_path"]), withheld, payload["base_sha"])
        if not repository.exists():
            # Hard-linked immutable Git objects survive unlinking the temporary source.
            git(
                destination,
                "-c",
                "core.logAllRefUpdates=false",
                "clone",
                "--local",
                "--quiet",
                payload["repository_path"],
                str(repository),
            )
            git(repository, "remote", "remove", "origin")
        audit_baseline(repository, withheld, payload["base_sha"])
        bundle = Path(payload["verifier_bundle_path"]).read_bytes()
        if hashlib.sha256(bundle).hexdigest() != payload["verifier_bundle_sha256"]:
            raise ValueError("Verifier checksum changed")
        workspace = next(
            (w for w in rpc("workspace.list") if w["path"] == str(repository)), None
        )
        if not workspace:
            workspace = rpc(
                "workspace.create", {"path": str(repository), "name": payload["title"]}
            )
        case = next(
            (
                c
                for c in rpc("eval.case.list")
                if c["title"] == payload["title"]
                and c["latest_revision"]["workspace_id"] == workspace["id"]
            ),
            None,
        )
        if not case:
            case = rpc(
                "eval.case.create",
                {
                    "workspace_id": workspace["id"],
                    "title": payload["title"],
                    "description": payload["description"],
                    "prompt": payload["prompt"],
                    "base_sha": payload["base_sha"],
                },
            )
        identity = {"case_id": case["id"], "revision_id": case["latest_revision"]["id"]}
        revision = case["latest_revision"]
        if revision["status"] == "published":
            if (
                revision["base_sha"] != payload["base_sha"]
                or revision["prompt"] != payload["prompt"]
                or revision["scorer_spec"] != payload["scorer_spec"]
                or revision["setup_spec"] != payload["setup_spec"]
            ):
                raise ValueError(
                    "Existing published case differs; refusing to overwrite it"
                )
        else:
            print(f"Validating {slug} in the live app", flush=True)
            rpc(
                "eval.case.update_draft",
                {
                    **identity,
                    "setup_spec": payload["setup_spec"],
                    "scorer_spec": payload["scorer_spec"],
                    "path_policy": payload["path_policy"],
                    "verifier_files": [
                        {"path": path.as_posix(), "content": content.decode()}
                        for path, content in parse_verifier_bundle(bundle)
                    ],
                },
            )
            validated = rpc("eval.case.validate", identity)
            revision = validated["latest_revision"]
            if revision["validation_status"] != "valid":
                raise RuntimeError(
                    f"Validation failed: {revision['validation_details']}"
                )
            case = rpc("eval.case.publish", identity)
        imported.append({"id": slug, **identity, "repository_path": str(repository)})
        print(f"Available: {payload['title']}", flush=True)
    name = "T3 Code realistic regressions"
    revision_ids = [case["revision_id"] for case in imported]
    suite = next(
        (
            s
            for s in rpc("eval.suite.list")
            if s["name"] == name
            and [c["revision_id"] for c in s["latest_version"]["cases"]] == revision_ids
        ),
        None,
    )
    if not suite:
        suite = rpc(
            "eval.suite.create",
            {
                "name": name,
                "description": "Five external T3 regression cases with separate held-out verifiers.",
            },
        )
        identity = {
            "suite_id": suite["id"],
            "version_id": suite["latest_version"]["id"],
        }
        rpc("eval.suite.update_draft", {**identity, "case_revision_ids": revision_ids})
        suite = rpc("eval.suite.freeze", identity)
    visible = rpc("eval.case.list")
    assert all(
        any(
            case["id"] == item["case_id"]
            and case["latest_revision"]["status"] == "published"
            for case in visible
        )
        for item in imported
    )
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
        after = {
            table: source.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in chat_counts
        }
    if after != chat_counts:
        raise RuntimeError(
            "Chat counts changed during import; inspect the backup before continuing"
        )
    result = {
        "status": "imported_into_active_ui_backend",
        "database_path": str(database),
        "backup_path": str(backup),
        "chat_counts_before": chat_counts,
        "chat_counts_after": after,
        "cases": imported,
        "suite_id": suite["id"],
        "suite_version_id": suite["latest_version"]["id"],
        "suite_status": suite["latest_version"]["status"],
        "agent_runs_started": 0,
    }
    (evidence / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backend-pid", type=int, required=True)
    parser.add_argument("--destination", type=Path, default=ROOT / ".eval-cases/t3code")
    args = parser.parse_args()
    result = import_live(
        args.package.resolve(),
        args.database.resolve(),
        args.backend_pid,
        args.destination.resolve(),
    )
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
