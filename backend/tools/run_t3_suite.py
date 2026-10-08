"""Run one bounded, paired T3 suite experiment through the active app API."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.import_t3_live import Rpc, connection_for_process

NAME = "T3 five-case comparison — medium vs high"
PREAMBLE = (
    "Work only within this attempt's disposable worktree. Do not read other repositories, "
    "sibling directories, evaluation data, held-out verifiers, or home-directory user data. "
    "Do not fetch upstream solutions, use network services, or delegate to other agents. "
    "Follow repository AGENTS.md safety instructions. Dependencies are already installed. "
    "Use focused local checks, not repository-wide checks or browsers. "
    "Only production source changes necessary for the current task may remain changed. "
    "Do not modify tooling, dependencies, instructions, or existing test files. "
    "Held-out tests are intentionally absent and will be installed after the run; "
    "do not recreate their paths. Scratch files must not remain in the scored diff."
)


def validate_plan(preflight: dict, differences: list[dict]) -> None:
    if (
        preflight["case_count"] != 5
        or preflight["attempt_count"] != 10
        or preflight["invalid_case_revision_ids"]
        or preflight["network_enabled"]
    ):
        raise RuntimeError(
            "Expected exactly ten valid offline attempts across five cases"
        )
    if [d["field"] for d in differences] != ["reasoning_effort"]:
        raise RuntimeError("Configurations must differ only in reasoning effort")


def select_existing_configs(catalog: list[dict], snapshot_ids: list[int], model: str):
    selected = []
    if len(snapshot_ids) != 2 or len(set(snapshot_ids)) != 2:
        raise RuntimeError("Expected two distinct existing configuration snapshots")
    for snapshot_id, effort in zip(snapshot_ids, ("medium", "high"), strict=True):
        config = next((c for c in catalog if c["snapshot"]["id"] == snapshot_id), None)
        if config is None:
            raise RuntimeError("Existing configuration snapshot not found")
        snapshot = config["snapshot"]
        if (
            snapshot["model"] != model
            or snapshot["reasoning_effort"] != effort
            or snapshot["sandbox_policy"].get("mode") != "workspace-write"
            or snapshot["sandbox_policy"].get("network") is not False
        ):
            raise RuntimeError(
                "Existing snapshot does not match the approved offline plan"
            )
        selected.append(config)
    return selected


def run_suite(
    database: Path,
    pid: int,
    model: str,
    *,
    suite_version: int | None = None,
    existing_snapshot_ids: list[int] | None = None,
) -> dict:
    url, token = connection_for_process(pid, database)
    rpc = Rpc(url, token)
    name = (
        NAME
        if suite_version is None
        else f"T3 v{suite_version} five-case comparison — medium vs high"
    )
    experiments = rpc("eval.experiment.list")
    if any(e["name"] == name for e in experiments):
        raise RuntimeError("Comparison already exists; inspect it instead of rerunning")
    if any(e.get("status") in {"ready", "running"} for e in experiments):
        raise RuntimeError("Another experiment is active; refusing overlapping runs")
    cases = rpc("eval.case.list")
    expected = {
        f"T3 Code: {slug}"
        for slug in (
            "trimmed-ids",
            "worker-recovery",
            "cache-pruning",
            "concurrent-settings",
            "indexeddb-recovery",
        )
    }
    selected = [c for c in cases if c["title"] in expected]
    if len(selected) != 5 or any(
        c["latest_revision"]["status"] != "published" for c in selected
    ):
        raise RuntimeError("Expected all five published T3 cases")
    revision_ids = {c["latest_revision"]["id"] for c in selected}
    suites = rpc("eval.suite.list")
    suite = next(
        (
            s
            for s in suites
            if s["latest_version"]["status"] == "frozen"
            and (
                suite_version is None or s["latest_version"]["version"] == suite_version
            )
            and {c["revision_id"] for c in s["latest_version"]["cases"]} == revision_ids
        ),
        None,
    )
    if suite is None:
        raise RuntimeError(
            "Expected a frozen suite containing exactly the five T3 revisions"
        )
    configs = (
        select_existing_configs(rpc("eval.config.list"), existing_snapshot_ids, model)
        if existing_snapshot_ids is not None
        else []
    )
    for effort in () if existing_snapshot_ids is not None else ("medium", "high"):
        configs.append(
            rpc(
                "eval.config.capture",
                {
                    "workspace_id": selected[0]["latest_revision"]["workspace_id"],
                    "name": f"T3 suite — pinned model, {effort}",
                    "description": "Identical suite scope guard; only reasoning effort differs.",
                    "model": model,
                    "reasoning_effort": effort,
                    "instruction_preamble": PREAMBLE,
                    "sandbox_policy": {"mode": "workspace-write", "network": False},
                },
            )
        )
    snapshot_ids = [c["snapshot"]["id"] for c in configs]
    differences = rpc(
        "eval.config.diff",
        {
            "left_snapshot_id": snapshot_ids[0],
            "right_snapshot_id": snapshot_ids[1],
        },
    )["differences"]
    params = {
        "name": name,
        "suite_version_id": suite["latest_version"]["id"],
        "config_snapshot_ids": snapshot_ids,
        "samples_per_case": 1,
        "concurrency": 1,
        "timeout_seconds": 600,
    }
    preflight = rpc("eval.experiment.preflight", params)
    validate_plan(preflight, differences)
    experiment = rpc("eval.experiment.create", params)
    output = Path(tempfile.mkdtemp(prefix="uiagg-t3-comparison-", dir="/private/tmp"))
    record = {
        "experiment_id": experiment["id"],
        "configurations": configs,
        "configuration_differences": differences,
        "preflight": preflight,
        "plan": params,
        "output_directory": str(output),
    }
    (output / "plan.json").write_text(json.dumps(record, indent=2) + "\n")
    print(
        json.dumps(
            {
                "experiment_id": experiment["id"],
                "attempt_count": 10,
                "output_directory": str(output),
            }
        ),
        flush=True,
    )
    rpc("eval.experiment.start", {"experiment_id": experiment["id"]})
    deadline = time.monotonic() + 8400
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
            raise RuntimeError("Outer deadline exceeded; cancellation requested")
        time.sleep(5)
    record.update(
        {
            "experiment": experiment,
            "attempts": [
                rpc("eval.attempt.get", {"attempt_id": a["id"]})
                for a in experiment["attempts"]
            ],
        }
    )
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(
        json.dumps(
            {"status": experiment["status"], "result_path": str(output / "result.json")}
        ),
        flush=True,
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--backend-pid", required=True, type=int)
    parser.add_argument("--model", required=True)
    parser.add_argument("--suite-version", type=int)
    parser.add_argument("--existing-snapshot-ids", type=int, nargs=2)
    args = parser.parse_args()
    run_suite(
        args.database.resolve(),
        args.backend_pid,
        args.model,
        suite_version=args.suite_version,
        existing_snapshot_ids=args.existing_snapshot_ids,
    )


if __name__ == "__main__":
    main()
