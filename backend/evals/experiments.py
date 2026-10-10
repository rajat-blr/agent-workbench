"""Registered experiments RPC handlers."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import models
from database.schemas import (
    EvalExperimentEventsParams,
    EvalExperimentIdParams,
    EvalExperimentPlan,
)
from evals.common import EvalServiceError, _params
from evals.configuration import controlled_execution, reproducibility_warnings
from evals.statistics import summarize_results
from rpc_registry import rpc


class ExperimentsHandlers:
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

    @rpc("eval.experiment.preflight")
    async def _rpc_eval_experiment_preflight(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalExperimentPlan, params)
        _, _, _, preflight = await self._experiment_inputs(db, values)
        return preflight

    @rpc("eval.experiment.create")
    async def _rpc_eval_experiment_create(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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
        name = values.name.strip() or f"{suite.name if suite else 'Suite'} comparison"
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

    @rpc("eval.experiment.list")
    async def _rpc_eval_experiment_list(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        experiments = (
            await db.scalars(
                select(models.EvalExperiment).order_by(
                    models.EvalExperiment.created_at.desc()
                )
            )
        ).all()
        return [await self._experiment_payload(db, item) for item in experiments]

    @rpc("eval.experiment.get")
    async def _rpc_eval_experiment_get(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalExperimentIdParams, params)
        experiment = await db.get(models.EvalExperiment, values.experiment_id)
        if not experiment:
            raise EvalServiceError(-32004, "Eval experiment not found")
        return await self._experiment_payload(db, experiment)

    @rpc("eval.experiment.start")
    async def _rpc_eval_experiment_start(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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

    @rpc("eval.experiment.cancel")
    async def _rpc_eval_experiment_cancel(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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

    @rpc("eval.experiment.resume")
    async def _rpc_eval_experiment_resume(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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

    @rpc("eval.experiment.subscribe", "eval.experiment.unsubscribe")
    async def _rpc_eval_experiment_subscribe(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalExperimentIdParams, params)
        if not await db.get(models.EvalExperiment, values.experiment_id):
            raise EvalServiceError(-32004, "Eval experiment not found")
        return {
            "experiment_id": values.experiment_id,
            "subscribed": method.endswith("subscribe")
            and not method.endswith("unsubscribe"),
        }

    @rpc("eval.experiment.events")
    async def _rpc_eval_experiment_events(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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
