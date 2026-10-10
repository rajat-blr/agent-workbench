"""Shared core RPC errors and payload helpers."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from database import models
from database.schemas import RunRecord, SessionRecord, WorkspaceRecord


def _workspace_dict(workspace: models.Workspace) -> dict[str, Any]:
    return WorkspaceRecord.model_validate(workspace).model_dump(mode="json")


def _session_dict(session: models.Session) -> dict[str, Any]:
    return SessionRecord.model_validate(session).model_dump(mode="json")


def _run_dict(run: models.Run) -> dict[str, Any]:
    return RunRecord.model_validate(run).model_dump(mode="json")


def _resolve_workspace(path: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError("Workspace path must be an existing directory")
    return str(resolved)


async def _run_git_action(path: str, *arguments: str) -> str:
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            path,
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
    except FileNotFoundError as exc:
        raise RpcMethodError(-32030, "Git is not installed") from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise RpcMethodError(-32030, "Git command timed out") from exc
    output = (stdout + b"\n" + stderr).decode(errors="replace").strip()
    output = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1***@", output)[:1500]
    if process.returncode:
        raise RpcMethodError(-32030, output or "Git command failed")
    return output


def _params(model: type[BaseModel], values: dict[str, Any]) -> BaseModel:
    return model.model_validate(values)


class RpcMethodError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
