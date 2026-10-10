"""Evals service composition and constant-time registered RPC routing."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from artifacts import ArtifactStore
from evals.attempts import AttemptsHandlers
from evals.cases import CasesHandlers
from evals.common import EvalServiceError, _revision_payload
from evals.configs import ConfigsHandlers
from evals.experiments import ExperimentsHandlers
from evals.scheduler import EvalScheduler
from evals.suites import SuitesHandlers
from evals.worktrees import WorktreeService
from rpc_registry import bind_handlers

__all__ = ["EvalService", "EvalServiceError", "_revision_payload"]


class EvalService(
    CasesHandlers,
    ExperimentsHandlers,
    AttemptsHandlers,
    SuitesHandlers,
    ConfigsHandlers,
):
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
        self._rpc_handlers = bind_handlers(self)

    async def dispatch(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        handler = self._rpc_handlers.get(method)
        if handler is None:
            raise NotImplementedError(f"Unknown method: {method}")
        return await handler(method, params, db)
