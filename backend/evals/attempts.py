"""Registered attempts RPC handlers."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import models
from database.schemas import EvalAttemptArtifactParams, EvalAttemptIdParams
from evals.common import EvalServiceError, _params
from evals.normalizer import normalize_events
from rpc_registry import rpc


class AttemptsHandlers:
    @rpc("eval.attempt.retry")
    async def _rpc_eval_attempt_retry(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalAttemptIdParams, params)
        if not self.scheduler:
            raise EvalServiceError(-32020, "Eval scheduler is unavailable")
        try:
            retry_id = await self.scheduler.retry_attempt(values.attempt_id)
        except ValueError as exc:
            raise EvalServiceError(-32004, str(exc)) from exc
        except RuntimeError as exc:
            raise EvalServiceError(-32010, str(exc)) from exc
        return {
            "accepted": True,
            "retried_attempt_id": values.attempt_id,
            "attempt_id": retry_id,
        }

    @rpc("eval.attempt.artifact")
    async def _rpc_eval_attempt_artifact(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalAttemptArtifactParams, params)
        attempt = await db.get(models.EvalAttempt, values.attempt_id)
        artifact = await db.get(models.RunArtifact, values.artifact_id)
        if (
            not attempt
            or not attempt.run_id
            or not artifact
            or artifact.run_id != attempt.run_id
            or artifact.artifact_type != "scorer_output"
            or not artifact.relative_path.startswith(
                f"run-{attempt.run_id}/scorer_output/"
            )
        ):
            raise EvalServiceError(-32004, "Attempt artifact not found")
        score_id = await db.scalar(
            select(models.EvalScore.id).where(
                models.EvalScore.attempt_id == attempt.id,
                models.EvalScore.artifact_id == artifact.id,
            )
        )
        if score_id is None:
            raise EvalServiceError(-32004, "Attempt artifact not found")
        if not self.artifact_store:
            raise EvalServiceError(-32020, "Artifact storage is unavailable")
        try:
            raw = await asyncio.to_thread(
                self.artifact_store.read_verified_bytes,
                artifact.relative_path,
                artifact.sha256,
            )
            output = json.loads(raw)
            stdout = output["stdout"]
            stderr = output["stderr"]
            if not isinstance(stdout, str) or not isinstance(stderr, str):
                raise TypeError("Invalid scorer output")
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError) as exc:
            raise EvalServiceError(
                -32020, "Scorer output artifact is unavailable or damaged"
            ) from exc
        total_length = max(len(stdout), len(stderr))
        next_offset = min(total_length, values.offset + values.limit)
        return {
            "artifact_id": artifact.id,
            "attempt_id": attempt.id,
            "scorer_key": artifact.metadata_json.get("scorer_key"),
            "stdout": stdout[values.offset : next_offset],
            "stderr": stderr[values.offset : next_offset],
            "offset": values.offset,
            "next_offset": next_offset,
            "has_more": next_offset < total_length,
            "total_length": total_length,
        }

    @rpc("eval.attempt.get")
    async def _rpc_eval_attempt_get(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalAttemptIdParams, params)
        attempt = await db.get(models.EvalAttempt, values.attempt_id)
        if not attempt:
            raise EvalServiceError(-32004, "Eval attempt not found")
        revision = await db.get(models.EvalCaseRevision, attempt.case_revision_id)
        case = await db.get(models.EvalCase, revision.case_id) if revision else None
        snapshot = await db.get(models.EvalConfigSnapshot, attempt.config_snapshot_id)
        config = (
            await db.get(models.EvalConfig, snapshot.config_id) if snapshot else None
        )
        scores = list(
            (
                await db.scalars(
                    select(models.EvalScore)
                    .where(models.EvalScore.attempt_id == attempt.id)
                    .order_by(models.EvalScore.id)
                )
            ).all()
        )
        artifacts = (
            list(
                (
                    await db.scalars(
                        select(models.RunArtifact)
                        .where(models.RunArtifact.run_id == attempt.run_id)
                        .order_by(models.RunArtifact.id)
                    )
                ).all()
            )
            if attempt.run_id
            else []
        )
        run_diff = (
            await db.get(models.RunDiff, attempt.run_id) if attempt.run_id else None
        )
        diff_payload = None
        if run_diff:
            result = run_diff.result or {}
            diff_payload = {
                "run_id": run_diff.run_id,
                "status": run_diff.status,
                "final": run_diff.final,
                "reason": run_diff.reason,
                "files": result.get("files", []),
                "file_count": result.get("file_count", 0),
                "added": result.get("added", 0),
                "deleted": result.get("deleted", 0),
                "captured_at": result.get("captured_at"),
                "stale": None,
                "decision": None,
                "can_revert": False,
            }
        return {
            "id": attempt.id,
            "experiment_id": attempt.experiment_id,
            "case": {"id": case.id, "title": case.title} if case else None,
            "case_revision_id": attempt.case_revision_id,
            "configuration": {
                "snapshot_id": snapshot.id,
                "name": config.name,
                "model": snapshot.model,
                "reasoning_effort": snapshot.reasoning_effort,
            }
            if snapshot and config
            else None,
            "sample_index": attempt.sample_index,
            "retry_index": attempt.retry_index,
            "run_id": attempt.run_id,
            "status": attempt.status,
            "outcome": attempt.outcome,
            "failure_category": attempt.failure_category,
            "durations_ms": {
                "setup": attempt.setup_duration_ms,
                "agent": attempt.agent_duration_ms,
                "scoring": attempt.scoring_duration_ms,
            },
            "tokens": {
                "input": attempt.input_tokens,
                "cached_input": attempt.cached_input_tokens,
                "output": attempt.output_tokens,
                "reasoning_output": attempt.reasoning_output_tokens,
            },
            "scores": [
                {
                    "key": score.scorer_key,
                    "required": score.required,
                    "passed": score.passed,
                    "value": score.value_json,
                    "summary": score.summary,
                    "evidence": score.evidence_json,
                    "artifact_id": score.artifact_id,
                }
                for score in scores
            ],
            "diff": diff_payload,
            "artifacts": [
                {
                    "id": artifact.id,
                    "type": artifact.artifact_type,
                    "sha256": artifact.sha256,
                    "byte_size": artifact.byte_size,
                    "metadata": artifact.metadata_json,
                }
                for artifact in artifacts
            ],
        }

    @rpc("eval.attempt.steps", "eval.attempt.events")
    async def _rpc_eval_attempt_steps(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalAttemptIdParams, params)
        attempt = await db.get(models.EvalAttempt, values.attempt_id)
        if not attempt:
            raise EvalServiceError(-32004, "Eval attempt not found")
        if not attempt.run_id:
            return []
        events = list(
            (
                await db.scalars(
                    select(models.RunEvent)
                    .where(models.RunEvent.run_id == attempt.run_id)
                    .order_by(models.RunEvent.id)
                )
            ).all()
        )
        event_payloads = [
            {
                "id": event.id,
                "type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at,
            }
            for event in events
        ]
        if method == "eval.attempt.events":
            return [
                {**event, "created_at": event["created_at"].isoformat()}
                for event in event_payloads
            ]
        normalized = normalize_events(event_payloads)
        await db.execute(
            delete(models.EvalStep).where(models.EvalStep.run_id == attempt.run_id)
        )
        for step in normalized:
            db.add(
                models.EvalStep(
                    run_id=attempt.run_id,
                    sequence=step["sequence"],
                    source_event_start_id=step["source_event_start_id"],
                    source_event_end_id=step["source_event_end_id"],
                    source_item_id=step["source_item_id"],
                    kind=step["kind"],
                    title=step["title"],
                    status=step["status"],
                    duration_ms=step["duration_ms"],
                    signature=step["signature"],
                    flags_json=step["flags"],
                    summary=step["summary"],
                    normalizer_version=step["normalizer_version"],
                )
            )
        await db.commit()
        return normalized
