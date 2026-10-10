"""Registered cases RPC handlers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import models
from database.schemas import (
    EvalCaseCreate,
    EvalCaseCreateFromRun,
    EvalCaseIdParams,
    EvalCaseRevisionParams,
    EvalCaseUpdateDraft,
)
from evals.common import FULL_COMMIT_RE, EvalServiceError, _case_payload, _params
from evals.scorers import (
    CommandScorerSpec,
    DiffConstraintSpec,
    FileAssertionSpec,
    classify_required_scores,
    score_command,
    score_diff_constraints,
    score_file_assertion,
)
from evals.verifier_bundles import (
    build_verifier_bundle,
    materialize_verifier_bundle,
    verifier_paths,
)
from evals.worktrees import WorktreeError
from rpc_registry import rpc
from run_diffs import build_starting_patch


class CasesHandlers:
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
        except (FileNotFoundError, TimeoutError):
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

    @rpc("eval.case.create_from_run")
    async def _rpc_eval_case_create_from_run(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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
            await db.get(models.Workspace, session.workspace_id) if session else None
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
            except (OSError, RuntimeError, ValueError):
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
                if isinstance(item, dict) and item.get("type") == "command_execution"
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
            validation_details_json={"candidate_verifier_commands": candidates[:10]},
        )
        db.add(revision)
        await db.commit()
        await db.refresh(case)
        await db.refresh(revision)
        return _case_payload(case, [revision])

    @rpc("eval.case.create")
    async def _rpc_eval_case_create(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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

    @rpc("eval.case.revise")
    async def _rpc_eval_case_revise(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalCaseRevisionParams, params)
        case, source = await self._revision(db, values.case_id, values.revision_id)
        if source.status != "published":
            raise EvalServiceError(-32010, "Only published revisions can be revised")
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
            except (OSError, RuntimeError, ValueError):
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

    @rpc("eval.case.validate")
    async def _rpc_eval_case_validate(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalCaseRevisionParams, params)
        case, revision = await self._revision(db, values.case_id, values.revision_id)
        if revision.status != "draft":
            raise EvalServiceError(-32010, "Published revisions cannot be revalidated")
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
                        raise WorktreeError("Starting patch artifact is unavailable")
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
                                    required_paths=tuple(raw.get("required_paths", [])),
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
            and all(result.status == "pass" for result in results if result.required)
        ):
            problems.append("All required scorers already pass at the base commit")
        if (
            results
            and base_expectation == "required_scorer_passes"
            and any(result.status != "pass" for result in results if result.required)
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

    @rpc("eval.case.publish")
    async def _rpc_eval_case_publish(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(EvalCaseRevisionParams, params)
        case, revision = await self._revision(db, values.case_id, values.revision_id)
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

    @rpc("eval.case.list")
    async def _rpc_eval_case_list(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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

    @rpc("eval.case.get")
    async def _rpc_eval_case_get(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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

    @rpc("eval.case.update_draft")
    async def _rpc_eval_case_update_draft(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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
                except (OSError, RuntimeError, ValueError):
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
