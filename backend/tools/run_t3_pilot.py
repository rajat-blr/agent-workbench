"""Run exactly one T3 cache-pruning attempt through the active app API."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.import_t3_live import Rpc, connection_for_process


def run_pilot(database: Path, pid: int, model: str) -> dict:
    url, token = connection_for_process(pid, database)
    rpc = Rpc(url, token)
    cases = rpc("eval.case.list")
    case = next(
        c
        for c in cases
        if c["title"] == "T3 Code: cache-pruning"
        and c["latest_revision"]["status"] == "published"
    )
    revision = case["latest_revision"]
    prior = [
        e for e in rpc("eval.experiment.list") if e["name"] == "T3 cache-pruning pilot"
    ]
    if prior:
        raise RuntimeError(
            "A pilot already exists; inspect it instead of silently running again"
        )
    preamble = (
        "Work only within this attempt's disposable worktree. Do not read other repositories, "
        "sibling directories, evaluation data, held-out verifiers, or home-directory user data. "
        "Do not fetch upstream solutions, use network services, or delegate to other agents. "
        "Follow repository AGENTS.md safety instructions. Dependencies are already installed. "
        "Use focused local checks, not repository-wide checks or browsers. "
        "Only apps/server/src/pullRequest/PullRequestReadCache.ts may remain changed. "
        "Do not modify tooling, dependencies, instructions, or existing test files. "
        "Held-out tests are intentionally absent and will be installed after the run; "
        "do not recreate their paths. Scratch files must not remain in the scored diff."
    )
    config = rpc(
        "eval.config.capture",
        {
            "workspace_id": revision["workspace_id"],
            "name": "T3 pilot — pinned model, medium",
            "description": "One-case smoke pilot; no comparison or statistical claim.",
            "model": model,
            "reasoning_effort": "medium",
            "instruction_preamble": preamble,
            "sandbox_policy": {"mode": "workspace-write", "network": False},
        },
    )
    suite = rpc(
        "eval.suite.create",
        {
            "name": "T3 cache-pruning pilot suite",
            "description": "Single-case pilot; original five-case suite unchanged.",
        },
    )
    identity = {"suite_id": suite["id"], "version_id": suite["latest_version"]["id"]}
    rpc("eval.suite.update_draft", {**identity, "case_revision_ids": [revision["id"]]})
    suite = rpc("eval.suite.freeze", identity)
    params = {
        "name": "T3 cache-pruning pilot",
        "suite_version_id": identity["version_id"],
        "config_snapshot_ids": [config["snapshot"]["id"]],
        "samples_per_case": 1,
        "concurrency": 1,
        "timeout_seconds": 600,
    }
    preflight = rpc("eval.experiment.preflight", params)
    if (
        preflight["attempt_count"] != 1
        or preflight["invalid_case_revision_ids"]
        or preflight["network_enabled"]
    ):
        raise RuntimeError(
            "Pilot preflight did not establish one valid offline attempt"
        )
    experiment = rpc("eval.experiment.create", params)
    output = Path(tempfile.mkdtemp(prefix="uiagg-t3-pilot-", dir="/private/tmp"))
    record = {
        "experiment_id": experiment["id"],
        "case_id": case["id"],
        "case_revision_id": revision["id"],
        "configuration": {
            "id": config["id"],
            "snapshot_id": config["snapshot"]["id"],
            "model": model,
            "reasoning_effort": "medium",
            "cli_version": config["snapshot"]["cli_version"],
            "content_hash": config["snapshot"]["content_hash"],
        },
        "preflight": preflight,
        "output_directory": str(output),
    }
    (output / "plan.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2), flush=True)
    rpc("eval.experiment.start", {"experiment_id": experiment["id"]})
    deadline = time.monotonic() + 900
    last = None
    while True:
        experiment = rpc("eval.experiment.get", {"experiment_id": experiment["id"]})
        state = (experiment["status"], experiment["attempt_status_counts"])
        if state != last:
            print(json.dumps({"status": state[0], "attempts": state[1]}), flush=True)
            last = state
        if experiment["status"] not in {"running", "ready"}:
            break
        if time.monotonic() > deadline:
            rpc("eval.experiment.cancel", {"experiment_id": experiment["id"]})
            raise RuntimeError(
                "Pilot exceeded the outer monitoring deadline; cancellation requested"
            )
        time.sleep(5)
    attempt = rpc("eval.attempt.get", {"attempt_id": experiment["attempts"][0]["id"]})
    record.update({"experiment": experiment, "attempt": attempt})
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": experiment["status"],
                "outcome": attempt["outcome"],
                "attempt_id": attempt["id"],
                "run_id": attempt["run_id"],
                "result_path": str(output / "result.json"),
            }
        ),
        flush=True,
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--backend-pid", required=True, type=int)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    run_pilot(args.database.resolve(), args.backend_pid, args.model)


if __name__ == "__main__":
    main()
