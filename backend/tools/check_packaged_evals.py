"""Check frozen-backend lifecycle behavior on a copied DB; optionally open an isolated QA app."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.import_t3_live import Rpc
from tools.revise_t3_prompts import ROOT, revise_t3_cases


def wait_for(check, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    raise TimeoutError("Bounded lifecycle check timed out")


def run_checks(executable: Path, database: Path, artifacts: Path, qa_app: Path | None):
    root = Path(tempfile.mkdtemp(prefix="uiagg-packaged-check-", dir="/private/tmp"))
    state = root / "state.db"
    with (
        sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source,
        sqlite3.connect(state) as target,
    ):
        source.backup(target)
    shutil.copytree(artifacts, root / "artifacts")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    token = secrets.token_hex(32)
    url = f"http://127.0.0.1:{port}"
    environment = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{state}",
        "ARTIFACT_DIRECTORY": str(root / "artifacts"),
        "EVAL_WORKTREE_DIRECTORY": str(root / "worktrees"),
        "LOCAL_AUTH_TOKEN": token,
        "PORT": str(port),
        "CODEX_COMMAND": str(ROOT / "backend/tools/fixtures/lifecycle_agent.py"),
    }
    log = (root / "backend.log").open("ab")
    backend = None
    viewer = None
    owned_agent_groups = set()
    rpc = Rpc(url, token)

    def start_backend():
        process = subprocess.Popen(
            [str(executable)],
            env=environment,
            cwd=root,
            stdout=log,
            stderr=subprocess.STDOUT,
        )

        def healthy():
            if process.poll() is not None:
                raise RuntimeError(
                    f"Frozen backend exited: {process.returncode}; see {root / 'backend.log'}"
                )
            try:
                with urllib.request.urlopen(url + "/health", timeout=1) as response:
                    return response.status == 200
            except OSError:
                return False

        wait_for(healthy)
        return process

    def running_fixture(experiment_id):
        result = rpc("eval.experiment.get", {"experiment_id": experiment_id})
        for attempt in result["attempts"]:
            if attempt["status"] != "running" or not attempt["run_id"]:
                continue
            run = rpc("run.get", {"run_id": attempt["run_id"]})
            path = Path(run["workspace_path"])
            if not path.is_relative_to(root / "worktrees"):
                raise ValueError("Fixture escaped isolated worktrees")
            ready = path / ".runtime-ready.json"
            if ready.exists():
                pids = json.loads(ready.read_text())
                if pids["parent"] != run["pid"]:
                    raise ValueError(
                        "Fixture PID does not match recorded spawned process"
                    )
                owned_agent_groups.add(pids["parent"])
                return path, pids
        return None

    record = {
        "kind": "synthetic packaged lifecycle checks, not model evaluation",
        "output_directory": str(root),
        "backend_executable": str(executable),
    }
    try:
        backend = start_backend()
        record["scope_revisions"] = revise_t3_cases(
            rpc, json.loads((ROOT / "evals/t3code/prompt-scope-v2.json").read_text())
        )
        record["historical_comparison"] = rpc(
            "eval.experiment.get", {"experiment_id": 2}
        )
        repository = root / "fixture"
        repository.mkdir()
        (repository / "README.md").write_text(
            "Synthetic lifecycle fixture, not benchmark evidence.\n"
        )
        for args in (
            ["init", "-q"],
            ["add", "README.md"],
            [
                "-c",
                "user.name=Lifecycle QA",
                "-c",
                "user.email=qa@example.test",
                "commit",
                "-qm",
                "fixture",
            ],
        ):
            subprocess.run(
                ["git", "-C", str(repository), *args], check=True, capture_output=True
            )
        workspace = rpc(
            "workspace.create",
            {"path": str(repository), "name": "Synthetic lifecycle QA"},
        )
        case = rpc(
            "eval.case.create",
            {
                "workspace_id": workspace["id"],
                "title": "Synthetic lifecycle fixture",
                "prompt": "LIFECYCLE_BLOCK: Create done.txt after the test harness releases execution.",
            },
        )
        identity = {"case_id": case["id"], "revision_id": case["latest_revision"]["id"]}
        rpc(
            "eval.case.update_draft",
            {
                **identity,
                "scorer_spec": [
                    {"type": "file", "path": "done.txt", "assertion": "exists"}
                ],
            },
        )
        assert (
            rpc("eval.case.validate", identity)["latest_revision"]["validation_status"]
            == "valid"
        )
        rpc("eval.case.publish", identity)
        suite = rpc("eval.suite.create", {"name": "Synthetic lifecycle QA"})
        suite_identity = {
            "suite_id": suite["id"],
            "version_id": suite["latest_version"]["id"],
        }
        rpc(
            "eval.suite.update_draft",
            {**suite_identity, "case_revision_ids": [identity["revision_id"]]},
        )
        rpc("eval.suite.freeze", suite_identity)
        config = rpc(
            "eval.config.capture",
            {
                "name": "Synthetic protocol fixture — NOT a model",
                "workspace_id": workspace["id"],
                "sandbox_policy": {"mode": "workspace-write", "network": False},
            },
        )

        def create(name):
            return rpc(
                "eval.experiment.create",
                {
                    "name": name,
                    "suite_version_id": suite_identity["version_id"],
                    "config_snapshot_ids": [config["snapshot"]["id"]],
                    "samples_per_case": 2,
                    "concurrency": 1,
                    "timeout_seconds": 60,
                },
            )

        cancel = create("QA cancellation fixture (synthetic)")
        rpc("eval.experiment.start", {"experiment_id": cancel["id"]})
        cancel_path, cancel_pids = wait_for(lambda: running_fixture(cancel["id"]))
        rpc("eval.experiment.cancel", {"experiment_id": cancel["id"]})
        cancelled = rpc("eval.experiment.get", {"experiment_id": cancel["id"]})
        assert cancelled["status"] == "cancelled"
        assert all(a["outcome"] == "cancelled" for a in cancelled["attempts"])
        assert sum(a["run_id"] is not None for a in cancelled["attempts"]) == 1
        assert not cancel_path.exists()
        try:
            os.kill(cancel_pids["parent"], 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("Cancelled fixture process survived")
        owned_agent_groups.discard(cancel_pids["parent"])
        record["cancellation"] = cancelled

        restart = create("QA restart/resume fixture (synthetic)")
        rpc("eval.experiment.start", {"experiment_id": restart["id"]})
        restart_path, restart_pids = wait_for(lambda: running_fixture(restart["id"]))
        backend.kill()  # Exactly the test process created above, never a PID found by name.
        backend.wait(timeout=10)
        # A hard crash cannot reap independent process groups: stop our captured fixture.
        os.killpg(restart_pids["parent"], signal.SIGKILL)
        owned_agent_groups.discard(restart_pids["parent"])
        backend = start_backend()
        interrupted = rpc("eval.experiment.get", {"experiment_id": restart["id"]})
        assert interrupted["status"] == "failed"
        assert [a["status"] for a in interrupted["attempts"]] == [
            "interrupted",
            "queued",
        ]
        assert interrupted["attempts"][0]["failure_category"] == "backend_restart"
        assert not restart_path.exists()
        record["after_restart_before_resume"] = interrupted
        rpc("eval.experiment.resume", {"experiment_id": restart["id"]})

        def completed():
            result = rpc("eval.experiment.get", {"experiment_id": restart["id"]})
            if result["status"] == "completed":
                return result
            running = running_fixture(restart["id"])
            if running:
                (running[0] / ".release").touch()
            return None

        resumed = wait_for(completed)
        assert [a["outcome"] for a in resumed["attempts"]] == [
            "infra_error",
            "pass",
            "pass",
        ]
        assert resumed["attempts"][-1]["retry_index"] == 1
        # Completed runs have been reaped; never retain their PIDs across GUI QA.
        owned_agent_groups.clear()
        record["after_explicit_resume"] = resumed

        session = rpc(
            "session.create", {"workspace_id": workspace["id"], "provider": "codex"}
        )
        chat_runs = []
        for content in ("Synthetic chat first turn", "Synthetic chat second turn"):
            sent = rpc(
                "session.send", {"session_id": session["id"], "content": content}
            )
            chat_runs.append(
                wait_for(
                    lambda run_id=sent["run_id"]: (
                        r
                        if (r := rpc("run.get", {"run_id": run_id}))["status"]
                        == "completed"
                        else None
                    )
                )
            )
        record["chat_regression"] = {
            "session_id": session["id"],
            "run_ids": [r["id"] for r in chat_runs],
            "session": rpc("session.get", {"session_id": session["id"]}),
        }
        record["interactive_experiment"] = create(
            "QA interactive cancellation (synthetic)"
        )
        record["status"] = "api_lifecycle_checks_passed"
        (root / "result.json").write_text(json.dumps(record, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": record["status"],
                    "result_path": str(root / "result.json"),
                    "interactive_experiment_id": record["interactive_experiment"]["id"],
                }
            ),
            flush=True,
        )
        if qa_app:
            viewer_environment = {
                **environment,
                "START_BACKEND": "false",
                "BACKEND_URL": url,
                "BACKEND_AUTH_TOKEN": token,
                "AGENT_WORKBENCH_USER_DATA_DIR": str(root / "profile"),
            }
            viewer = subprocess.Popen(
                [str(qa_app)],
                env=viewer_environment,
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            print(
                json.dumps(
                    {
                        "qa_app_pid": viewer.pid,
                        "ui_deadline_seconds": 600,
                        "finish_marker": str(root / "finish"),
                    }
                ),
                flush=True,
            )
            deadline = time.monotonic() + 600
            while (
                viewer.poll() is None
                and not (root / "finish").exists()
                and time.monotonic() < deadline
            ):
                time.sleep(0.5)
            record["interactive_experiment"] = rpc(
                "eval.experiment.get",
                {"experiment_id": record["interactive_experiment"]["id"]},
            )
            (root / "result.json").write_text(json.dumps(record, indent=2) + "\n")
        return record
    finally:
        if viewer and viewer.poll() is None:
            viewer.terminate()
            viewer.wait(timeout=10)
        if backend and backend.poll() is None:
            backend.terminate()
            backend.wait(timeout=10)
        for pid in owned_agent_groups:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-executable", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--qa-app", type=Path)
    args = parser.parse_args()
    run_checks(
        args.backend_executable.resolve(),
        args.database.resolve(),
        args.artifacts.resolve(),
        args.qa_app.resolve() if args.qa_app else None,
    )


if __name__ == "__main__":
    main()
