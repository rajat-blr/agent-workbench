from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from artifacts import ArtifactStore
from database import models
from database.schemas import (
    EvalAttemptArtifactParams,
    EvalAttemptIdParams,
    EvalCaseCreate,
    EvalCaseCreateFromRun,
    EvalCaseIdParams,
    EvalCaseRevisionParams,
    EvalCaseUpdateDraft,
    EvalConfigCapture,
    EvalConfigDiffParams,
    EvalConfigIdParams,
    EvalExperimentEventsParams,
    EvalExperimentIdParams,
    EvalExperimentPlan,
    EvalSuiteCreate,
    EvalSuiteIdParams,
    EvalSuiteUpdateDraft,
    EvalSuiteVersionParams,
)
from evals.configuration import (
    capture_instruction_files,
    controlled_execution,
    detect_cli_version,
    redact_text,
    reproducibility_warnings,
)
from evals.normalizer import normalize_events
from evals.scheduler import EvalScheduler
from evals.scorers import (
    CommandScorerSpec,
    DiffConstraintSpec,
    FileAssertionSpec,
    classify_required_scores,
    score_command,
    score_diff_constraints,
    score_file_assertion,
)
from evals.statistics import summarize_results
from evals.verifier_bundles import (
    build_verifier_bundle,
    materialize_verifier_bundle,
    verifier_paths,
)
from evals.worktrees import WorktreeError, WorktreeService
from run_diffs import build_starting_patch

FULL_COMMIT_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
SECRET_KEY_RE = re.compile(
    r"(?:secret|token|password|credential|api[_-]?key|authorization)", re.IGNORECASE
)


