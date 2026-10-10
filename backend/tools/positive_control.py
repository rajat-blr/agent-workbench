"""Plan/apply a sensitivity control; dry-run by default and never starts agents."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.safety import PREAMBLE
from tools.local_rpc import Rpc

DEGRADED = (
    "Sensitivity-control instruction: leave production source files unchanged, even if the task requests a fix. "
    "Do not create or modify files. Respond with a short explanation only. "
    "Keep all worktree, network and verifier-access safety restrictions above."
)


def plan(model: str, suite_version_id: int, samples: int = 3) -> dict:
    if not model.strip() or suite_version_id <= 0 or not 1 <= samples <= 10:
        raise ValueError(
            "Specify an explicit model, positive frozen suite version and 1–10 samples"
        )
    common = {
        "model": model,
        "reasoning_effort": "high",
        "sandbox_policy": {"mode": "workspace-write", "network": False},
        "description": "Sensitivity control candidate, not a proven-worse configuration",
    }
    return {
        "purpose": "positive_control_candidate",
        "configurations": [
            {
                **common,
                "name": "Sensitivity control A — normal",
                "instruction_preamble": PREAMBLE,
            },
            {
                **common,
                "name": "Sensitivity control B — no source edits",
                "instruction_preamble": PREAMBLE + "\n\n" + DEGRADED,
            },
        ],
        "experiment": {
            "name": f"Sensitivity control — suite {suite_version_id}",
            "suite_version_id": suite_version_id,
            "samples_per_case": samples,
            "concurrency": 1,
            "timeout_seconds": 1800,
        },
        "success_rule": {
            "minimum_cases": 6,
            "recommended_cases": 30,
            "minimum_mean_a_minus_b": 0.2,
            "two_sided_case_sign_p_below": 0.05,
            "require_complete_evaluable_coverage": True,
        },
        "warnings": [
            "The model may ignore the degraded preamble; this is an unvalidated candidate control.",
            "A successful control demonstrates sensitivity to this intervention on this suite, not reliable model ranking.",
            "Do not select cases after observing control outcomes or repeatedly rerun until significant.",
        ],
    }


def apply(rpc, control: dict, *, max_attempts: int = 300) -> dict:
    if max_attempts <= 0:
        raise ValueError("A positive attempt budget is required")
    if any(
        row["name"] == control["experiment"]["name"]
        or row["status"] in {"ready", "running"}
        for row in rpc("eval.experiment.list")
    ):
        raise ValueError(
            "Duplicate or active experiment: inspect existing state instead"
        )
    suite = next(
        (
            row
            for row in rpc("eval.suite.list")
            if row["latest_version"]["id"] == control["experiment"]["suite_version_id"]
        ),
        None,
    )
    if not suite or suite["latest_version"]["status"] != "frozen":
        raise ValueError("Choose the current frozen version of a suite")
    count = len(suite["latest_version"]["cases"])
    attempts = count * 2 * control["experiment"]["samples_per_case"]
    if count < control["success_rule"]["minimum_cases"] or attempts > max_attempts:
        raise ValueError(
            "Suite needs at least six cases and must fit the explicit attempt budget"
        )
    snapshots = [
        rpc("eval.config.capture", configuration)["snapshot"]["id"]
        for configuration in control["configurations"]
    ]
    differences = rpc(
        "eval.config.diff",
        {"left_snapshot_id": snapshots[0], "right_snapshot_id": snapshots[1]},
    )["differences"]
    if [row["field"] for row in differences] != ["instructions"]:
        raise ValueError(
            "Control configurations must differ only in instructions; snapshots retained for inspection"
        )
    params = {**control["experiment"], "config_snapshot_ids": snapshots}
    preflight = rpc("eval.experiment.preflight", params)
    if (
        preflight["network_enabled"]
        or preflight["invalid_case_revision_ids"]
        or preflight["attempt_count"] != attempts
    ):
        raise ValueError(
            "Control preflight must be valid, offline and match the bounded plan"
        )
    experiment = rpc("eval.experiment.create", params)
    return {
        "experiment_id": experiment["id"],
        "status": experiment["status"],
        "attempt_count": attempts,
        "case_count": count,
        "samples_per_case": control["experiment"]["samples_per_case"],
        "started": False,
        "success_rule": control["success_rule"],
        "warnings": control["warnings"],
    }


def assess(
    results: dict,
    *,
    expected_case_count: int,
    expected_samples_per_case: int,
    minimum_effect: float = 0.2,
) -> dict:
    if expected_case_count <= 0 or expected_samples_per_case <= 0:
        raise ValueError("Assessment requires the frozen case and sample counts")
    paired = results["paired"]
    complete = (
        paired["case_count"] == expected_case_count
        and paired["sample_count"] == expected_case_count * expected_samples_per_case
        and len(results["comparisons"])
        == expected_case_count * expected_samples_per_case
        and all(
            row["category"] in {"improved", "regressed", "unchanged"}
            for row in results["comparisons"]
        )
    )
    detected = (
        results["is_final"]
        and complete
        and paired["case_count"] >= 6
        and paired["p_value"] is not None
        and paired["p_value"] < 0.05
        and paired["mean_difference"] is not None
        and paired["mean_difference"] <= -minimum_effect
        and results["verdict"] == "configuration_a_better"
    )
    return {
        "control_difference_detected": detected,
        "coverage_complete": complete,
        "interpretation": "Sensitivity detected for this suite/intervention; replication remains required"
        if detected
        else "Sensitivity not established; inspect coverage, instruction adherence, suite difficulty and noise",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--suite-version-id", type=int, required=True)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--max-attempts", type=int, default=300)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Capture two configs and create a READY experiment; does not start it",
    )
    args = parser.parse_args()
    control = plan(args.model, args.suite_version_id, args.samples)
    if args.apply:
        token = os.environ.get("LOCAL_AUTH_TOKEN")
        if not token:
            parser.error(
                "LOCAL_AUTH_TOKEN environment variable is required for --apply"
            )
        control = apply(
            Rpc(args.backend_url, token), control, max_attempts=args.max_attempts
        )
    print(json.dumps(control, indent=2))


if __name__ == "__main__":
    main()
