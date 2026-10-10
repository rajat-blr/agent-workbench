"""Resume a bounded four-case portfolio comparison and export real UI evidence."""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from pydantic import TypeAdapter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.configuration import redact_text
from evals.safety import PREAMBLE
from evals.verifier_bundles import parse_verifier_bundle
from rpc_contract import (
    EvalAttemptDetail,
    EvalAttemptEvent,
    EvalExperiment,
    EvalScorerOutput,
    EvalStep,
)
from tools.audit_mined_inventory import inventory
from tools.eval_baselines import ROOT
from tools.local_rpc import Rpc, connection_for_process, read_chat_counts

TASKS = {
    "90269c601aae25499ee87e78a07508564825867f": (
        "Zod · Numeric enum options",
        "Fix numeric TypeScript enum handling: schema options must contain only accepted numeric values, not reverse-mapped name keys. Preserve string-enum behavior and make classic and mini APIs agree. Invalid enum names must still be rejected.",
    ),
    "7a00236683c79000dbab0d92f6faf0b7fba39f59": (
        "Zod · Preserve integer bounds",
        "Fix int/int64 format checks widening previously specified numeric bounds. Applying an integer format before or after min/max must preserve the tighter bounds, including bigint bounds. Bounds getters and emitted JSON Schema must agree; for min 0 and max 23, adding int64 must not replace those bounds with the full int64 range.",
    ),
    "28e8572cd265b4da1160ce6cd51919bb70516e2c": (
        "Hono · Empty query parameters",
        "Fix AWS API Gateway v1 and ALB request conversion dropping empty query-string values. Preserve empty strings as key=, preserve the string 0, and omit undefined values. Existing percent encoding and repeated-value handling must remain unchanged.",
    ),
    "f950277cd3d9264622785e82785f21c648da699a": (
        "Hono · Resilient pretty JSON",
        "Fix prettyJSON middleware so invalid JSON, empty bodies, consumed bodies and bodyless 204/304 responses pass through safely rather than throwing. Preserve status and headers on untouched responses. When valid JSON is reformatted, remove stale Content-Length while preserving other headers and existing pretty-print behavior.",
    ),
}
JOURNAL = ROOT / ".eval-candidates/portfolio-comparison.json"
NAME = "Zod + Hono · Low vs High reasoning"


