import asyncio
import json
import os
import sys
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_eval_scheduler import FakeEvalRuntime, initialize_repository

from database import Base, models
from evals.scheduler import (
    EvalScheduler,
    reconcile_eval_worktrees,
    reconcile_interrupted_evals,
)
from evals.worktrees import WorktreeService


async def catalog(tmp_path, *, setup=None, scorers=None):
    repository = tmp_path / "repository"
    repository.mkdir()
    head = await asyncio.to_thread(initialize_repository, repository)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'lifecycle.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        workspace = models.Workspace(path=str(repository), name="Lifecycle fixture")
        case = models.EvalCase(
            title="Lifecycle fixture", description="Synthetic; not model evidence"
        )
        config = models.EvalConfig(name="Fixture runtime", description="")
        suite = models.EvalSuite(name="Lifecycle", description="")
        db.add_all([workspace, case, config, suite])
        await db.flush()
        revision = models.EvalCaseRevision(
            case_id=case.id,
            revision=1,
            status="published",
            content_hash="a" * 64,
            workspace_id=workspace.id,
            base_sha=head,
            prompt="Create done.txt",
            setup_spec_json=setup or [],
            scorer_spec_json=scorers
            or [{"type": "file", "path": "done.txt", "assertion": "exists"}],
            path_policy_json={},
            validation_status="valid",
            validation_details_json={},
            published_at=datetime.now(UTC),
        )
        snapshot = models.EvalConfigSnapshot(
            config_id=config.id,
            content_hash="b" * 64,
            instructions_json=[],
            codex_config_json={},
            sandbox_policy_json={"mode": "workspace-write"},
            uncontrolled_inputs_json=[],
        )
        version = models.EvalSuiteVersion(
            suite_id=suite.id,
            version=1,
            status="frozen",
            content_hash="c" * 64,
            frozen_at=datetime.now(UTC),
        )
        db.add_all([revision, snapshot, version])
        await db.flush()
        experiment = models.EvalExperiment(
            name="Lifecycle",
            suite_version_id=version.id,
            status="ready",
            samples_per_case=2,
            concurrency=1,
            timeout_seconds=60,
        )
        db.add(experiment)
        await db.flush()
        db.add(
            models.EvalExperimentConfig(
                experiment_id=experiment.id, config_snapshot_id=snapshot.id, ordinal=0
            )
        )
        for sample in range(2):
            db.add(
                models.EvalAttempt(
                    experiment_id=experiment.id,
                    case_revision_id=revision.id,
                    config_snapshot_id=snapshot.id,
                    sample_index=sample,
                    retry_index=0,
                    status="queued",
                )
            )
        await db.commit()
    return engine, factory, repository, head, experiment.id


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["setup", "scoring"])
async def test_cancel_stops_command_descendants_and_never_launches_queued_attempt(
    tmp_path, phase
):
    ready = tmp_path / "ready.json"
    heartbeat = tmp_path / "heartbeat.txt"
    child = f"from pathlib import Path; import time\np=Path({str(heartbeat)!r})\nwhile True:\n p.write_text(str(time.monotonic())); time.sleep(.01)"
    command = (
        "import subprocess,sys,os,json,time; from pathlib import Path; "
        f"child=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"Path({str(ready)!r}).write_text(json.dumps({{'parent':os.getpid(),'child':child.pid}})); time.sleep(60)"
    )
    spec = [
        {"type": "command", "key": "blocked", "argv": [sys.executable, "-c", command]}
    ]
    engine, factory, repository, _, experiment_id = await catalog(
        tmp_path,
        setup=spec if phase == "setup" else None,
        scorers=spec if phase == "scoring" else None,
    )
    runtime = FakeEvalRuntime(factory)
    root = tmp_path / "worktrees"
    scheduler = EvalScheduler(factory, runtime, WorktreeService(root))
    try:
        await scheduler.start(experiment_id)
        async with asyncio.timeout(5):
            while not ready.exists() or not heartbeat.exists():
                await asyncio.sleep(0.01)
        pids = json.loads(ready.read_text())
        await asyncio.wait_for(scheduler.cancel(experiment_id), timeout=5)
        await scheduler.wait(experiment_id)
        async with factory() as db:
            experiment = await db.get(models.EvalExperiment, experiment_id)
            attempts = list(
                (
                    await db.scalars(
                        select(models.EvalAttempt).order_by(models.EvalAttempt.id)
                    )
                ).all()
            )
        assert experiment.status == "cancelled"
        assert [(a.status, a.outcome) for a in attempts] == [
            ("cancelled", "cancelled")
        ] * 2
        assert all(a.worktree_path is None for a in attempts)
        assert not list(root.iterdir())
        assert len(runtime.executions) == (0 if phase == "setup" else 1)
        with pytest.raises(ProcessLookupError):
            os.kill(pids["parent"], 0)
        stamp = heartbeat.read_text()
        await asyncio.sleep(0.1)
        assert heartbeat.read_text() == stamp
        assert not (repository / "done.txt").exists()
    finally:
        if experiment_id in scheduler._tasks:
            await scheduler.cancel(experiment_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_restart_cleanup_and_explicit_resume_preserve_interrupted_history(
    tmp_path,
):
    engine, factory, repository, head, experiment_id = await catalog(tmp_path)
    worktrees = WorktreeService(tmp_path / "worktrees")
    async with factory() as db:
        experiment = await db.get(models.EvalExperiment, experiment_id)
        attempt = await db.get(models.EvalAttempt, 1)
        experiment.status = "running"
        attempt.status = "running"
        provisioned = await worktrees.provision(repository, head, attempt.id)
        attempt.worktree_path = str(provisioned.path)
        await db.commit()
    await reconcile_interrupted_evals(factory)
    await reconcile_eval_worktrees(factory, worktrees)
    assert not provisioned.path.exists()
    scheduler = EvalScheduler(factory, FakeEvalRuntime(factory), worktrees)
    retries = await scheduler.resume(experiment_id)
    await scheduler.wait(experiment_id)
    async with factory() as db:
        attempts = list(
            (
                await db.scalars(
                    select(models.EvalAttempt).order_by(models.EvalAttempt.id)
                )
            ).all()
        )
        experiment = await db.get(models.EvalExperiment, experiment_id)
    assert experiment.status == "completed"
    assert attempts[0].status == "interrupted" and attempts[0].outcome == "infra_error"
    assert attempts[0].failure_category == "backend_restart"
    assert [a.outcome for a in attempts[1:]] == ["pass", "pass"]
    assert retries == [attempts[2].id] and attempts[2].retry_index == 1
    assert attempts[0].sample_index == attempts[2].sample_index == 0
    assert all(a.worktree_path is None for a in attempts)
    assert not list(worktrees.root.iterdir())
    await engine.dispose()
