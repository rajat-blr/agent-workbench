"""Registered configs RPC handlers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import models
from database.schemas import EvalConfigCapture, EvalConfigDiffParams, EvalConfigIdParams
from evals.common import EvalServiceError, _config_payload, _params, _redact
from evals.configuration import (
    capture_instruction_files,
    controlled_execution,
    detect_cli_version,
)
from evals.worktrees import WorktreeError
from rpc_registry import rpc


class ConfigsHandlers:
    @rpc("eval.config.capture")
    async def _rpc_eval_config_capture(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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
            workspace_path = await asyncio.to_thread(Path(workspace.path).resolve)
            if not await asyncio.to_thread(workspace_path.is_dir):
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
            codex_home = await asyncio.to_thread(
                lambda: Path(
                    os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
                ).expanduser()
            )
            captured, notices = await asyncio.to_thread(
                capture_instruction_files,
                workspace_path,
                root,
                codex_home,
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

    @rpc("eval.config.list")
    async def _rpc_eval_config_list(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        configs = (
            await db.scalars(
                select(models.EvalConfig).order_by(models.EvalConfig.created_at.desc())
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

    @rpc("eval.config.get")
    async def _rpc_eval_config_get(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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

    @rpc("eval.config.diff")
    async def _rpc_eval_config_diff(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
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