class EvalServiceError(ValueError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _params(model: type[BaseModel], values: dict[str, Any]) -> BaseModel:
    return model.model_validate(values)


def _revision_payload(revision: models.EvalCaseRevision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "case_id": revision.case_id,
        "revision": revision.revision,
        "status": revision.status,
        "content_hash": revision.content_hash,
        "workspace_id": revision.workspace_id,
        "source_run_id": revision.source_run_id,
        "starting_patch_artifact_id": revision.starting_patch_artifact_id,
        "verifier_artifact_id": revision.verifier_artifact_id,
        "base_sha": revision.base_sha,
        "prompt": revision.prompt,
        "setup_spec": revision.setup_spec_json,
        "scorer_spec": revision.scorer_spec_json,
        "path_policy": revision.path_policy_json,
        "validation_status": revision.validation_status,
        "validation_details": revision.validation_details_json,
        "published_at": revision.published_at.isoformat()
        if revision.published_at
        else None,
        "created_at": revision.created_at.isoformat(),
    }


def _case_payload(
    case: models.EvalCase, revisions: list[models.EvalCaseRevision]
) -> dict[str, Any]:
    ordered = sorted(revisions, key=lambda revision: revision.revision, reverse=True)
    return {
        "id": case.id,
        "title": case.title,
        "description": case.description,
        "created_at": case.created_at.isoformat(),
        "updated_at": case.updated_at.isoformat(),
        "latest_revision": _revision_payload(ordered[0]) if ordered else None,
    }


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if SECRET_KEY_RE.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _config_payload(
    config: models.EvalConfig, snapshot: models.EvalConfigSnapshot
) -> dict[str, Any]:
    return {
        "id": config.id,
        "name": config.name,
        "description": config.description,
        "created_at": config.created_at.isoformat(),
        "snapshot": {
            "id": snapshot.id,
            "content_hash": snapshot.content_hash,
            "model": snapshot.model,
            "reasoning_effort": snapshot.reasoning_effort,
            "instructions": snapshot.instructions_json,
            "codex_config": snapshot.codex_config_json,
            "sandbox_policy": snapshot.sandbox_policy_json,
            "cli_version": snapshot.cli_version,
            "uncontrolled_inputs": snapshot.uncontrolled_inputs_json,
            "reproducibility_warnings": reproducibility_warnings(snapshot),
            "created_at": snapshot.created_at.isoformat(),
        },
    }


class EvalService:
    def __init__(
        self,
        worktrees: WorktreeService,
        scheduler: EvalScheduler | None = None,
        artifact_store: ArtifactStore | None = None,
        cli_command: str | None = None,
    ) -> None:
        self.worktrees = worktrees
        self.scheduler = scheduler
        self.artifact_store = artifact_store
        self.cli_command = cli_command

    async def _verifier_content(
        self, db: AsyncSession, revision: models.EvalCaseRevision
    ) -> bytes | None:
        if not revision.verifier_artifact_id:
            return None
        artifact = await db.get(models.RunArtifact, revision.verifier_artifact_id)
        if (
            not artifact
            or artifact.artifact_type != "verifier_bundle"
            or not artifact.relative_path.startswith(
                f"eval-case-{revision.id}/verifier_bundle/"
            )
            or not self.artifact_store
        ):
            raise WorktreeError("Held-out verifier bundle is unavailable")
        try:
            return await asyncio.to_thread(
                self.artifact_store.read_verified_bytes,
                artifact.relative_path,
                artifact.sha256,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise WorktreeError("Held-out verifier bundle checksum is invalid") from exc

    @staticmethod
    async def _head(workspace_path: str) -> str | None:
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                workspace_path,
                "rev-parse",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
        except FileNotFoundError, TimeoutError:
            return None
        sha = stdout.decode().strip()
        return (
            sha if process.returncode == 0 and FULL_COMMIT_RE.fullmatch(sha) else None
        )

    @staticmethod
    def _canonical_content(revision: models.EvalCaseRevision) -> bytes:
        content = {
            "workspace_id": revision.workspace_id,
            "base_sha": revision.base_sha,
            "prompt": revision.prompt,
            "setup_spec": revision.setup_spec_json,
            "scorer_spec": revision.scorer_spec_json,
            "path_policy": revision.path_policy_json,
            "starting_patch_artifact_id": revision.starting_patch_artifact_id,
            "verifier_artifact_id": revision.verifier_artifact_id,
        }
        return json.dumps(content, sort_keys=True, separators=(",", ":")).encode()

    async def _revision(
        self, db: AsyncSession, case_id: int, revision_id: int
    ) -> tuple[models.EvalCase, models.EvalCaseRevision]:
        case = await db.get(models.EvalCase, case_id)
        revision = await db.get(models.EvalCaseRevision, revision_id)
        if not case or not revision or revision.case_id != case.id:
            raise EvalServiceError(-32004, "Eval case revision not found")
        return case, revision

    async def _suite_payload(
        self, db: AsyncSession, suite: models.EvalSuite
    ) -> dict[str, Any]:
        versions = list(
            (
                await db.scalars(
                    select(models.EvalSuiteVersion)
                    .where(models.EvalSuiteVersion.suite_id == suite.id)
                    .order_by(models.EvalSuiteVersion.version.desc())
                )
            ).all()
        )
        latest = versions[0]
        members = list(
            (
                await db.scalars(
                    select(models.EvalSuiteVersionCase)
                    .where(models.EvalSuiteVersionCase.suite_version_id == latest.id)
                    .order_by(models.EvalSuiteVersionCase.ordinal)
                )
            ).all()
        )
        cases = []
        for member in members:
            revision = await db.get(models.EvalCaseRevision, member.case_revision_id)
            case = await db.get(models.EvalCase, revision.case_id) if revision else None
            if revision and case:
                cases.append(
                    {
                        "case_id": case.id,
                        "title": case.title,
                        "revision_id": revision.id,
                        "revision": revision.revision,
                        "ordinal": member.ordinal,
                    }
                )
        return {
            "id": suite.id,
            "name": suite.name,
            "description": suite.description,
            "created_at": suite.created_at.isoformat(),
            "updated_at": suite.updated_at.isoformat(),
            "latest_version": {
                "id": latest.id,
                "version": latest.version,
                "status": latest.status,
                "content_hash": latest.content_hash,
                "frozen_at": latest.frozen_at.isoformat() if latest.frozen_at else None,
                "cases": cases,
            },
        }

    async def _experiment_inputs(
        self, db: AsyncSession, values: EvalExperimentPlan
    ) -> tuple[
        models.EvalSuiteVersion,
        list[models.EvalSuiteVersionCase],
        list[models.EvalConfigSnapshot],
        dict[str, Any],
    ]:
        if len(values.config_snapshot_ids) != len(set(values.config_snapshot_ids)):
            raise EvalServiceError(-32602, "Configuration snapshots must be distinct")
        suite_version = await db.get(models.EvalSuiteVersion, values.suite_version_id)
        if not suite_version or suite_version.status != "frozen":
            raise EvalServiceError(-32010, "Experiments require a frozen suite version")
        members = list(
            (
                await db.scalars(
                    select(models.EvalSuiteVersionCase)
                    .where(
                        models.EvalSuiteVersionCase.suite_version_id == suite_version.id
                    )
                    .order_by(models.EvalSuiteVersionCase.ordinal)
                )
            ).all()
        )
        if not members:
            raise EvalServiceError(-32010, "The frozen suite contains no cases")
        snapshots = [
            await db.get(models.EvalConfigSnapshot, item)
            for item in values.config_snapshot_ids
        ]
        if any(snapshot is None for snapshot in snapshots):
            raise EvalServiceError(-32004, "Configuration snapshot not found")
        typed_snapshots = [snapshot for snapshot in snapshots if snapshot is not None]
        repositories: set[str] = set()
        invalid_cases: list[int] = []
        for member in members:
            revision = await db.get(models.EvalCaseRevision, member.case_revision_id)
            if (
                not revision
                or revision.status != "published"
                or revision.validation_status != "valid"
            ):
                invalid_cases.append(member.case_revision_id)
                continue
            workspace = await db.get(models.Workspace, revision.workspace_id)
            if not workspace or not revision.base_sha:
                invalid_cases.append(member.case_revision_id)
            elif workspace:
                repositories.add(workspace.path)
        differences = []
        if len(typed_snapshots) == 2:
            fields = (
                "model",
                "reasoning_effort",
                "instructions_json",
                "codex_config_json",
                "sandbox_policy_json",
                "cli_version",
                "uncontrolled_inputs_json",
            )
            differences = [
                field.removesuffix("_json")
                for field in fields
                if getattr(typed_snapshots[0], field)
                != getattr(typed_snapshots[1], field)
            ]
        warnings = []
        if invalid_cases:
            warnings.append(
                f"{len(invalid_cases)} case revisions are invalid or unavailable"
            )
        if len(differences) > 1:
            warnings.append(
                "Configurations differ across multiple controlled dimensions"
            )
        if any(snapshot.uncontrolled_inputs_json for snapshot in typed_snapshots):
            warnings.append("One or more configurations include uncontrolled inputs")
        for index, snapshot in enumerate(typed_snapshots):
            try:
                controlled_execution(
                    snapshot.instructions_json,
                    snapshot.codex_config_json,
                    snapshot.sandbox_policy_json,
                )
            except ValueError as exc:
                raise EvalServiceError(-32602, str(exc)) from exc
            warnings.extend(
                f"Config {'AB'[index]}: {warning}"
                for warning in reproducibility_warnings(snapshot)
            )
        preflight = {
            "case_count": len(members),
            "config_count": len(typed_snapshots),
            "samples_per_case": values.samples_per_case,
            "attempt_count": len(members)
            * len(typed_snapshots)
            * values.samples_per_case,
            "repositories": sorted(repositories),
            "invalid_case_revision_ids": invalid_cases,
            "configuration_differences": differences,
            "warnings": warnings,
            "isolation": "detached disposable Git worktree",
            "network_enabled": False,
        }
        return suite_version, members, typed_snapshots, preflight

    async def _experiment_payload(
        self, db: AsyncSession, experiment: models.EvalExperiment
    ) -> dict[str, Any]:
        configs = list(
            (
                await db.scalars(
                    select(models.EvalExperimentConfig)
                    .where(models.EvalExperimentConfig.experiment_id == experiment.id)
                    .order_by(models.EvalExperimentConfig.ordinal)
                )
            ).all()
        )
        attempts = list(
            (
                await db.scalars(
                    select(models.EvalAttempt)
                    .where(models.EvalAttempt.experiment_id == experiment.id)
                    .order_by(models.EvalAttempt.id)
                )
            ).all()
        )
        counts: dict[str, int] = defaultdict(int)
        for attempt in attempts:
            counts[attempt.status] += 1
        case_titles = dict(
            (
                await db.execute(
                    select(models.EvalCaseRevision.id, models.EvalCase.title)
                    .join(
                        models.EvalCase,
                        models.EvalCase.id == models.EvalCaseRevision.case_id,
                    )
                    .where(
                        models.EvalCaseRevision.id.in_(
                            {item.case_revision_id for item in attempts}
                        )
                    )
                )
            ).all()
        )
        attempt_rows = [
            {
                "id": item.id,
                "case_revision_id": item.case_revision_id,
                "case_title": case_titles.get(item.case_revision_id),
                "config_snapshot_id": item.config_snapshot_id,
                "sample_index": item.sample_index,
                "retry_index": item.retry_index,
                "run_id": item.run_id,
                "status": item.status,
                "outcome": item.outcome,
                "failure_category": item.failure_category,
                "setup_duration_ms": item.setup_duration_ms,
                "agent_duration_ms": item.agent_duration_ms,
                "scoring_duration_ms": item.scoring_duration_ms,
                "input_tokens": item.input_tokens,
                "cached_input_tokens": item.cached_input_tokens,
                "output_tokens": item.output_tokens,
                "reasoning_output_tokens": item.reasoning_output_tokens,
            }
            for item in attempts
        ]
        config_ids = [item.config_snapshot_id for item in configs]
        config_labels = []
        for config_id in config_ids:
            snapshot = await db.get(models.EvalConfigSnapshot, config_id)
            config = (
                await db.get(models.EvalConfig, snapshot.config_id)
                if snapshot
                else None
            )
            config_labels.append(
                {
                    "snapshot_id": config_id,
                    "name": config.name if config else f"Config #{config_id}",
                }
            )
        return {
            "id": experiment.id,
            "name": experiment.name,
            "suite_version_id": experiment.suite_version_id,
            "status": experiment.status,
            "samples_per_case": experiment.samples_per_case,
            "concurrency": experiment.concurrency,
            "timeout_seconds": experiment.timeout_seconds,
            "config_snapshot_ids": config_ids,
            "configurations": config_labels,
            "attempt_count": len(attempts),
            "attempt_status_counts": dict(counts),
            "attempts": attempt_rows,
            "results": summarize_results(
                attempt_rows, config_ids, is_final=experiment.status == "completed"
            ),
            "created_at": experiment.created_at.isoformat(),
            "started_at": experiment.started_at.isoformat()
            if experiment.started_at
            else None,
            "completed_at": experiment.completed_at.isoformat()
            if experiment.completed_at
            else None,
        }

    async def dispatch(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        if method == "eval.case.create_from_run":
            values = _params(EvalCaseCreateFromRun, params)
            run = await db.get(models.Run, values.run_id)
            if (
                not run
                or run.kind != "chat"
                or run.status != "completed"
                or not run.session_id
            ):
                raise EvalServiceError(
                    -32010, "Only completed Chat runs can become eval cases"
                )
            session = await db.get(models.Session, run.session_id)
            workspace = (
                await db.get(models.Workspace, session.workspace_id)
                if session
                else None
            )
            run_diff = await db.get(models.RunDiff, run.id)
            baseline = run_diff.baseline if run_diff else None
            base_sha = baseline.get("base_sha") if isinstance(baseline, dict) else None
            if not workspace or not baseline or not base_sha:
                raise EvalServiceError(
                    -32010, "This run does not contain a reproducible Git baseline"
                )
            case = models.EvalCase(
                title=(values.title or run.prompt.splitlines()[0][:120]).strip()
                or f"Eval from run #{run.id}",
                description=values.description.strip(),
            )
            db.add(case)
            await db.flush()
            starting_artifact_id = None
            patch = await asyncio.to_thread(build_starting_patch, baseline, base_sha)
            if patch:
                if not self.artifact_store:
                    raise EvalServiceError(-32020, "Artifact storage is unavailable")
                writer = self.artifact_store.open_writer(
                    run.id,
                    "starting_patch",
                    {"content_type": "text/x-diff", "source_run_id": run.id},
                )
                try:
                    writer.write(patch)
                    stored = writer.finish()
                except OSError, RuntimeError, ValueError:
                    writer.abort()
                    raise
                artifact = models.RunArtifact(
                    run_id=run.id,
                    artifact_type=stored.artifact_type,
                    relative_path=stored.relative_path,
                    sha256=stored.sha256,
                    byte_size=stored.byte_size,
                    metadata_json=stored.metadata,
                )
                db.add(artifact)
                await db.flush()
                starting_artifact_id = artifact.id
            events = list(
                (
                    await db.scalars(
                        select(models.RunEvent)
                        .where(
                            models.RunEvent.run_id == run.id,
                            models.RunEvent.event_type == "codex.item.completed",
                        )
                        .order_by(models.RunEvent.id)
                    )
                ).all()
            )
            candidates = []
            verifier_pattern = re.compile(
                r"\b(?:pytest|test|lint|check|mypy|tsc|cargo\s+test|go\s+test|vite\s+build)\b",
                re.IGNORECASE,
            )
            for event in events:
                item = event.payload.get("item")
                command = (
                    item.get("command")
                    if isinstance(item, dict)
                    and item.get("type") == "command_execution"
                    else None
                )
                if (
                    isinstance(command, str)
                    and verifier_pattern.search(command)
                    and command not in candidates
                ):
                    candidates.append(command)
            revision = models.EvalCaseRevision(
                case_id=case.id,
                revision=1,
                status="draft",
                workspace_id=workspace.id,
                source_run_id=run.id,
                base_sha=base_sha.lower(),
                prompt=run.prompt,
                setup_spec_json=[],
                scorer_spec_json=[],
                path_policy_json={},
                starting_patch_artifact_id=starting_artifact_id,
                validation_status="not_validated",
                validation_details_json={
                    "candidate_verifier_commands": candidates[:10]
                },
            )
            db.add(revision)
            await db.commit()
            await db.refresh(case)
            await db.refresh(revision)
            return _case_payload(case, [revision])

        if method == "eval.experiment.preflight":
            values = _params(EvalExperimentPlan, params)
            _, _, _, preflight = await self._experiment_inputs(db, values)
            return preflight

        if method == "eval.experiment.create":
            values = _params(EvalExperimentPlan, params)
            (
                suite_version,
                members,
                snapshots,
                preflight,
            ) = await self._experiment_inputs(db, values)
            if preflight["invalid_case_revision_ids"]:
                raise EvalServiceError(
                    -32010, "Resolve invalid cases before creating the experiment"
                )
            suite = await db.get(models.EvalSuite, suite_version.suite_id)
            name = (
                values.name.strip() or f"{suite.name if suite else 'Suite'} comparison"
            )
            experiment = models.EvalExperiment(
                name=name,
                suite_version_id=suite_version.id,
                status="ready",
                samples_per_case=values.samples_per_case,
                concurrency=values.concurrency,
                timeout_seconds=values.timeout_seconds,
            )
            db.add(experiment)
            await db.flush()
            for ordinal, snapshot in enumerate(snapshots):
                db.add(
                    models.EvalExperimentConfig(
                        experiment_id=experiment.id,
                        config_snapshot_id=snapshot.id,
                        ordinal=ordinal,
                    )
                )
            for member in members:
                for sample_index in range(values.samples_per_case):
                    for snapshot in snapshots:
                        db.add(
                            models.EvalAttempt(
                                experiment_id=experiment.id,
                                case_revision_id=member.case_revision_id,
                                config_snapshot_id=snapshot.id,
                                sample_index=sample_index,
                                retry_index=0,
                                status="queued",
                            )
                        )
            await db.commit()
            await db.refresh(experiment)
            return await self._experiment_payload(db, experiment)

        if method == "eval.experiment.list":
            experiments = (
                await db.scalars(
                    select(models.EvalExperiment).order_by(
                        models.EvalExperiment.created_at.desc()
                    )
                )
            ).all()
            return [await self._experiment_payload(db, item) for item in experiments]

        if method == "eval.experiment.get":
            values = _params(EvalExperimentIdParams, params)
            experiment = await db.get(models.EvalExperiment, values.experiment_id)
            if not experiment:
                raise EvalServiceError(-32004, "Eval experiment not found")
            return await self._experiment_payload(db, experiment)

        if method == "eval.experiment.start":
            values = _params(EvalExperimentIdParams, params)
            if not self.scheduler:
                raise EvalServiceError(-32020, "Eval scheduler is unavailable")
            try:
                await self.scheduler.start(values.experiment_id)
            except ValueError as exc:
                raise EvalServiceError(-32004, str(exc)) from exc
            except RuntimeError as exc:
                raise EvalServiceError(-32010, str(exc)) from exc
            return {"accepted": True, "experiment_id": values.experiment_id}

        if method == "eval.experiment.cancel":
            values = _params(EvalExperimentIdParams, params)
            if not self.scheduler:
                raise EvalServiceError(-32020, "Eval scheduler is unavailable")
            try:
                await self.scheduler.cancel(values.experiment_id)
            except ValueError as exc:
                raise EvalServiceError(-32004, str(exc)) from exc
            except RuntimeError as exc:
                raise EvalServiceError(-32010, str(exc)) from exc
            return {"accepted": True, "experiment_id": values.experiment_id}

        if method == "eval.experiment.resume":
            values = _params(EvalExperimentIdParams, params)
            if not self.scheduler:
                raise EvalServiceError(-32020, "Eval scheduler is unavailable")
            try:
                attempt_ids = await self.scheduler.resume(values.experiment_id)
            except ValueError as exc:
                raise EvalServiceError(-32004, str(exc)) from exc
            except RuntimeError as exc:
                raise EvalServiceError(-32010, str(exc)) from exc
            return {
                "accepted": True,
                "experiment_id": values.experiment_id,
                "attempt_ids": attempt_ids,
            }

        if method in {"eval.experiment.subscribe", "eval.experiment.unsubscribe"}:
            values = _params(EvalExperimentIdParams, params)
            if not await db.get(models.EvalExperiment, values.experiment_id):
                raise EvalServiceError(-32004, "Eval experiment not found")
            return {
                "experiment_id": values.experiment_id,
                "subscribed": method.endswith("subscribe")
                and not method.endswith("unsubscribe"),
            }

        if method == "eval.experiment.events":
            values = _params(EvalExperimentEventsParams, params)
            if not await db.get(models.EvalExperiment, values.experiment_id):
                raise EvalServiceError(-32004, "Eval experiment not found")
            events = list(
                (
                    await db.scalars(
                        select(models.EvalExperimentEvent)
                        .where(
                            models.EvalExperimentEvent.experiment_id
                            == values.experiment_id,
                            models.EvalExperimentEvent.id > values.after_sequence,
                        )
                        .order_by(models.EvalExperimentEvent.id)
                        .limit(values.limit)
                    )
                ).all()
            )
            return [
                {
                    "experiment_id": event.experiment_id,
                    "type": event.event_type,
                    "payload": event.payload,
                    "sequence": event.id,
                    "created_at": event.created_at.isoformat(),
                }
                for event in events
            ]

        if method == "eval.attempt.retry":
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

        if method == "eval.attempt.artifact":
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

        if method == "eval.attempt.get":
            values = _params(EvalAttemptIdParams, params)
            attempt = await db.get(models.EvalAttempt, values.attempt_id)
            if not attempt:
                raise EvalServiceError(-32004, "Eval attempt not found")
            revision = await db.get(models.EvalCaseRevision, attempt.case_revision_id)
            case = await db.get(models.EvalCase, revision.case_id) if revision else None
            snapshot = await db.get(
                models.EvalConfigSnapshot, attempt.config_snapshot_id
            )
            config = (
                await db.get(models.EvalConfig, snapshot.config_id)
                if snapshot
                else None
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

        if method in {"eval.attempt.steps", "eval.attempt.events"}:
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

        if method == "eval.suite.create":
            values = _params(EvalSuiteCreate, params)
            if not values.name.strip():
                raise EvalServiceError(-32602, "Suite name is required")
            suite = models.EvalSuite(
                name=values.name.strip(), description=values.description.strip()
            )
            db.add(suite)
            await db.flush()
            db.add(
                models.EvalSuiteVersion(suite_id=suite.id, version=1, status="draft")
            )
            await db.commit()
            await db.refresh(suite)
            return await self._suite_payload(db, suite)

        if method == "eval.suite.list":
            suites = (
                await db.scalars(
                    select(models.EvalSuite).order_by(
                        models.EvalSuite.updated_at.desc()
                    )
                )
            ).all()
            return [await self._suite_payload(db, suite) for suite in suites]

        if method == "eval.suite.get":
            values = _params(EvalSuiteIdParams, params)
            suite = await db.get(models.EvalSuite, values.suite_id)
            if not suite:
                raise EvalServiceError(-32004, "Eval suite not found")
            return await self._suite_payload(db, suite)

        if method == "eval.suite.update_draft":
            values = _params(EvalSuiteUpdateDraft, params)
            suite = await db.get(models.EvalSuite, values.suite_id)
            version = await db.get(models.EvalSuiteVersion, values.version_id)
            if not suite or not version or version.suite_id != suite.id:
                raise EvalServiceError(-32004, "Eval suite version not found")
            if version.status == "frozen":
                old_members = list(
                    (
                        await db.scalars(
                            select(models.EvalSuiteVersionCase)
                            .where(
                                models.EvalSuiteVersionCase.suite_version_id
                                == version.id
                            )
                            .order_by(models.EvalSuiteVersionCase.ordinal)
                        )
                    ).all()
                )
                version = models.EvalSuiteVersion(
                    suite_id=suite.id, version=version.version + 1, status="draft"
                )
                db.add(version)
                await db.flush()
                for member in old_members:
                    db.add(
                        models.EvalSuiteVersionCase(
                            suite_version_id=version.id,
                            case_revision_id=member.case_revision_id,
                            ordinal=member.ordinal,
                        )
                    )
            if values.name is not None:
                suite.name = values.name.strip()
            if values.description is not None:
                suite.description = values.description.strip()
            if values.case_revision_ids is not None:
                if len(values.case_revision_ids) != len(set(values.case_revision_ids)):
                    raise EvalServiceError(
                        -32602, "A case revision may appear only once"
                    )
                revisions = [
                    await db.get(models.EvalCaseRevision, item)
                    for item in values.case_revision_ids
                ]
                if any(
                    item is None or item.status != "published" for item in revisions
                ):
                    raise EvalServiceError(
                        -32602, "Suites may contain only published case revisions"
                    )
                await db.execute(
                    delete(models.EvalSuiteVersionCase).where(
                        models.EvalSuiteVersionCase.suite_version_id == version.id
                    )
                )
                for ordinal, revision_id in enumerate(values.case_revision_ids):
                    db.add(
                        models.EvalSuiteVersionCase(
                            suite_version_id=version.id,
                            case_revision_id=revision_id,
                            ordinal=ordinal,
                        )
                    )
            suite.updated_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(suite)
            return await self._suite_payload(db, suite)

        if method == "eval.suite.freeze":
            values = _params(EvalSuiteVersionParams, params)
            suite = await db.get(models.EvalSuite, values.suite_id)
            version = await db.get(models.EvalSuiteVersion, values.version_id)
            if not suite or not version or version.suite_id != suite.id:
                raise EvalServiceError(-32004, "Eval suite version not found")
            if version.status != "draft":
                raise EvalServiceError(-32010, "Suite version is already frozen")
            members = list(
                (
                    await db.scalars(
                        select(models.EvalSuiteVersionCase)
                        .where(
                            models.EvalSuiteVersionCase.suite_version_id == version.id
                        )
                        .order_by(models.EvalSuiteVersionCase.ordinal)
                    )
                ).all()
            )
            if not members:
                raise EvalServiceError(
                    -32010, "Add at least one published case before freezing"
                )
            canonical = json.dumps(
                [item.case_revision_id for item in members], separators=(",", ":")
            )
            version.content_hash = hashlib.sha256(canonical.encode()).hexdigest()
            version.status = "frozen"
            version.frozen_at = datetime.now(UTC)
            suite.updated_at = version.frozen_at
            await db.commit()
            await db.refresh(suite)
            return await self._suite_payload(db, suite)

        if method == "eval.config.capture":
            values = _params(EvalConfigCapture, params)
            if not values.name.strip():
                raise EvalServiceError(-32602, "Configuration name is required")
            if values.reasoning_effort not in {
                None,
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
            }:
                raise EvalServiceError(-32602, "Unsupported reasoning effort")
            instructions = [
                item for item in values.instructions if item.get("kind") != "preamble"
            ]
            observations = list(values.uncontrolled_inputs)
            if values.workspace_id:
                workspace = await db.get(models.Workspace, values.workspace_id)
                if not workspace:
                    raise EvalServiceError(-32004, "Workspace not found")
                workspace_path = Path(workspace.path).resolve()
                if not workspace_path.is_dir():
                    raise EvalServiceError(
                        -32010, "Instruction capture workspace is unavailable"
                    )
                try:
                    root = Path(
                        (
                            await self.worktrees._git(
                                workspace_path, "rev-parse", "--show-toplevel"
                            )
                        )
                        .decode()
                        .strip()
                    )
                except WorktreeError:
                    root = workspace_path
                captured, notices = await asyncio.to_thread(
                    capture_instruction_files,
                    workspace_path,
                    root,
                    Path(
                        os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
                    ).expanduser(),
                )
                instructions = captured + instructions
                observations.extend(notices)
            else:
                observations.append(
                    {
                        "kind": "instruction_capture",
                        "detail": "No workspace selected; instruction files were not captured",
                    }
                )
            cli_version = await detect_cli_version(self.cli_command)
            if values.cli_version:
                observations.append(
                    {
                        "kind": "cli_version",
                        "detail": "Client-declared CLI version is not used as verified executable evidence",
                    }
                )
            if values.instruction_preamble.strip():
                instructions.append(
                    {"kind": "preamble", "content": values.instruction_preamble.strip()}
                )
            try:
                controlled_execution(
                    instructions, values.codex_config, values.sandbox_policy
                )
            except ValueError as exc:
                raise EvalServiceError(-32602, str(exc)) from exc
            config = models.EvalConfig(
                name=values.name.strip(), description=values.description.strip()
            )
            db.add(config)
            await db.flush()
            content = _redact(
                {
                    "model": values.model,
                    "reasoning_effort": values.reasoning_effort,
                    "instructions": instructions,
                    "codex_config": values.codex_config,
                    "sandbox_policy": {
                        "mode": values.sandbox_policy.get("mode", "workspace-write"),
                        "network": False,
                    },
                    "cli_version": cli_version,
                    "uncontrolled_inputs": observations,
                }
            )
            snapshot = models.EvalConfigSnapshot(
                config_id=config.id,
                content_hash=hashlib.sha256(
                    json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                model=content["model"],
                reasoning_effort=content["reasoning_effort"],
                instructions_json=content["instructions"],
                codex_config_json=content["codex_config"],
                sandbox_policy_json=content["sandbox_policy"],
                cli_version=content["cli_version"],
                uncontrolled_inputs_json=content["uncontrolled_inputs"],
            )
            db.add(snapshot)
            await db.commit()
            await db.refresh(config)
            await db.refresh(snapshot)
            return _config_payload(config, snapshot)

        if method == "eval.config.list":
            configs = (
                await db.scalars(
                    select(models.EvalConfig).order_by(
                        models.EvalConfig.created_at.desc()
                    )
                )
            ).all()
            payloads = []
            for config in configs:
                snapshot = await db.scalar(
                    select(models.EvalConfigSnapshot)
                    .where(models.EvalConfigSnapshot.config_id == config.id)
                    .order_by(models.EvalConfigSnapshot.id.desc())
                )
                if snapshot:
                    payloads.append(_config_payload(config, snapshot))
            return payloads

        if method == "eval.config.get":
            values = _params(EvalConfigIdParams, params)
            config = await db.get(models.EvalConfig, values.config_id)
            snapshot = await db.scalar(
                select(models.EvalConfigSnapshot)
                .where(models.EvalConfigSnapshot.config_id == values.config_id)
                .order_by(models.EvalConfigSnapshot.id.desc())
            )
            if not config or not snapshot:
                raise EvalServiceError(-32004, "Eval configuration not found")
            return _config_payload(config, snapshot)

        if method == "eval.config.diff":
            values = _params(EvalConfigDiffParams, params)
            left = await db.get(models.EvalConfigSnapshot, values.left_snapshot_id)
            right = await db.get(models.EvalConfigSnapshot, values.right_snapshot_id)
            if not left or not right:
                raise EvalServiceError(-32004, "Configuration snapshot not found")
            fields = (
                "model",
                "reasoning_effort",
                "instructions_json",
                "codex_config_json",
                "sandbox_policy_json",
                "cli_version",
                "uncontrolled_inputs_json",
            )
            return {
                "differences": [
                    {
                        "field": field.removesuffix("_json"),
                        "left": getattr(left, field),
                        "right": getattr(right, field),
                    }
                    for field in fields
                    if getattr(left, field) != getattr(right, field)
                ]
            }

        if method == "eval.case.create":
            values = _params(EvalCaseCreate, params)
            workspace = await db.get(models.Workspace, values.workspace_id)
            if not workspace:
                raise EvalServiceError(-32004, "Workspace not found")
            title = values.title.strip()
            prompt = values.prompt.strip()
            if not title or not prompt:
                raise EvalServiceError(-32602, "Case title and prompt are required")
            if values.base_sha and not FULL_COMMIT_RE.fullmatch(values.base_sha):
                raise EvalServiceError(-32602, "Base commit must be a full Git SHA")
            case = models.EvalCase(
                title=title,
                description=values.description.strip(),
            )
            db.add(case)
            await db.flush()
            base_sha = values.base_sha or await self._head(workspace.path)
            revision = models.EvalCaseRevision(
                case_id=case.id,
                revision=1,
                status="draft",
                workspace_id=workspace.id,
                base_sha=base_sha.lower() if base_sha else None,
                prompt=prompt,
                setup_spec_json=[],
                scorer_spec_json=[],
                path_policy_json={},
                validation_status="not_validated",
                validation_details_json={},
            )
            db.add(revision)
            await db.commit()
            await db.refresh(case)
            await db.refresh(revision)
            return _case_payload(case, [revision])

        if method == "eval.case.revise":
            values = _params(EvalCaseRevisionParams, params)
            case, source = await self._revision(db, values.case_id, values.revision_id)
            if source.status != "published":
                raise EvalServiceError(
                    -32010, "Only published revisions can be revised"
                )
            revisions = list(
                (
                    await db.scalars(
                        select(models.EvalCaseRevision)
                        .where(models.EvalCaseRevision.case_id == case.id)
                        .order_by(models.EvalCaseRevision.revision.desc())
                    )
                ).all()
            )
            if revisions[0].status == "draft":
                return _case_payload(case, revisions)
            if revisions[0].id != source.id:
                raise EvalServiceError(-32010, "Revise the latest published revision")
            # Verify before creating the draft; bundles are owned by revision ID.
            verifier_content = await self._verifier_content(db, source)
            revision = models.EvalCaseRevision(
                case_id=case.id,
                revision=source.revision + 1,
                status="draft",
                workspace_id=source.workspace_id,
                source_run_id=source.source_run_id,
                base_sha=source.base_sha,
                prompt=source.prompt,
                starting_patch_artifact_id=source.starting_patch_artifact_id,
                setup_spec_json=deepcopy(source.setup_spec_json),
                scorer_spec_json=deepcopy(source.scorer_spec_json),
                path_policy_json=deepcopy(source.path_policy_json),
                validation_status="not_validated",
                validation_details_json={},
            )
            db.add(revision)
            await db.flush()
            if verifier_content is not None:
                writer = self.artifact_store.open_case_writer(
                    revision.id,
                    "verifier_bundle",
                    {"held_out_paths": verifier_paths(verifier_content)},
                )
                try:
                    writer.write(verifier_content)
                    stored = writer.finish()
                except OSError, RuntimeError, ValueError:
                    writer.abort()
                    raise
                artifact = models.RunArtifact(
                    run_id=None,
                    artifact_type=stored.artifact_type,
                    relative_path=stored.relative_path,
                    sha256=stored.sha256,
                    byte_size=stored.byte_size,
                    metadata_json=stored.metadata,
                )
                db.add(artifact)
                await db.flush()
                revision.verifier_artifact_id = artifact.id
            case.updated_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(revision)
            return _case_payload(case, [revision, *revisions])

        if method == "eval.case.validate":
            values = _params(EvalCaseRevisionParams, params)
            case, revision = await self._revision(
                db, values.case_id, values.revision_id
            )
            if revision.status != "draft":
                raise EvalServiceError(
                    -32010, "Published revisions cannot be revalidated"
                )
            workspace = await db.get(models.Workspace, revision.workspace_id)
            problems: list[str] = []
            if not workspace:
                problems.append("Workspace no longer exists")
            if not revision.base_sha:
                problems.append("A full base commit SHA is required")
            if not revision.scorer_spec_json:
                problems.append("At least one deterministic scorer is required")
            base_expectation = revision.path_policy_json.get(
                "base_expectation", "required_scorer_fails"
            )
            if base_expectation not in {
                "required_scorer_fails",
                "required_scorer_passes",
                "none",
            }:
                problems.append("Unsupported base-state expectation")
            results = []
            provisioned = None
            held_out_paths: list[str] = []
            if not problems and workspace and revision.base_sha:
                try:
                    verifier_content = await self._verifier_content(db, revision)
                    starting_patch = None
                    if revision.starting_patch_artifact_id:
                        artifact = await db.get(
                            models.RunArtifact, revision.starting_patch_artifact_id
                        )
                        if not artifact or not self.artifact_store:
                            raise WorktreeError(
                                "Starting patch artifact is unavailable"
                            )
                        starting_patch = await asyncio.to_thread(
                            self.artifact_store.read_bytes, artifact.relative_path
                        )
                    provisioned = await self.worktrees.provision(
                        workspace.path,
                        revision.base_sha,
                        revision.id,
                        starting_patch=starting_patch,
                    )
                    if verifier_content:
                        held_out_paths = verifier_paths(verifier_content)
                        for path in held_out_paths:
                            if (provisioned.path / path).exists():
                                raise WorktreeError(
                                    f"Held-out verifier path is already agent-visible: {path}"
                                )
                    for raw in revision.setup_spec_json:
                        if (
                            raw.get("type") != "command"
                            or not isinstance(raw.get("argv"), list)
                            or not all(isinstance(item, str) for item in raw["argv"])
                        ):
                            raise WorktreeError("Unsupported setup step")
                        try:
                            timeout_seconds = float(raw.get("timeout_seconds", 120))
                        except (TypeError, ValueError) as exc:
                            raise WorktreeError("Invalid setup timeout") from exc
                        if timeout_seconds <= 0:
                            raise WorktreeError("Invalid setup timeout")
                        setup_result = await score_command(
                            CommandScorerSpec(
                                key=str(raw.get("key", "setup")),
                                argv=tuple(raw["argv"]),
                                timeout_seconds=timeout_seconds,
                            ),
                            provisioned.path,
                        )
                        if setup_result.status != "pass":
                            raise WorktreeError(f"Setup failed: {setup_result.summary}")
                    if verifier_content:
                        materialize_verifier_bundle(verifier_content, provisioned.path)
                    for raw in revision.scorer_spec_json:
                        scorer_type = raw.get("type")
                        key = str(raw.get("key") or scorer_type or "scorer")
                        if scorer_type == "command":
                            argv = raw.get("argv")
                            if not isinstance(argv, list) or not all(
                                isinstance(item, str) for item in argv
                            ):
                                problems.append(
                                    f"{key}: command argv must be a string list"
                                )
                                continue
                            results.append(
                                await score_command(
                                    CommandScorerSpec(key=key, argv=tuple(argv)),
                                    provisioned.path,
                                )
                            )
                        elif scorer_type == "file":
                            results.append(
                                score_file_assertion(
                                    FileAssertionSpec(
                                        key=key,
                                        path=str(raw.get("path", "")),
                                        assertion=raw.get("assertion", "exists"),
                                        expected=raw.get("expected"),
                                        json_path=raw.get("json_path"),
                                    ),
                                    provisioned.path,
                                )
                            )
                        elif scorer_type == "diff":
                            results.append(
                                score_diff_constraints(
                                    DiffConstraintSpec(
                                        key=key,
                                        allowed=tuple(raw.get("allowed", [])),
                                        forbidden=tuple(raw.get("forbidden", [])),
                                        required_paths=tuple(
                                            raw.get("required_paths", [])
                                        ),
                                    ),
                                    set(),
                                )
                            )
                        else:
                            problems.append(f"{key}: unsupported scorer type")
                except WorktreeError as exc:
                    problems.append(str(exc))
                finally:
                    if provisioned:
                        try:
                            await self.worktrees.cleanup(provisioned)
                        except WorktreeError as exc:
                            problems.append(f"Worktree cleanup failed: {exc}")
            if results and classify_required_scores(results) == "infra_error":
                problems.append("A scorer could not be evaluated")
            if (
                results
                and base_expectation == "required_scorer_fails"
                and all(
                    result.status == "pass" for result in results if result.required
                )
            ):
                problems.append("All required scorers already pass at the base commit")
            if (
                results
                and base_expectation == "required_scorer_passes"
                and any(
                    result.status != "pass" for result in results if result.required
                )
            ):
                problems.append("A required scorer does not pass at the base commit")
            revision.validation_status = "invalid" if problems else "valid"
            revision.validation_details_json = {
                "problems": problems,
                "held_out_paths": held_out_paths,
                "base_expectation": base_expectation,
                "base_results": [
                    {
                        "key": result.scorer_key,
                        "status": result.status,
                        "summary": result.summary,
                    }
                    for result in results
                ],
            }
            case.updated_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(case)
            await db.refresh(revision)
            return _case_payload(case, [revision])

        if method == "eval.case.publish":
            values = _params(EvalCaseRevisionParams, params)
            case, revision = await self._revision(
                db, values.case_id, values.revision_id
            )
            if revision.status != "draft":
                raise EvalServiceError(-32010, "Case revision is already published")
            if revision.validation_status != "valid" or not revision.scorer_spec_json:
                raise EvalServiceError(
                    -32010, "Validate the case successfully before publishing"
                )
            revision.content_hash = hashlib.sha256(
                self._canonical_content(revision)
            ).hexdigest()
            revision.status = "published"
            revision.published_at = datetime.now(UTC)
            case.updated_at = revision.published_at
            await db.commit()
            await db.refresh(case)
            await db.refresh(revision)
            return _case_payload(case, [revision])

        if method == "eval.case.list":
            cases = (
                await db.scalars(
                    select(models.EvalCase).order_by(models.EvalCase.updated_at.desc())
                )
            ).all()
            revisions = (
                await db.scalars(
                    select(models.EvalCaseRevision).order_by(
                        models.EvalCaseRevision.case_id,
                        models.EvalCaseRevision.revision.desc(),
                    )
                )
            ).all()
            by_case: dict[int, list[models.EvalCaseRevision]] = defaultdict(list)
            for revision in revisions:
                by_case[revision.case_id].append(revision)
            return [_case_payload(case, by_case[case.id]) for case in cases]

        if method == "eval.case.get":
            values = _params(EvalCaseIdParams, params)
            case = await db.get(models.EvalCase, values.case_id)
            if not case:
                raise EvalServiceError(-32004, "Eval case not found")
            revisions = (
                await db.scalars(
                    select(models.EvalCaseRevision).where(
                        models.EvalCaseRevision.case_id == case.id
                    )
                )
            ).all()
            return _case_payload(case, list(revisions))

        if method == "eval.case.update_draft":
            values = _params(EvalCaseUpdateDraft, params)
            case = await db.get(models.EvalCase, values.case_id)
            revision = await db.get(models.EvalCaseRevision, values.revision_id)
            if not case or not revision or revision.case_id != case.id:
                raise EvalServiceError(-32004, "Eval case draft not found")
            if revision.status != "draft":
                raise EvalServiceError(-32010, "Published case revisions are immutable")
            bundle = None
            if values.verifier_files:
                if not self.artifact_store:
                    raise EvalServiceError(-32020, "Artifact storage is unavailable")
                try:
                    bundle = build_verifier_bundle(
                        [file.model_dump() for file in values.verifier_files]
                    )
                except ValueError as exc:
                    raise EvalServiceError(-32602, str(exc)) from exc
            fields = values.model_fields_set
            if "title" in fields and values.title is not None:
                title = values.title.strip()
                if not title:
                    raise EvalServiceError(-32602, "Case title is required")
                case.title = title
            if "description" in fields and values.description is not None:
                case.description = values.description.strip()
            if "prompt" in fields and values.prompt is not None:
                prompt = values.prompt.strip()
                if not prompt:
                    raise EvalServiceError(-32602, "Case prompt is required")
                revision.prompt = prompt
            if "base_sha" in fields:
                if values.base_sha and not FULL_COMMIT_RE.fullmatch(values.base_sha):
                    raise EvalServiceError(-32602, "Base commit must be a full Git SHA")
                revision.base_sha = values.base_sha.lower() if values.base_sha else None
            if values.setup_spec is not None:
                revision.setup_spec_json = values.setup_spec
            if values.scorer_spec is not None:
                revision.scorer_spec_json = values.scorer_spec
            if values.path_policy is not None:
                revision.path_policy_json = values.path_policy
            if values.verifier_files is not None:
                if bundle is not None:
                    writer = self.artifact_store.open_case_writer(
                        revision.id,
                        "verifier_bundle",
                        {"held_out_paths": verifier_paths(bundle)},
                    )
                    try:
                        writer.write(bundle)
                        stored = writer.finish()
                    except OSError, RuntimeError, ValueError:
                        writer.abort()
                        raise
                    artifact = models.RunArtifact(
                        run_id=None,
                        artifact_type=stored.artifact_type,
                        relative_path=stored.relative_path,
                        sha256=stored.sha256,
                        byte_size=stored.byte_size,
                        metadata_json=stored.metadata,
                    )
                    db.add(artifact)
                    await db.flush()
                    revision.verifier_artifact_id = artifact.id
                else:
                    revision.verifier_artifact_id = None
            revision.validation_status = "not_validated"
            revision.validation_details_json = {}
            case.updated_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(case)
            await db.refresh(revision)
            return _case_payload(case, [revision])

        raise NotImplementedError(f"Unknown method: {method}")
