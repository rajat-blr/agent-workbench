import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import Base, models
from evals.scheduler import EvalScheduler, reconcile_interrupted_evals
from evals.service import EvalService
from evals.worktrees import WorktreeService


def initialize_repository(path) -> str:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "scheduler@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Scheduler Test"], check=True
    )
    (path / "README.md").write_text("fixture\n")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-q", "-m", "fixture"], check=True
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class FakeEvalRuntime:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        self.executions = []

    async def start(
        self,
        session_id,
        run_id,
        workspace_path,
        prompt,
        thread_id=None,
        *,
        mode="chat",
        execution=None,
    ) -> None:
        self.executions.append(execution)
        (Path(workspace_path) / "done.txt").write_text("complete\n")
        async with self.session_factory() as db:
            run = await db.get(models.Run, run_id)
            run.status = "completed"
            run.started_at = datetime.now(UTC)
            run.completed_at = datetime.now(UTC)
            run.return_code = 0
            db.add_all(
                [
                    models.RunEvent(
                        run_id=run_id,
                        source_event_id="cmd-1",
                        event_type="codex.item.started",
                        payload={
                            "item": {
                                "id": "cmd-1",
                                "type": "command_execution",
                                "command": "create marker",
                            }
                        },
                    ),
                    models.RunEvent(
                        run_id=run_id,
                        source_event_id="cmd-1",
                        event_type="codex.item.completed",
                        payload={
                            "item": {
                                "id": "cmd-1",
                                "type": "command_execution",
                                "command": "create marker",
                                "exit_code": 0,
                            }
                        },
                    ),
                ]
            )
            await db.commit()

    async def wait(self, run_id: int) -> None:
        return None

    async def cancel(self, run_id: int) -> bool:
        return True


@pytest.mark.asyncio
async def test_scheduler_executes_scores_and_cleans_worktree(tmp_path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    head = await asyncio.to_thread(initialize_repository, repository)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scheduler.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        workspace = models.Workspace(path=str(repository), name="Fixture")
        case = models.EvalCase(title="Create marker", description="")
        config = models.EvalConfig(name="Candidate", description="")
        suite = models.EvalSuite(name="Core", description="")
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
            setup_spec_json=[],
            scorer_spec_json=[
                {
                    "type": "file",
                    "key": "marker",
                    "path": "done.txt",
                    "assertion": "exists",
                }
            ],
            path_policy_json={},
            validation_status="valid",
            validation_details_json={},
            published_at=datetime.now(UTC),
        )
        snapshot = models.EvalConfigSnapshot(
            config_id=config.id,
            content_hash="b" * 64,
            model="test-model",
            reasoning_effort="high",
            instructions_json=[],
            codex_config_json={},
            sandbox_policy_json={"mode": "workspace-write"},
            cli_version="test",
            uncontrolled_inputs_json=[],
        )
        suite_version = models.EvalSuiteVersion(
            suite_id=suite.id,
            version=1,
            status="frozen",
            content_hash="c" * 64,
            frozen_at=datetime.now(UTC),
        )
        db.add_all([revision, snapshot, suite_version])
        await db.flush()
        experiment = models.EvalExperiment(
            name="Run",
            suite_version_id=suite_version.id,
            status="ready",
            samples_per_case=1,
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
        attempt = models.EvalAttempt(
            experiment_id=experiment.id,
            case_revision_id=revision.id,
            config_snapshot_id=snapshot.id,
            sample_index=0,
            retry_index=0,
            status="queued",
        )
        db.add(attempt)
        await db.commit()
        experiment_id = experiment.id
        attempt_id = attempt.id

    worktree_root = tmp_path / "worktrees"
    runtime = FakeEvalRuntime(session_factory)
    scheduler = EvalScheduler(session_factory, runtime, WorktreeService(worktree_root))
    await scheduler.start(experiment_id)
    await scheduler.wait(experiment_id)

    async with session_factory() as db:
        experiment = await db.get(models.EvalExperiment, experiment_id)
        attempt = await db.get(models.EvalAttempt, attempt_id)
        scores = list((await db.execute(select(models.EvalScore))).scalars())
        detail = await EvalService(WorktreeService(worktree_root)).dispatch(
            "eval.attempt.get", {"attempt_id": attempt_id}, db
        )
        service = EvalService(WorktreeService(worktree_root))
        steps = await service.dispatch(
            "eval.attempt.steps", {"attempt_id": attempt_id}, db
        )
        events = await service.dispatch(
            "eval.attempt.events", {"attempt_id": attempt_id}, db
        )
    assert experiment and experiment.status == "completed"
    assert attempt and attempt.status == "completed" and attempt.outcome == "pass"
    assert scores[0].scorer_key == "marker" and scores[0].passed is True
    assert detail["case"]["title"] == "Create marker"
    assert detail["scores"][0]["summary"] == "File assertion exists passed"
    assert detail["configuration"]["model"] == "test-model"
    assert steps[0]["kind"] == "command" and steps[0]["status"] == "pass"
    assert [event["type"] for event in events] == [
        "codex.item.started",
        "codex.item.completed",
    ]
    assert runtime.executions[0].model == "test-model"
    assert runtime.executions[0].ephemeral is True
    assert not list(worktree_root.glob("attempt-*"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_restart_reconciliation_marks_running_eval_interrupted(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'restart.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with engine.connect() as connection:
        # Foreign-key-complete catalog data is unnecessary for this crash fixture.
        await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await connection.execute(
            text(
                "INSERT INTO eval_experiments "
                "(id, name, suite_version_id, status, samples_per_case, concurrency, "
                "timeout_seconds, cancel_requested) VALUES "
                "(1, 'Interrupted', 1, 'running', 1, 1, 60, 0)"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO eval_attempts (id, experiment_id, case_revision_id, config_snapshot_id, sample_index, retry_index, status) VALUES (1, 1, 1, 1, 0, 0, 'running')"
            )
        )
        await connection.commit()
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.commit()
    await reconcile_interrupted_evals(session_factory)
    async with session_factory() as db:
        experiment = await db.get(models.EvalExperiment, 1)
        attempt = await db.get(models.EvalAttempt, 1)
    assert experiment and experiment.status == "failed"
    assert attempt and attempt.status == "interrupted"
    assert attempt.failure_category == "backend_restart"
    await engine.dispose()
