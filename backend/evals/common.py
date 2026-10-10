"""Shared Evals errors and payload helpers."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from database import models
from evals.configuration import redact_text, reproducibility_warnings

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
