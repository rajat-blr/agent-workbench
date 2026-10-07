"""Import prepared T3 cases into a NEW isolated app database, never the live app."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def import_cases(package: Path, state: Path) -> dict:
    if "database.database" in sys.modules or "settings" in sys.modules:
        raise RuntimeError(
            "Import must run in a fresh process, before app settings are loaded"
        )
    # Must precede database/settings imports; the live configured database is out of scope.
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{state / 'state.db'}"
    os.environ["ARTIFACT_DIRECTORY"] = str(state / "artifacts")
    os.environ["EVAL_WORKTREE_DIRECTORY"] = str(state / "worktrees")
    from artifacts import ArtifactStore
    from database import SessionLocal, engine, models
    from database.migrations.runner import run_migrations
    from evals.service import EvalService
    from evals.verifier_bundles import parse_verifier_bundle
    from evals.worktrees import WorktreeService
    from tools.prepare_t3_evals import audit_baseline

    report = json.loads((package / "report.json").read_text())
    if report["status"] != "packaged_and_scorer_verified" or report["case_count"] != 5:
        raise ValueError("A fully verified five-case package is required")
    await run_migrations(engine, database_url=os.environ["DATABASE_URL"])
    service = EvalService(
        WorktreeService(state / "worktrees"),
        artifact_store=ArtifactStore(state / "artifacts"),
    )
    imported = []
    try:
        async with SessionLocal() as db:
            for item in report["cases"]:
                print(f"Importing and validating {item['id']}", flush=True)
                payload = json.loads(Path(item["import_payload"]).read_text())
                repository = Path(payload["repository_path"])
                audit_baseline(
                    repository,
                    set(item["isolation_audit"]["held_out_paths_absent"]),
                    payload["base_sha"],
                )
                bundle = Path(payload["verifier_bundle_path"]).read_bytes()
                if (
                    hashlib.sha256(bundle).hexdigest()
                    != payload["verifier_bundle_sha256"]
                ):
                    raise ValueError("Verifier checksum changed after packaging")
                workspace = models.Workspace(
                    path=str(repository), name=payload["title"]
                )
                db.add(workspace)
                await db.commit()
                await db.refresh(workspace)
                case = await service.dispatch(
                    "eval.case.create",
                    {
                        "workspace_id": workspace.id,
                        "title": payload["title"],
                        "description": payload["description"],
                        "prompt": payload["prompt"],
                        "base_sha": payload["base_sha"],
                    },
                    db,
                )
                identity = {
                    "case_id": case["id"],
                    "revision_id": case["latest_revision"]["id"],
                }
                await service.dispatch(
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
                    db,
                )
                validated = await service.dispatch("eval.case.validate", identity, db)
                revision = validated["latest_revision"]
                if revision["validation_status"] != "valid":
                    raise RuntimeError(
                        f"Case validation failed: {revision['validation_details']}"
                    )
                published = await service.dispatch("eval.case.publish", identity, db)
                imported.append(
                    {
                        "id": item["id"],
                        **identity,
                        "content_hash": published["latest_revision"]["content_hash"],
                        "validation": revision["validation_details"],
                    }
                )
                print(f"Published {item['id']}", flush=True)
            suite = await service.dispatch(
                "eval.suite.create",
                {
                    "name": "T3 Code realistic regressions",
                    "description": "Five external regression cases; prepared baselines and held-out tests.",
                },
                db,
            )
            suite_identity = {
                "suite_id": suite["id"],
                "version_id": suite["latest_version"]["id"],
            }
            await service.dispatch(
                "eval.suite.update_draft",
                {
                    **suite_identity,
                    "case_revision_ids": [case["revision_id"] for case in imported],
                },
                db,
            )
            frozen = await service.dispatch("eval.suite.freeze", suite_identity, db)
        result = {
            "status": "imported_published_frozen",
            "package": str(package),
            "state_directory": str(state),
            "database_url": os.environ["DATABASE_URL"],
            "artifact_directory": str(state / "artifacts"),
            "eval_worktree_directory": str(state / "worktrees"),
            "agent_runs": 0,
            "cases": imported,
            "suite": frozen,
        }
        if list((state / "worktrees").glob("attempt-*")):
            raise RuntimeError("Validation worktrees were not cleaned up")
        (state / "import-report.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    arguments = parser.parse_args()
    state = Path(tempfile.mkdtemp(prefix="uiagg-t3-app-", dir="/private/tmp"))
    print(f"Isolated app state: {state}", flush=True)
    result = asyncio.run(import_cases(arguments.package.resolve(), state))
    print(f"Import report: {result['state_directory']}/import-report.json", flush=True)


if __name__ == "__main__":
    main()
