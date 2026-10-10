"""Registered session RPC handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import models
from database.schemas import (
    MessageRecord,
    RunEventRecord,
    SessionCreate,
    SessionHistoryParams,
    SessionHistoryRecord,
    SessionIdParams,
    SessionRecord,
    SessionSend,
)
from rpc_contract import SessionListParams
from rpc_handlers.common import RpcMethodError, _params, _session_dict
from rpc_registry import rpc


class SessionHandlers:
    @rpc("session.create")
    async def _rpc_session_create(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(SessionCreate, params)
        workspace = await db.get(models.Workspace, values.workspace_id)
        if not workspace:
            raise RpcMethodError(-32004, "Workspace not found")
        session = models.Session(workspace_id=workspace.id, provider="codex")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return _session_dict(session)

    @rpc("session.list")
    async def _rpc_session_list(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(SessionListParams, params)
        query = select(models.Session).limit(values.limit)
        if values.before_id is not None:
            query = query.order_by(models.Session.id.desc())
            if values.before_id:
                query = query.where(models.Session.id < values.before_id)
        else:
            query = query.order_by(
                models.Session.updated_at.desc(), models.Session.id.desc()
            )
        if values.workspace_id is not None:
            query = query.where(models.Session.workspace_id == values.workspace_id)
        sessions = (await db.scalars(query)).all()
        return [_session_dict(session) for session in sessions]

    @rpc("session.get")
    async def _rpc_session_get(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(SessionIdParams, params)
        return _session_dict(await self._session(db, values.session_id))

    @rpc("session.delete")
    async def _rpc_session_delete(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(SessionIdParams, params)
        session = await self._session(db, values.session_id)
        if await self._has_active_run(db, session_id=session.id):
            raise RpcMethodError(
                -32010, "Stop the active run before deleting this session"
            )
        await db.delete(session)
        await db.commit()
        return {"deleted": True, "session_id": values.session_id}

    @rpc("session.history")
    async def _rpc_session_history(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(SessionHistoryParams, params)
        session = await self._session(db, values.session_id)
        messages = (
            await db.scalars(
                select(models.Message)
                .where(models.Message.session_id == session.id)
                .order_by(models.Message.id)
            )
        ).all()
        events = (
            await db.scalars(
                select(models.RunEvent)
                .where(
                    models.RunEvent.session_id == session.id,
                    models.RunEvent.id > values.after_sequence,
                )
                .order_by(models.RunEvent.id)
                .limit(values.limit + 1)
            )
        ).all()
        has_more = len(events) > values.limit
        events = events[: values.limit]
        return SessionHistoryRecord(
            session=SessionRecord.model_validate(session),
            conversation=[
                MessageRecord.model_validate(message) for message in messages
            ],
            events=[
                RunEventRecord(
                    id=event.id,
                    run_id=event.run_id,
                    sequence=event.id,
                    type=event.event_type,
                    payload=event.payload,
                    created_at=event.created_at,
                )
                for event in events
            ],
            last_sequence=events[-1].id if events else values.after_sequence,
            has_more=has_more,
        ).model_dump(mode="json")

    @rpc("session.send")
    async def _rpc_session_send(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(SessionSend, params)
        content = values.content.strip()
        if not content:
            raise ValueError("Message content is required")
        session = await self._session(db, values.session_id)
        workspace = await db.get(models.Workspace, session.workspace_id)
        if not workspace:
            raise RpcMethodError(-32004, "Workspace not found")
        async with self._workspace_locks.setdefault(workspace.id, asyncio.Lock()):
            # The initial lookup may predate another run that held this lock.
            await db.rollback()
            session = await self._session(db, values.session_id)
            workspace = await self._workspace(db, session.workspace_id)
            if await self._has_active_run(db, workspace_id=workspace.id):
                raise RpcMethodError(-32010, "Another run is active in this workspace")
            run = models.Run(
                kind="chat",
                session_id=session.id,
                workspace_path=workspace.path,
                status="queued",
                prompt=content,
            )
            db.add(run)
            await db.flush()
            db.add(
                models.Message(
                    session_id=session.id,
                    run_id=run.id,
                    role="user",
                    content=content,
                )
            )
            session.status = "running"
            if not session.title:
                session.title = content[:80]
            await db.commit()
            if self.diff_service:
                await self.diff_service.capture(run.id, workspace.path)
            try:
                await self.runtime.start(
                    session.id,
                    run.id,
                    workspace.path,
                    content,
                    session.codex_thread_id,
                    mode=values.mode,
                )
            except Exception as exc:
                await self._mark_run_start_failed(session.id, run.id, str(exc))
                if self.diff_service:
                    await self.diff_service.refresh(run.id, final=True)
                if isinstance(exc, RuntimeError) and str(exc).startswith("Codex CLI"):
                    raise RpcMethodError(-32020, str(exc)) from exc
                raise RpcMethodError(-32020, "Codex could not be started") from exc
            return {"accepted": True, "session_id": session.id, "run_id": run.id}

    @rpc("session.cancel", "session.stop")
    async def _rpc_session_cancel(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(SessionIdParams, params)
        await self._session(db, values.session_id)
        active_run_id = await db.scalar(
            select(models.Run.id)
            .where(
                models.Run.session_id == values.session_id,
                models.Run.status.in_(("queued", "running", "stopping")),
            )
            .order_by(models.Run.id.desc())
            .limit(1)
        )
        if active_run_id is None or not await self.runtime.cancel(active_run_id):
            raise RpcMethodError(-32011, "No active run exists for this session")
        return {"accepted": True, "session_id": values.session_id}

    @rpc("session.subscribe", "session.unsubscribe")
    async def _rpc_session_subscribe(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        values = _params(SessionIdParams, params)
        await self._session(db, values.session_id)
        return {
            "session_id": values.session_id,
            "subscribed": method == "session.subscribe",
        }
