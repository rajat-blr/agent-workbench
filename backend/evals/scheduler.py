from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_runtime import ExecutionOptions
from artifacts import ArtifactStore
from database import models
from evals.scorers import (
    CommandScorerSpec,
    DiffConstraintSpec,
    FileAssertionSpec,
    ScoreResult,
    classify_required_scores,
    score_command,
    score_diff_constraints,
    score_file_assertion,
)
from evals.worktrees import ProvisionedWorktree, WorktreeError, WorktreeService


class EvalRuntime(Protocol):
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
    ) -> None: ...
    async def wait(self, run_id: int) -> None: ...
    async def cancel(self, run_id: int) -> bool: ...


class DiffCapture(Protocol):
    async def capture(self, run_id: int, workspace_path: str): ...


class EvalScheduler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runtime: EvalRuntime,
        worktrees: WorktreeService,
        diff_service: DiffCapture | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.runtime = runtime
        self.worktrees = worktrees
        self.diff_service = diff_service
        self.artifact_store = artifact_store
        self._tasks: dict[int, asyncio.Task[None]] = {}

    async def start(self, experiment_id: int) -> None:
        task = self._tasks.get(experiment_id)
        if task and not task.done():
            raise RuntimeError("Experiment is already running")
        async with self.session_factory() as db:
            experiment = await db.get(models.EvalExperiment, experiment_id)
            if not experiment:
                raise ValueError("Eval experiment not found")
            if experiment.status != "ready":
                raise RuntimeError("Only ready experiments can be started")
            experiment.status = "running"
            experiment.started_at = datetime.now(UTC)
            await db.commit()
        self._tasks[experiment_id] = asyncio.create_task(self._run(experiment_id))

    async def cancel(self, experiment_id: int) -> None:
        async with self.session_factory() as db:
            experiment = await db.get(models.EvalExperiment, experiment_id)
            if not experiment:
                raise ValueError("Eval experiment not found")
            if experiment.status not in {"ready", "running"}:
                raise RuntimeError("Experiment is not cancellable")
            experiment.cancel_requested = True
            if experiment.status == "ready":
                now = datetime.now(UTC)
                experiment.status = "cancelled"
                experiment.completed_at = now
                await db.execute(
                    update(models.EvalAttempt)
                    .where(
                        models.EvalAttempt.experiment_id == experiment_id,
                        models.EvalAttempt.status == "queued",
                    )
                    .values(status="cancelled", outcome="cancelled", completed_at=now)
                )
            run_ids = list(
                (
                    await db.scalars(
                        select(models.EvalAttempt.run_id).where(
                            models.EvalAttempt.experiment_id == experiment_id,
                            models.EvalAttempt.status == "running",
                            models.EvalAttempt.run_id.is_not(None),
                        )
                    )
                ).all()
            )
            await db.commit()
        await asyncio.gather(
            *(self.runtime.cancel(run_id) for run_id in run_ids if run_id),
            return_exceptions=True,
        )

    async def wait(self, experiment_id: int) -> None:
        task = self._tasks.get(experiment_id)
        if task:
            await asyncio.shield(task)

    async def _run(self, experiment_id: int) -> None:
        async with self.session_factory() as db:
            experiment = await db.get(models.EvalExperiment, experiment_id)
            concurrency = experiment.concurrency if experiment else 1
            attempt_ids = list(
                (
                    await db.scalars(
                        select(models.EvalAttempt.id)
                        .where(
                            models.EvalAttempt.experiment_id == experiment_id,
                            models.EvalAttempt.status == "queued",
                        )
                        .order_by(models.EvalAttempt.id)
                    )
                ).all()
            )
        semaphore = asyncio.Semaphore(concurrency)

        async def execute(attempt_id: int) -> None:
            async with semaphore:
                await self._execute_attempt(experiment_id, attempt_id)

        try:
            await asyncio.gather(*(execute(attempt_id) for attempt_id in attempt_ids))
            async with self.session_factory() as db:
                experiment = await db.get(models.EvalExperiment, experiment_id)
                if experiment:
                    experiment.status = (
                        "cancelled" if experiment.cancel_requested else "completed"
                    )
                    experiment.completed_at = datetime.now(UTC)
                    await db.commit()
        except Exception:
            async with self.session_factory() as db:
                experiment = await db.get(models.EvalExperiment, experiment_id)
                if experiment:
                    experiment.status = "failed"
                    experiment.completed_at = datetime.now(UTC)
                    await db.commit()
            raise
        finally:
            self._tasks.pop(experiment_id, None)

    async def _execute_attempt(self, experiment_id: int, attempt_id: int) -> None:
        provisioned: ProvisionedWorktree | None = None
        run_id: int | None = None
        try:
            async with self.session_factory() as db:
                experiment = await db.get(models.EvalExperiment, experiment_id)
                attempt = await db.get(models.EvalAttempt, attempt_id)
                if not experiment or not attempt or attempt.status != "queued":
                    return
                if experiment.cancel_requested:
                    attempt.status = "cancelled"
                    attempt.outcome = "cancelled"
                    attempt.completed_at = datetime.now(UTC)
                    await db.commit()
                    return
                revision = await db.get(
                    models.EvalCaseRevision, attempt.case_revision_id
                )
                snapshot = await db.get(
                    models.EvalConfigSnapshot, attempt.config_snapshot_id
                )
                workspace = (
                    await db.get(models.Workspace, revision.workspace_id)
                    if revision
                    else None
                )
                if (
                    not revision
                    or not snapshot
                    or not workspace
                    or not revision.base_sha
                ):
                    await self._finish_invalid(
                        db, attempt, "Missing immutable attempt inputs"
                    )
                    return
                timeout_seconds = experiment.timeout_seconds
                repository_path = workspace.path
                base_sha = revision.base_sha
                prompt = revision.prompt
                setup_spec = revision.setup_spec_json
                scorer_spec = revision.scorer_spec_json
                starting_patch_artifact_id = revision.starting_patch_artifact_id
                model = snapshot.model
                reasoning = snapshot.reasoning_effort
                sandbox = snapshot.sandbox_policy_json.get("mode", "workspace-write")
                config_overrides = tuple(
                    f"{key}={json.dumps(value, separators=(',', ':'))}"
                    for key, value in sorted(snapshot.codex_config_json.items())
                    if value != "[REDACTED]"
                )

            starting_patch = None
            if starting_patch_artifact_id:
                async with self.session_factory() as db:
                    artifact = await db.get(
                        models.RunArtifact, starting_patch_artifact_id
                    )
                if not artifact or not self.artifact_store:
                    raise WorktreeError("Starting patch artifact is unavailable")
                starting_patch = await asyncio.to_thread(
                    self.artifact_store.read_bytes, artifact.relative_path
                )
            provisioned = await self.worktrees.provision(
                repository_path, base_sha, attempt_id, starting_patch=starting_patch
            )
            setup_started = time.monotonic()
            for raw in setup_spec:
                if raw.get("type") != "command" or not isinstance(
                    raw.get("argv"), list
                ):
                    raise WorktreeError("Unsupported setup step")
                result = await score_command(
                    CommandScorerSpec(
                        key=str(raw.get("key", "setup")),
                        argv=tuple(raw["argv"]),
                        timeout_seconds=float(raw.get("timeout_seconds", 120)),
                    ),
                    provisioned.path,
                )
                if result.status != "pass":
                    raise WorktreeError(f"Setup failed: {result.summary}")
            setup_ms = int((time.monotonic() - setup_started) * 1000)

            async with self.session_factory() as db:
                attempt = await db.get(models.EvalAttempt, attempt_id)
                if not attempt:
                    return
                run = models.Run(
                    kind="eval",
                    eval_attempt_id=attempt.id,
                    workspace_path=str(provisioned.path),
                    status="queued",
                    prompt=prompt,
                )
                db.add(run)
                await db.flush()
                attempt.run_id = run.id
                attempt.worktree_path = str(provisioned.path)
                attempt.status = "running"
                attempt.started_at = datetime.now(UTC)
                attempt.setup_duration_ms = setup_ms
                await db.commit()
                run_id = run.id
            if self.diff_service:
                await self.diff_service.capture(run_id, str(provisioned.path))
            execution = ExecutionOptions(
                model=model,
                reasoning_effort=reasoning,
                sandbox=sandbox
                if sandbox in {"read-only", "workspace-write"}
                else "workspace-write",
                config_overrides=config_overrides,
                timeout_seconds=timeout_seconds,
                ephemeral=True,
                ignore_user_config=True,
            )
            agent_started = time.monotonic()
            await self.runtime.start(
                None,
                run_id,
                str(provisioned.path),
                prompt,
                mode="eval",
                execution=execution,
            )
            await self.runtime.wait(run_id)
            agent_ms = int((time.monotonic() - agent_started) * 1000)

            async with self.session_factory() as db:
                run = await db.get(models.Run, run_id)
                attempt = await db.get(models.EvalAttempt, attempt_id)
                if not run or not attempt:
                    return
                attempt.agent_duration_ms = agent_ms
                if run.status == "cancelled":
                    attempt.status = "cancelled"
                    attempt.outcome = "cancelled"
                    attempt.completed_at = datetime.now(UTC)
                    await db.commit()
                    return
                if run.status != "completed":
                    attempt.status = "completed"
                    attempt.outcome = (
                        "timeout"
                        if run.error and "timeout" in run.error.lower()
                        else "infra_error"
                    )
                    attempt.failure_category = "agent_execution"
                    attempt.completed_at = datetime.now(UTC)
                    await db.commit()
                    return

            scoring_started = time.monotonic()
            changed_paths = await self.worktrees.changed_paths(provisioned)
            scores = await self._score(scorer_spec, provisioned, changed_paths)
            outcome = classify_required_scores(scores)
            async with self.session_factory() as db:
                attempt = await db.get(models.EvalAttempt, attempt_id)
                if not attempt:
                    return
                for result in scores:
                    db.add(
                        models.EvalScore(
                            attempt_id=attempt.id,
                            scorer_key=result.scorer_key,
                            required=result.required,
                            passed=result.passed,
                            value_json=result.value,
                            summary=result.summary,
                            evidence_json=result.evidence,
                        )
                    )
                attempt.status = "completed"
                attempt.outcome = outcome
                attempt.scoring_duration_ms = int(
                    (time.monotonic() - scoring_started) * 1000
                )
                attempt.completed_at = datetime.now(UTC)
                await db.commit()
        # Attempt boundaries must persist unexpected executor/scorer failures as
        # infrastructure outcomes so one bad attempt cannot strand the queue.
        except Exception as exc:  # noqa: BLE001
            async with self.session_factory() as db:
                attempt = await db.get(models.EvalAttempt, attempt_id)
                if attempt and attempt.status not in {"completed", "cancelled"}:
                    attempt.status = "completed"
                    attempt.outcome = "infra_error"
                    attempt.failure_category = str(exc)[:64]
                    attempt.completed_at = datetime.now(UTC)
                    if run_id:
                        run = await db.get(models.Run, run_id)
                        if run and run.status in {"queued", "running", "stopping"}:
                            run.status = "failed"
                            run.error = str(exc)[:2000]
                            run.completed_at = datetime.now(UTC)
                    await db.commit()
        finally:
            if provisioned:
                try:
                    await self.worktrees.cleanup(provisioned)
                except WorktreeError:
                    pass

    @staticmethod
    async def _finish_invalid(
        db: AsyncSession, attempt: models.EvalAttempt, reason: str
    ) -> None:
        attempt.status = "completed"
        attempt.outcome = "invalid_case"
        attempt.failure_category = reason[:64]
        attempt.completed_at = datetime.now(UTC)
        await db.commit()

    @staticmethod
    async def _score(
        specs: list[dict], worktree: ProvisionedWorktree, changed_paths: set[str]
    ) -> list[ScoreResult]:
        results = []
        for raw in specs:
            key = str(raw.get("key") or raw.get("type") or "scorer")
            if raw.get("type") == "command":
                results.append(
                    await score_command(
                        CommandScorerSpec(
                            key=key,
                            argv=tuple(raw.get("argv", [])),
                            timeout_seconds=float(raw.get("timeout_seconds", 120)),
                        ),
                        worktree.path,
                    )
                )
            elif raw.get("type") == "file":
                results.append(
                    score_file_assertion(
                        FileAssertionSpec(
                            key=key,
                            path=str(raw.get("path", "")),
                            assertion=raw.get("assertion", "exists"),
                            expected=raw.get("expected"),
                            json_path=raw.get("json_path"),
                        ),
                        worktree.path,
                    )
                )
            elif raw.get("type") == "diff":
                results.append(
                    score_diff_constraints(
                        DiffConstraintSpec(
                            key=key,
                            allowed=tuple(raw.get("allowed", [])),
                            forbidden=tuple(raw.get("forbidden", [])),
                            required_paths=tuple(raw.get("required_paths", [])),
                        ),
                        changed_paths,
                    )
                )
        return results


async def reconcile_interrupted_evals(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as db:
        await db.execute(
            update(models.EvalAttempt)
            .where(models.EvalAttempt.status == "running")
            .values(
                status="interrupted",
                outcome="infra_error",
                failure_category="backend_restart",
                completed_at=now,
            )
        )
        await db.execute(
            update(models.EvalExperiment)
            .where(models.EvalExperiment.status == "running")
            .values(status="failed", completed_at=now)
        )
        await db.commit()
