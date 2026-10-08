from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_runtime import ExecutionOptions
from artifacts import ArtifactStore
from database import models
from evals.configuration import controlled_execution
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
from evals.statistics import token_usage
from evals.verifier_bundles import materialize_verifier_bundle
from evals.worktrees import ProvisionedWorktree, WorktreeError, WorktreeService
from event_broker import EvalProgressEvent, EventBroker


def _phase_time() -> float:
    # Match asyncio deadlines. On macOS, uvloop's clock includes system sleep
    # while Python's time.monotonic() does not. Never mix their clock domains.
    return asyncio.get_running_loop().time()


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
        event_broker: EventBroker | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.runtime = runtime
        self.worktrees = worktrees
        self.diff_service = diff_service
        self.artifact_store = artifact_store
        self.event_broker = event_broker
        self._tasks: dict[int, asyncio.Task[None]] = {}

    async def _emit(self, experiment_id: int, event_type: str, payload: dict) -> None:
        async with self.session_factory() as db:
            stored = models.EvalExperimentEvent(
                experiment_id=experiment_id,
                event_type=event_type,
                payload=payload,
            )
            db.add(stored)
            await db.commit()
            await db.refresh(stored)
        if self.event_broker:
            self.event_broker.publish_experiment(
                EvalProgressEvent(
                    experiment_id=experiment_id,
                    type=event_type,
                    payload=payload,
                    sequence=stored.id,
                    created_at=stored.created_at.isoformat(),
                )
            )

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
            experiment.completed_at = None
            experiment.cancel_requested = False
            await db.commit()
        await self._emit(
            experiment_id, "eval.experiment.started", {"status": "running"}
        )
        self._tasks[experiment_id] = asyncio.create_task(self._run(experiment_id))

    async def resume(self, experiment_id: int) -> list[int]:
        async with self.session_factory() as db:
            experiment = await db.get(models.EvalExperiment, experiment_id)
            if not experiment:
                raise ValueError("Eval experiment not found")
            if experiment.status != "failed":
                raise RuntimeError("Only failed experiments can be resumed")
            interrupted = list(
                (
                    await db.scalars(
                        select(models.EvalAttempt).where(
                            models.EvalAttempt.experiment_id == experiment_id,
                            models.EvalAttempt.status == "interrupted",
                        )
                    )
                ).all()
            )
            if not interrupted:
                raise RuntimeError("Experiment has no interrupted attempts to resume")
            retries = []
            for attempt in interrupted:
                retry_index = (
                    await db.scalar(
                        select(func.max(models.EvalAttempt.retry_index)).where(
                            models.EvalAttempt.experiment_id == experiment_id,
                            models.EvalAttempt.case_revision_id
                            == attempt.case_revision_id,
                            models.EvalAttempt.config_snapshot_id
                            == attempt.config_snapshot_id,
                            models.EvalAttempt.sample_index == attempt.sample_index,
                        )
                    )
                    or 0
                ) + 1
                retry = models.EvalAttempt(
                    experiment_id=experiment_id,
                    case_revision_id=attempt.case_revision_id,
                    config_snapshot_id=attempt.config_snapshot_id,
                    sample_index=attempt.sample_index,
                    retry_index=retry_index,
                    status="queued",
                )
                db.add(retry)
                await db.flush()
                retries.append(retry.id)
            experiment.status = "ready"
            experiment.cancel_requested = False
            experiment.completed_at = None
            await db.commit()
        await self._emit(
            experiment_id, "eval.experiment.resumed", {"attempt_ids": retries}
        )
        await self.start(experiment_id)
        return retries

    async def retry_attempt(self, attempt_id: int) -> int:
        async with self.session_factory() as db:
            attempt = await db.get(models.EvalAttempt, attempt_id)
            if not attempt:
                raise ValueError("Eval attempt not found")
            if attempt.status not in {"completed", "cancelled", "interrupted"}:
                raise RuntimeError("Only terminal attempts can be retried")
            experiment = await db.get(models.EvalExperiment, attempt.experiment_id)
            if not experiment or experiment.status == "running":
                raise RuntimeError(
                    "Attempt cannot be retried while its experiment runs"
                )
            retry_index = (
                await db.scalar(
                    select(func.max(models.EvalAttempt.retry_index)).where(
                        models.EvalAttempt.experiment_id == attempt.experiment_id,
                        models.EvalAttempt.case_revision_id == attempt.case_revision_id,
                        models.EvalAttempt.config_snapshot_id
                        == attempt.config_snapshot_id,
                        models.EvalAttempt.sample_index == attempt.sample_index,
                    )
                )
                or 0
            ) + 1
            retry = models.EvalAttempt(
                experiment_id=attempt.experiment_id,
                case_revision_id=attempt.case_revision_id,
                config_snapshot_id=attempt.config_snapshot_id,
                sample_index=attempt.sample_index,
                retry_index=retry_index,
                status="queued",
            )
            db.add(retry)
            await db.flush()
            retry_id = retry.id
            experiment.status = "ready"
            experiment.cancel_requested = False
            experiment.completed_at = None
            experiment_id = experiment.id
            await db.commit()
        await self._emit(
            experiment_id,
            "eval.attempt.retry_queued",
            {"attempt_id": retry_id, "retried_attempt_id": attempt_id},
        )
        await self.start(experiment_id)
        return retry_id

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
        await self._emit(
            experiment_id,
            "eval.experiment.cancel_requested",
            {"status": "cancelling"},
        )
        await asyncio.gather(
            *(self.runtime.cancel(run_id) for run_id in run_ids if run_id),
            return_exceptions=True,
        )
        task = self._tasks.get(experiment_id)
        if task and not task.done():
            # Setup/scorers run outside the agent runtime. Cancelling their task
            # lets score_command terminate its process group before cleanup.
            if not task.cancelling():
                task.cancel()
            await asyncio.shield(task)

    async def wait(self, experiment_id: int) -> None:
        task = self._tasks.get(experiment_id)
        if task:
            await asyncio.shield(task)

    async def _run(self, experiment_id: int) -> None:
        final_status = "failed"
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

        attempt_tasks = [
            asyncio.create_task(execute(attempt_id)) for attempt_id in attempt_ids
        ]
        try:
            await asyncio.gather(*attempt_tasks)
            async with self.session_factory() as db:
                experiment = await db.get(models.EvalExperiment, experiment_id)
                if experiment:
                    experiment.status = (
                        "cancelled" if experiment.cancel_requested else "completed"
                    )
                    experiment.completed_at = datetime.now(UTC)
                    await db.commit()
                    final_status = experiment.status
            await self._emit(
                experiment_id,
                "eval.experiment.completed",
                {"status": final_status},
            )
        except asyncio.CancelledError:
            # gather can report one cancelled child before its siblings finish
            # their finally blocks. Join every cleanup before terminal status.
            await asyncio.gather(*attempt_tasks, return_exceptions=True)
            async with self.session_factory() as db:
                experiment = await db.get(models.EvalExperiment, experiment_id)
                if not experiment or not experiment.cancel_requested:
                    raise
                now = datetime.now(UTC)
                await db.execute(
                    update(models.EvalAttempt)
                    .where(
                        models.EvalAttempt.experiment_id == experiment_id,
                        models.EvalAttempt.status.in_(["queued", "running"]),
                    )
                    .values(status="cancelled", outcome="cancelled", completed_at=now)
                )
                experiment.status = "cancelled"
                experiment.completed_at = now
                await db.commit()
            await self._emit(
                experiment_id, "eval.experiment.completed", {"status": "cancelled"}
            )
        except Exception:
            async with self.session_factory() as db:
                experiment = await db.get(models.EvalExperiment, experiment_id)
                if experiment:
                    experiment.status = "failed"
                    experiment.completed_at = datetime.now(UTC)
                    await db.commit()
            await self._emit(
                experiment_id, "eval.experiment.failed", {"status": "failed"}
            )
            raise
        finally:
            self._tasks.pop(experiment_id, None)

    async def _execute_attempt(self, experiment_id: int, attempt_id: int) -> None:
        provisioned: ProvisionedWorktree | None = None
        run_id: int | None = None
        start_task: asyncio.Task | None = None
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
                verifier_artifact_id = revision.verifier_artifact_id
                model = snapshot.model
                reasoning = snapshot.reasoning_effort
                sandbox, preamble, config_overrides = controlled_execution(
                    snapshot.instructions_json,
                    snapshot.codex_config_json,
                    snapshot.sandbox_policy_json,
                )
                if preamble:
                    prompt = f"{preamble}\n\n--- Task ---\n\n{prompt}"

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
            setup_started = _phase_time()
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
            setup_ms = int((_phase_time() - setup_started) * 1000)

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
            await self._emit(
                experiment_id,
                "eval.attempt.status_changed",
                {"attempt_id": attempt_id, "run_id": run_id, "status": "running"},
            )
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
            agent_started = _phase_time()
            start_task = asyncio.create_task(
                self.runtime.start(
                    None,
                    run_id,
                    str(provisioned.path),
                    prompt,
                    mode="eval",
                    execution=execution,
                )
            )
            # Finish process registration before cancellation tries to stop it.
            await asyncio.shield(start_task)
            await self.runtime.wait(run_id)
            agent_ms = int((_phase_time() - agent_started) * 1000)

            async with self.session_factory() as db:
                run = await db.get(models.Run, run_id)
                attempt = await db.get(models.EvalAttempt, attempt_id)
                if not run or not attempt:
                    return
                attempt.agent_duration_ms = agent_ms
                payloads = list(
                    await db.scalars(
                        select(models.RunEvent.payload).where(
                            models.RunEvent.run_id == run_id,
                            models.RunEvent.event_type == "codex.turn.completed",
                        )
                    )
                )
                for field, value in token_usage(payloads).items():
                    setattr(attempt, field, value)
                await db.commit()
                if run.status == "cancelled":
                    attempt.status = "cancelled"
                    attempt.outcome = "cancelled"
                    attempt.completed_at = datetime.now(UTC)
                    await db.commit()
                    await self._emit(
                        experiment_id,
                        "eval.attempt.completed",
                        {
                            "attempt_id": attempt_id,
                            "status": "cancelled",
                            "outcome": "cancelled",
                        },
                    )
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
                    await self._emit(
                        experiment_id,
                        "eval.attempt.completed",
                        {
                            "attempt_id": attempt_id,
                            "status": "completed",
                            "outcome": attempt.outcome,
                        },
                    )
                    return

            scoring_started = _phase_time()
            changed_paths = await self.worktrees.changed_paths(provisioned)
            if verifier_artifact_id:
                async with self.session_factory() as db:
                    verifier_artifact = await db.get(
                        models.RunArtifact, verifier_artifact_id
                    )
                if (
                    not verifier_artifact
                    or verifier_artifact.artifact_type != "verifier_bundle"
                    or not verifier_artifact.relative_path.startswith(
                        f"eval-case-{attempt.case_revision_id}/verifier_bundle/"
                    )
                    or not self.artifact_store
                ):
                    raise WorktreeError("Held-out verifier bundle is unavailable")
                verifier_content = await asyncio.to_thread(
                    self.artifact_store.read_verified_bytes,
                    verifier_artifact.relative_path,
                    verifier_artifact.sha256,
                )
                materialize_verifier_bundle(verifier_content, provisioned.path)
            scores = await self._score(scorer_spec, provisioned, changed_paths)
            outcome = classify_required_scores(scores)
            async with self.session_factory() as db:
                attempt = await db.get(models.EvalAttempt, attempt_id)
                if not attempt:
                    return
                for result in scores:
                    artifact_id = None
                    if result.full_output is not None:
                        if not self.artifact_store or not run_id:
                            raise RuntimeError("Scorer output storage is unavailable")
                        writer = self.artifact_store.open_writer(
                            run_id,
                            "scorer_output",
                            {
                                "scorer_key": result.scorer_key,
                                "content_type": "application/json",
                            },
                        )
                        try:
                            writer.write(
                                json.dumps(
                                    result.full_output,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ).encode()
                            )
                            stored = writer.finish()
                        except OSError, RuntimeError, ValueError:
                            writer.abort()
                            raise
                        artifact = models.RunArtifact(
                            run_id=run_id,
                            artifact_type=stored.artifact_type,
                            relative_path=stored.relative_path,
                            sha256=stored.sha256,
                            byte_size=stored.byte_size,
                            metadata_json=stored.metadata,
                        )
                        db.add(artifact)
                        await db.flush()
                        artifact_id = artifact.id
                    db.add(
                        models.EvalScore(
                            attempt_id=attempt.id,
                            scorer_key=result.scorer_key,
                            required=result.required,
                            passed=result.passed,
                            value_json=result.value,
                            summary=result.summary,
                            evidence_json=result.evidence,
                            artifact_id=artifact_id,
                        )
                    )
                attempt.status = "completed"
                attempt.outcome = outcome
                attempt.scoring_duration_ms = int(
                    (_phase_time() - scoring_started) * 1000
                )
                attempt.completed_at = datetime.now(UTC)
                await db.commit()
            await self._emit(
                experiment_id,
                "eval.attempt.completed",
                {"attempt_id": attempt_id, "status": "completed", "outcome": outcome},
            )
        except asyncio.CancelledError:
            if start_task:
                await asyncio.gather(start_task, return_exceptions=True)
            if run_id:
                await self.runtime.cancel(run_id)
            raise
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
            await self._emit(
                experiment_id,
                "eval.attempt.completed",
                {
                    "attempt_id": attempt_id,
                    "status": "completed",
                    "outcome": "infra_error",
                },
            )
        finally:
            if provisioned:
                try:
                    await self.worktrees.cleanup(provisioned)
                    async with self.session_factory() as db:
                        attempt = await db.get(models.EvalAttempt, attempt_id)
                        if attempt:
                            attempt.worktree_path = None
                            await db.commit()
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

    async def _score(
        self,
        specs: list[dict],
        worktree: ProvisionedWorktree,
        changed_paths: set[str],
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
                        capture_full_output=self.artifact_store is not None,
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


async def reconcile_eval_worktrees(
    session_factory: async_sessionmaker[AsyncSession], worktrees: WorktreeService
) -> None:
    async with session_factory() as db:
        attempts = list(
            (
                await db.scalars(
                    select(models.EvalAttempt).where(
                        models.EvalAttempt.worktree_path.is_not(None),
                        models.EvalAttempt.status != "running",
                    )
                )
            ).all()
        )
        for attempt in attempts:
            revision = await db.get(models.EvalCaseRevision, attempt.case_revision_id)
            workspace = (
                await db.get(models.Workspace, revision.workspace_id)
                if revision
                else None
            )
            if not revision or not workspace or not revision.base_sha:
                continue
            provisioned = ProvisionedWorktree(
                attempt_id=attempt.id,
                repository_path=Path(workspace.path).resolve(),
                path=Path(attempt.worktree_path).resolve(),
                base_sha=revision.base_sha,
            )
            try:
                await worktrees.cleanup(provisioned)
            except WorktreeError:
                continue
            attempt.worktree_path = None
        await db.commit()
    async with session_factory() as db:
        retained_paths = {
            Path(path).resolve()
            for path in (
                await db.scalars(
                    select(models.EvalAttempt.worktree_path).where(
                        models.EvalAttempt.worktree_path.is_not(None)
                    )
                )
            ).all()
            if path
        }
    await worktrees.cleanup_orphans(retained_paths)