def portable(value):
    if isinstance(value, dict):
        return {key: portable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [portable(item) for item in value]
    if isinstance(value, str):
        return (
            redact_text(re.sub(r"\x1b\[[0-9;]*m", "", value))
            .replace(str(ROOT), "/benchmark")
            .replace(str(Path.home()), "/user")
            .replace("/private/tmp/uiagg-benchmark-tools.3m1BAw", "/benchmark/tools")
        )
    return value


def export_recording(rpc, state):
    experiment = rpc("eval.experiment.get", {"experiment_id": state["experiment_id"]})
    if (
        experiment["status"] == "running"
        or len(experiment["attempts"]) != 8
        or any(row["status"] in {"queued", "running"} for row in experiment["attempts"])
    ):
        raise ValueError(
            "Export requires all eight attempts to finish; no partial showcase"
        )
    attempts = []
    artifact_audits = []
    for row in experiment["attempts"]:
        params = {"attempt_id": row["id"]}
        detail = rpc("eval.attempt.get", params)
        TypeAdapter(EvalAttemptDetail).validate_python(detail)
        with sqlite3.connect(
            Path(state["database"]).as_uri() + "?mode=ro", uri=True
        ) as database:
            for artifact in detail["artifacts"]:
                relative = database.execute(
                    "SELECT relative_path FROM run_artifacts WHERE id=?",
                    (artifact["id"],),
                ).fetchone()[0]
                path = (ROOT / "backend/artifacts" / relative).resolve()
                if not path.is_relative_to((ROOT / "backend/artifacts").resolve()):
                    raise ValueError("Artifact escaped storage")
                content = path.read_bytes()
                if (
                    hashlib.sha256(content).hexdigest() != artifact["sha256"]
                    or len(content) != artifact["byte_size"]
                ):
                    raise ValueError("Recorded artifact checksum mismatch")
                artifact_audits.append(
                    {
                        "attempt_id": row["id"],
                        "artifact_id": artifact["id"],
                        "sha256": artifact["sha256"],
                        "checksum_verified": True,
                    }
                )
        outputs = []
        for score in detail["scores"]:
            if score["artifact_id"] is None:
                continue
            output = rpc(
                "eval.attempt.artifact", {**params, "artifact_id": score["artifact_id"]}
            )
            while output["has_more"]:
                next_chunk = rpc(
                    "eval.attempt.artifact",
                    {
                        **params,
                        "artifact_id": score["artifact_id"],
                        "offset": output["next_offset"],
                    },
                )
                output = {
                    **next_chunk,
                    "offset": 0,
                    "stdout": output["stdout"] + next_chunk["stdout"],
                    "stderr": output["stderr"] + next_chunk["stderr"],
                }
            outputs.append(output)
        TypeAdapter(list[EvalScorerOutput]).validate_python(outputs)
        attempts.append(
            {
                "detail": detail,
                "events": rpc("eval.attempt.events", params),
                "steps": rpc("eval.attempt.steps", params),
                "outputs": outputs,
            }
        )
        TypeAdapter(list[EvalAttemptEvent]).validate_python(attempts[-1]["events"])
        TypeAdapter(list[EvalStep]).validate_python(attempts[-1]["steps"])
    TypeAdapter(EvalExperiment).validate_python(experiment)
    recording = portable(
        {
            "schema_version": 1,
            "kind": "recorded_real_comparison",
            "experiment": experiment,
            "cases": [
                rpc("eval.case.get", {"case_id": row["case_id"]})
                for row in state["cases"]
            ],
            "configs": [
                row
                for row in rpc("eval.config.list")
                if row["snapshot"]["id"] in state["config_snapshot_ids"]
            ],
            "suites": [
                row
                for row in rpc("eval.suite.list")
                if row["latest_version"]["id"] == state["suite_version_id"]
            ],
            "attempts": attempts,
            "artifact_audits": artifact_audits,
            "source_licenses": {
                source: (
                    ROOT / ".eval-sources" / source.lower() / "LICENSE"
                ).read_text()
                for source in ("Zod", "Hono")
            },
            "provenance": [
                {
                    key: row[key]
                    for key in (
                        "source",
                        "commit",
                        "parent",
                        "title",
                        "case_revision_id",
                        "production_paths",
                        "test_paths",
                        "verifier_sha256",
                        "reference_patch_sha256",
                        "validation_repetitions",
                    )
                }
                for row in state["cases"]
            ],
            "limitations": [
                "Four cases and one sample per configuration; not a general model ranking.",
                "Public history; model training cutoff and contamination are unverified.",
                "Both configurations use the same model; only reasoning effort differs.",
                "Recorded evidence is read-only and does not execute repository code in the demo.",
            ],
        }
    )
    destination = ROOT / "frontend/src/data/portfolioBenchmark.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(recording, indent=2) + "\n")
    state["recording_sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
    save(state)
    print(
        json.dumps(
            {
                "recording": str(destination),
                "sha256": state["recording_sha256"],
                "attempts": len(attempts),
            }
        )
    )


def save(state):
    JOURNAL.write_text(json.dumps(state, indent=2) + "\n")


def prepare(rpc, database, model):
    audited = json.loads(
        (ROOT / ".eval-candidates/validated-inventory-20261009.json").read_text()
    )
    fresh = inventory(
        [(row["source"], Path(row["path"])) for row in audited["reports"]]
    )
    entries = {row["commit"]: row for row in fresh["cases"]}
    selected = []
    for commit, (title, prompt) in TASKS.items():
        entry = entries[commit]
        payload = json.loads(Path(entry["import_payload"]).read_text())
        bundle = Path(payload["verifier_bundle_path"]).read_bytes()
        if hashlib.sha256(bundle).hexdigest() != entry["verifier_sha256"]:
            raise ValueError("Verifier evidence changed")
        selected.append((entry, payload, bundle, title, prompt))
    if JOURNAL.exists():
        state = json.loads(JOURNAL.read_text())
        if state["model"] != model or state["database"] != str(database):
            raise ValueError("Existing journal belongs to a different plan")
    else:
        if any(
            row["status"] in {"ready", "running"} or row["name"] == NAME
            for row in rpc("eval.experiment.list")
        ):
            raise ValueError(
                "Existing experiment needs inspection; refusing duplicates"
            )
        backup = (
            Path(tempfile.mkdtemp(prefix="uiagg-before-portfolio-", dir="/private/tmp"))
            / "app.db"
        )
        with (
            sqlite3.connect(database) as source,
            sqlite3.connect(backup) as destination,
        ):
            source.backup(destination)
            counts = read_chat_counts(source)
        state = {
            "database": str(database),
            "backup": str(backup),
            "model": model,
            "chat_counts_before": counts,
            "cases": [],
            "config_snapshot_ids": [],
            "experiment_id": None,
        }
        save(state)
    for entry, payload, bundle, title, prompt in selected:
        if any(row["commit"] == entry["commit"] for row in state["cases"]):
            continue
        description = f"Portfolio comparison; public history, training cutoff unverified. Source: {entry['source']}; reference commit: {entry['commit']}. Two baseline failures and two reference passes verified before model execution."
        existing = next(
            (row for row in rpc("eval.case.list") if row["description"] == description),
            None,
        )
        if existing is None:
            workspace = rpc(
                "workspace.create", {"name": title, "path": payload["repository_path"]}
            )
            existing = rpc(
                "eval.case.create",
                {
                    "title": title,
                    "description": description,
                    "workspace_id": workspace["id"],
                    "base_sha": payload["base_sha"],
                    "prompt": prompt
                    + "\n\nAllowed production files: "
                    + ", ".join(entry["production_paths"])
                    + ". Do not modify tests, dependencies or tooling.",
                },
            )
        revision = existing["latest_revision"]
        if revision["status"] == "draft":
            existing = rpc(
                "eval.case.update_draft",
                {
                    "case_id": existing["id"],
                    "revision_id": revision["id"],
                    "setup_spec": payload["setup_spec"],
                    "scorer_spec": payload["scorer_spec"],
                    "path_policy": {
                        **payload["path_policy"],
                        "portfolio_source": entry["source"],
                        "reference_commit": entry["commit"],
                    },
                    "verifier_files": [
                        {"path": path.as_posix(), "content": content.decode()}
                        for path, content in parse_verifier_bundle(bundle)
                    ],
                },
            )
            print(f"Validating {title}…", flush=True)
            existing = rpc(
                "eval.case.validate",
                {"case_id": existing["id"], "revision_id": revision["id"]},
            )
            if existing["latest_revision"]["validation_status"] != "valid":
                raise ValueError(existing["latest_revision"]["validation_details"])
            existing = rpc(
                "eval.case.publish",
                {"case_id": existing["id"], "revision_id": revision["id"]},
            )
        state["cases"].append(
            {
                **entry,
                "case_id": existing["id"],
                "case_revision_id": revision["id"],
                "title": title,
            }
        )
        save(state)
    if not state.get("suite_version_id"):
        suite = next(
            (row for row in rpc("eval.suite.list") if row["name"] == NAME), None
        ) or rpc(
            "eval.suite.create",
            {
                "name": NAME,
                "description": "Four public-history tasks; one sample per configuration; showcase only, not a model ranking.",
            },
        )
        if suite["latest_version"]["status"] != "frozen":
            suite = rpc(
                "eval.suite.update_draft",
                {
                    "suite_id": suite["id"],
                    "version_id": suite["latest_version"]["id"],
                    "case_revision_ids": [
                        row["case_revision_id"] for row in state["cases"]
                    ],
                },
            )
            suite = rpc(
                "eval.suite.freeze",
                {"suite_id": suite["id"], "version_id": suite["latest_version"]["id"]},
            )
        state["suite_version_id"] = suite["latest_version"]["id"]
        save(state)
    for effort in ["low", "high"][len(state["config_snapshot_ids"]) :]:
        config = rpc(
            "eval.config.capture",
            {
                "name": f"{model} · {effort} reasoning",
                "description": "Same model, prompt and offline policy; reasoning effort differs.",
                "model": model,
                "reasoning_effort": effort,
                "instruction_preamble": PREAMBLE,
                "sandbox_policy": {"mode": "workspace-write", "network": False},
            },
        )
        state["config_snapshot_ids"].append(config["snapshot"]["id"])
        save(state)
    if state["experiment_id"] is None:
        params = {
            "name": NAME,
            "suite_version_id": state["suite_version_id"],
            "config_snapshot_ids": state["config_snapshot_ids"],
            "samples_per_case": 1,
            "concurrency": 1,
            "timeout_seconds": 600,
        }
        preflight = rpc("eval.experiment.preflight", params)
        if (
            preflight["attempt_count"] != 8
            or preflight["invalid_case_revision_ids"]
            or preflight["network_enabled"]
        ):
            raise ValueError("Bounded comparison preflight failed")
        state["experiment_id"] = rpc("eval.experiment.create", params)["id"]
        save(state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["prepare", "start", "status", "export", "watch"]
    )
    parser.add_argument("--backend-pid", type=int, required=True)
    parser.add_argument("--model", default="gpt-6.1-sol")
    args = parser.parse_args()
    database = ROOT / "backend/agent_workbench.db"
    rpc = Rpc(*connection_for_process(args.backend_pid, database))
    state = (
        prepare(rpc, database, args.model)
        if args.action == "prepare"
        else json.loads(JOURNAL.read_text())
    )
    experiment = rpc("eval.experiment.get", {"experiment_id": state["experiment_id"]})
    if args.action == "watch":
        deadline = time.monotonic() + 5400
        previous = None
        while any(
            row["status"] in {"queued", "running"} for row in experiment["attempts"]
        ):
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "Comparison monitor expired; inspect existing run, do not duplicate it"
                )
            counts = experiment["attempt_status_counts"]
            if counts != previous:
                print(
                    json.dumps({"status": experiment["status"], "counts": counts}),
                    flush=True,
                )
                previous = counts
            time.sleep(30)
            experiment = rpc(
                "eval.experiment.get", {"experiment_id": state["experiment_id"]}
            )
        export_recording(rpc, state)
        return
    if args.action == "export":
        export_recording(rpc, state)
        return
    if args.action == "start" and experiment["status"] == "ready":
        rpc("eval.experiment.start", {"experiment_id": experiment["id"]})
        experiment = rpc("eval.experiment.get", {"experiment_id": experiment["id"]})
    print(
        json.dumps(
            {
                "experiment_id": experiment["id"],
                "status": experiment["status"],
                "counts": experiment["attempt_status_counts"],
                "attempts": [
                    {
                        "id": row["id"],
                        "case": row["case_title"],
                        "config": row["config_snapshot_id"],
                        "status": row["status"],
                        "outcome": row["outcome"],
                    }
                    for row in experiment["attempts"]
                ],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
