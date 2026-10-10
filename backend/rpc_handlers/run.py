"""Registered run RPC handlers."""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import models
from database.schemas import (
    RunArtifactRecord,
    RunDiffParams,
    RunEventRecord,
    RunEventsParams,
    RunIdParams,
)
from rpc_handlers.common import RpcMethodError, _params, _run_dict
from rpc_registry import rpc


class RunHandlers:
    @rpc("run.get")
    async def _rpc_run_get(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(RunIdParams, params)
        run = await db.get(models.Run, values.run_id)
        if not run:
            raise RpcMethodError(-32004, "Run not found")
        return _run_dict(run)

    @rpc("run.events")
    async def _rpc_run_events(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(RunEventsParams, params)
        run = await db.get(models.Run, values.run_id)
        if not run:
            raise RpcMethodError(-32004, "Run not found")
        events = (
            await db.scalars(
                select(models.RunEvent)
                .where(
                    models.RunEvent.run_id == run.id,
                    models.RunEvent.id > values.after_sequence,
                )
                .order_by(models.RunEvent.id)
                .limit(values.limit + 1)
            )
        ).all()
        has_more = len(events) > values.limit
        events = events[: values.limit]
        return {
            "run": _run_dict(run),
            "events": [
                RunEventRecord(
                    id=event.id,
                    run_id=event.run_id,
                    sequence=event.id,
                    type=event.event_type,
                    payload=event.payload,
                    created_at=event.created_at,
                ).model_dump(mode="json")
                for event in events
            ],
            "last_sequence": events[-1].id if events else values.after_sequence,
            "has_more": has_more,
        }

    @rpc("run.artifacts")
    async def _rpc_run_artifacts(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(RunIdParams, params)
        run = await db.get(models.Run, values.run_id)
        if not run:
            raise RpcMethodError(-32004, "Run not found")
        artifacts = (
            await db.scalars(
                select(models.RunArtifact)
                .where(models.RunArtifact.run_id == run.id)
                .order_by(models.RunArtifact.id)
            )
        ).all()
        return [
            RunArtifactRecord.model_validate(artifact).model_dump(mode="json")
            for artifact in artifacts
        ]

    @rpc("run.diff.get")
    async def _rpc_run_diff_get(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(RunDiffParams, params)
        run = await db.get(models.Run, values.run_id)
        if not run or run.session_id != values.session_id:
            raise RpcMethodError(-32004, "Run not found in this session")
        if not self.diff_service:
            raise RpcMethodError(-32011, "Diff service is unavailable")
        await self.diff_service.refresh(
            run.id, final=run.status not in {"queued", "running", "stopping"}
        )
        result = await self.diff_service.get(run.id)
        return result or {
            "run_id": run.id,
            "status": "unavailable",
            "final": True,
            "reason": "A diff was not captured for this earlier run",
            "files": [],
            "file_count": 0,
            "added": 0,
            "deleted": 0,
            "captured_at": None,
        }

    @rpc("run.diff.accept", "run.diff.revert")
    async def _rpc_run_diff_accept(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(RunDiffParams, params)
        run = await db.get(models.Run, values.run_id)
        if not run or run.session_id != values.session_id:
            raise RpcMethodError(-32004, "Run not found in this session")
        if not self.diff_service:
            raise RpcMethodError(-32011, "Diff service is unavailable")
        session = await self._session(db, values.session_id)
        workspace_id = session.workspace_id
        async with self._workspace_locks.setdefault(workspace_id, asyncio.Lock()):
            await db.rollback()
            if await self._has_active_run(db, workspace_id=workspace_id):
                raise RpcMethodError(
                    -32010,
                    "Wait for the active run to finish before reviewing changes",
                )
            try:
                result = await self.diff_service.decide(
                    values.run_id,
                    "accept" if method.endswith("accept") else "revert",
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                raise RpcMethodError(-32012, str(exc)[:300]) from exc
            if not result:
                raise RpcMethodError(-32004, "No review was captured for this run")
            return result
