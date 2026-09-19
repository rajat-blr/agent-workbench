import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_runtime import AgentRuntimeManager, CodexAgentAdapter
from database import Base, SessionLocal, engine, get_db, models
from database.schemas import (
    MessageRecord,
    RpcRequest,
    SessionCreate,
    SessionEventRecord,
    SessionHistoryParams,
    SessionHistoryRecord,
    SessionIdParams,
    SessionRecord,
    SessionSend,
    WorkspaceCreate,
    WorkspaceIdParams,
    WorkspaceRecord,
    WorkspaceRename,
)
from event_broker import AgentEvent, EventBroker
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from settings import settings
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


def _workspace_dict(workspace: models.Workspace) -> dict[str, Any]:
    return WorkspaceRecord.model_validate(workspace).model_dump(mode="json")


def _session_dict(session: models.Session) -> dict[str, Any]:
    return SessionRecord.model_validate(session).model_dump(mode="json")


def _rpc_result(request_id: int | str | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(
    request_id: int | str | None, code: int, message: str, data: Any = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _resolve_workspace(path: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError("Workspace path must be an existing directory")
    return str(resolved)


async def _git_status(path: str) -> dict[str, Any]:
    async def run(*arguments: str) -> tuple[int, str]:
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                path,
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return 1, ""
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=4)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return 1, ""
        return process.returncode or 0, stdout.decode(errors="replace").strip()

    return_code, _ = await run("rev-parse", "--is-inside-work-tree")
    if return_code:
        return {"is_repository": False, "branch": None, "dirty_count": 0}
    _, branch = await run("branch", "--show-current")
    if not branch:
        _, branch = await run("rev-parse", "--short", "HEAD")
    _, changes = await run("status", "--porcelain")
    return {
        "is_repository": True,
        "branch": branch or "unknown",
        "dirty_count": len(changes.splitlines()) if changes else 0,
    }


def _params(model: type[BaseModel], values: dict[str, Any]) -> BaseModel:
    return model.model_validate(values)


class RpcMethodError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RpcDispatcher:
    def __init__(self, runtime: AgentRuntimeManager) -> None:
        self.runtime = runtime

    async def dispatch(self, request: RpcRequest, db: AsyncSession) -> dict[str, Any]:
        try:
            return _rpc_result(
                request.id,
                await self._dispatch_method(request.method, request.params, db),
            )
        except ValidationError as exc:
            return _rpc_error(
                request.id, -32602, "Invalid method parameters", exc.errors()
            )
        except RpcMethodError as exc:
            return _rpc_error(request.id, exc.code, exc.message)
        except ValueError as exc:
            return _rpc_error(request.id, -32602, str(exc))
        except IntegrityError:
            await db.rollback()
            return _rpc_error(
                request.id, -32009, "The requested resource already exists"
            )
        except NotImplementedError as exc:
            return _rpc_error(request.id, -32601, str(exc))
        except OSError, RuntimeError, SQLAlchemyError:
            await db.rollback()
            return _rpc_error(request.id, -32603, "Internal server error")

    async def _session(self, db: AsyncSession, session_id: int) -> models.Session:
        session = await db.get(models.Session, session_id)
        if not session:
            raise RpcMethodError(-32004, "Session not found")
        return session

    async def _workspace(self, db: AsyncSession, workspace_id: int) -> models.Workspace:
        workspace = await db.get(models.Workspace, workspace_id)
        if not workspace:
            raise RpcMethodError(-32004, "Workspace not found")
        return workspace

    async def _has_active_run(
        self,
        db: AsyncSession,
        *,
        session_id: int | None = None,
        workspace_id: int | None = None,
    ) -> bool:
        query = (
            select(models.Run.id)
            .join(models.Session)
            .where(models.Run.status.in_(("queued", "running", "stopping")))
        )
        if session_id is not None:
            query = query.where(models.Run.session_id == session_id)
        if workspace_id is not None:
            query = query.where(models.Session.workspace_id == workspace_id)
        return await db.scalar(query) is not None

    async def _dispatch_method(
        self, method: str, params: dict[str, Any], db: AsyncSession
    ) -> Any:
        if method == "health.check":
            await db.execute(text("SELECT 1"))
            return {"status": "ok"}
        if method == "workspace.create":
            values = _params(WorkspaceCreate, params)
            if not values.name.strip():
                raise ValueError("Workspace name is required")
            workspace = models.Workspace(
                path=_resolve_workspace(values.path), name=values.name.strip()
            )
            db.add(workspace)
            await db.commit()
            await db.refresh(workspace)
            return _workspace_dict(workspace)
        if method == "workspace.list":
            workspaces = (
                await db.scalars(
                    select(models.Workspace).order_by(models.Workspace.name)
                )
            ).all()
            return [_workspace_dict(workspace) for workspace in workspaces]
        if method == "workspace.get":
            values = _params(WorkspaceIdParams, params)
            return _workspace_dict(await self._workspace(db, values.workspace_id))
        if method == "workspace.rename":
            values = _params(WorkspaceRename, params)
            if not values.name.strip():
                raise ValueError("Workspace name is required")
            workspace = await self._workspace(db, values.workspace_id)
            workspace.name = values.name.strip()
            await db.commit()
            await db.refresh(workspace)
            return _workspace_dict(workspace)
        if method == "workspace.git_status":
            values = _params(WorkspaceIdParams, params)
            workspace = await self._workspace(db, values.workspace_id)
            return await _git_status(workspace.path)
        if method == "workspace.delete":
            values = _params(WorkspaceIdParams, params)
            workspace = await self._workspace(db, values.workspace_id)
            if await self._has_active_run(db, workspace_id=workspace.id):
                raise RpcMethodError(
                    -32010, "Stop active sessions before removing this workspace"
                )
            await db.delete(workspace)
            await db.commit()
            return {"deleted": True, "workspace_id": values.workspace_id}
        if method == "session.create":
            values = _params(SessionCreate, params)
            workspace = await db.get(models.Workspace, values.workspace_id)
            if not workspace:
                raise RpcMethodError(-32004, "Workspace not found")
            session = models.Session(workspace_id=workspace.id, provider="codex")
            db.add(session)
            await db.commit()
            await db.refresh(session)
            return _session_dict(session)
        if method == "session.list":
            query = (
                select(models.Session)
                .order_by(models.Session.updated_at.desc())
                .limit(500)
            )
            if params.get("workspace_id") is not None:
                query = query.where(
                    models.Session.workspace_id == int(params["workspace_id"])
                )
            sessions = (await db.scalars(query)).all()
            return [_session_dict(session) for session in sessions]
        if method == "session.get":
            values = _params(SessionIdParams, params)
            return _session_dict(await self._session(db, values.session_id))
        if method == "session.delete":
            values = _params(SessionIdParams, params)
            session = await self._session(db, values.session_id)
            if await self._has_active_run(db, session_id=session.id):
                raise RpcMethodError(
                    -32010, "Stop the active run before deleting this session"
                )
            await db.delete(session)
            await db.commit()
            return {"deleted": True, "session_id": values.session_id}
        if method == "session.history":
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
                    select(models.SessionEvent)
                    .where(
                        models.SessionEvent.session_id == session.id,
                        models.SessionEvent.id > values.after_sequence,
                    )
                    .order_by(models.SessionEvent.id)
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
                    SessionEventRecord(
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
        if method == "session.send":
            values = _params(SessionSend, params)
            content = values.content.strip()
            if not content:
                raise ValueError("Message content is required")
            session = await self._session(db, values.session_id)
            workspace = await db.get(models.Workspace, session.workspace_id)
            if not workspace:
                raise RpcMethodError(-32004, "Workspace not found")
            active_run = await db.scalar(
                select(models.Run.id).where(
                    models.Run.session_id == session.id,
                    models.Run.status.in_(("queued", "running", "stopping")),
                )
            )
            if active_run:
                raise RpcMethodError(-32010, "A run is already active for this session")
            run = models.Run(session_id=session.id, status="queued", prompt=content)
            db.add(run)
            await db.flush()
            db.add(
                models.Message(
                    session_id=session.id, run_id=run.id, role="user", content=content
                )
            )
            session.status = "running"
            if not session.title:
                session.title = content[:80]
            await db.commit()
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
                await mark_run_start_failed(session.id, run.id, str(exc))
                if isinstance(exc, RuntimeError) and str(exc).startswith("Codex CLI"):
                    raise RpcMethodError(-32020, str(exc)) from exc
                raise RpcMethodError(-32020, "Codex could not be started") from exc
            return {"accepted": True, "session_id": session.id, "run_id": run.id}
        if method in {"session.cancel", "session.stop"}:
            values = _params(SessionIdParams, params)
            await self._session(db, values.session_id)
            if not await self.runtime.cancel(values.session_id):
                raise RpcMethodError(-32011, "No active run exists for this session")
            return {"accepted": True, "session_id": values.session_id}
        if method in {"session.subscribe", "session.unsubscribe"}:
            values = _params(SessionIdParams, params)
            await self._session(db, values.session_id)
            return {
                "session_id": values.session_id,
                "subscribed": method == "session.subscribe",
            }
        raise NotImplementedError(f"Unknown method: {method}")


async def persist_event(
    session_id: int,
    run_id: int,
    event_type: str,
    payload: dict[str, Any],
    source_event_id: str | None,
) -> AgentEvent:
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        session = await db.get(models.Session, session_id)
        run = await db.get(models.Run, run_id)
        if not session or not run:
            raise RuntimeError("Cannot persist an event for a missing session or run")
        event = models.SessionEvent(
            session_id=session_id,
            run_id=run_id,
            source_event_id=source_event_id,
            event_type=event_type,
            payload=payload,
            created_at=now,
        )
        db.add(event)
        if event_type == "session.started":
            session.status = "running"
            run.status = "running"
            run.pid = payload.get("pid")
            run.started_at = now
        elif event_type == "codex.thread.started":
            thread_id = payload.get("thread_id")
            if isinstance(thread_id, str):
                session.codex_thread_id = thread_id
        elif event_type == "assistant.text":
            content = payload.get("content")
            if isinstance(content, str) and content:
                db.add(
                    models.Message(
                        session_id=session_id,
                        run_id=run_id,
                        role="assistant",
                        content=content,
                    )
                )
        elif event_type == "session.stopping":
            session.status = "stopping"
            run.status = "stopping"
        elif event_type in {"session.completed", "session.failed", "session.cancelled"}:
            status = event_type.removeprefix("session.")
            session.status = status
            run.status = status
            run.return_code = payload.get("return_code")
            run.error = payload.get("error")
            run.completed_at = now
        await db.commit()
        await db.refresh(event)
        return AgentEvent(
            session_id=session_id,
            run_id=run_id,
            type=event_type,
            payload=payload,
            sequence=event.id,
            created_at=now.isoformat(),
        )


async def mark_run_start_failed(session_id: int, run_id: int, error: str) -> None:
    async with SessionLocal() as db:
        now = datetime.now(UTC)
        run = await db.get(models.Run, run_id)
        session = await db.get(models.Session, session_id)
        if run:
            run.status = "failed"
            run.error = error[:2000]
            run.completed_at = now
        if session:
            session.status = "failed"
        await db.commit()


async def reconcile_interrupted_runs() -> None:
    async with SessionLocal() as db:
        now = datetime.now(UTC)
        await db.execute(
            update(models.Run)
            .where(models.Run.status.in_(("queued", "running", "stopping")))
            .values(
                status="failed",
                error="Backend stopped before this run completed",
                completed_at=now,
            )
        )
        await db.execute(
            update(models.Session)
            .where(models.Session.status.in_(("running", "stopping")))
            .values(status="failed", updated_at=now)
        )
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.local_auth_token:
        raise RuntimeError("LOCAL_AUTH_TOKEN is required")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await reconcile_interrupted_runs()
    broker = EventBroker()
    adapter = CodexAgentAdapter(
        command=settings.codex_command,
        model=settings.codex_model,
        sandbox=settings.agent_sandbox,
        skip_git_repo_check=settings.codex_skip_git_repo_check,
    )
    runtime = AgentRuntimeManager(
        broker, adapter, persist_event, timeout_seconds=settings.agent_timeout_seconds
    )
    app.state.broker = broker
    app.state.runtime = runtime
    app.state.dispatcher = RpcDispatcher(runtime)
    yield
    await runtime.shutdown()
    await engine.dispose()


app = FastAPI(title="Agent Workbench", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)
db_dependency = Depends(get_db)


def _valid_token(candidate: str) -> bool:
    return bool(settings.local_auth_token) and secrets.compare_digest(
        candidate, settings.local_auth_token
    )


async def require_http_auth(authorization: str | None = Header(default=None)) -> None:
    prefix = "Bearer "
    if (
        not authorization
        or not authorization.startswith(prefix)
        or not _valid_token(authorization.removeprefix(prefix))
    ):
        raise HTTPException(
            status_code=401, detail="Invalid local authentication token"
        )


@app.get("/health")
async def health() -> dict[str, str]:
    async with SessionLocal() as db:
        await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/rpc", dependencies=[Depends(require_http_auth)])
async def rpc(request: RpcRequest, db: AsyncSession = db_dependency) -> JSONResponse:
    return JSONResponse(await app.state.dispatcher.dispatch(request, db))


def _valid_origin(origin: str | None) -> bool:
    if origin is None:
        return False
    return origin in settings.allowed_origin_list or (
        origin.startswith("file://") and "file://" in settings.allowed_origin_list
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    protocols = {
        protocol.strip()
        for protocol in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if protocol.strip()
    }
    auth_protocol = next(
        (protocol for protocol in protocols if protocol.startswith("auth.")), ""
    )
    if (
        "agent-workbench" not in protocols
        or not _valid_token(auth_protocol.removeprefix("auth."))
        or not _valid_origin(websocket.headers.get("origin"))
    ):
        await websocket.close(code=1008, reason="Unauthorized local client")
        return
    await websocket.accept(subprotocol="agent-workbench")
    send_lock = asyncio.Lock()
    subscriptions: dict[int, asyncio.Task[None]] = {}

    async def send_json(message: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(message)

    async def forward_events(session_id: int, ready: asyncio.Event) -> None:
        async with app.state.broker.subscribe(session_id) as queue:
            ready.set()
            while True:
                event = await queue.get()
                await send_json(
                    {
                        "jsonrpc": "2.0",
                        "method": "session.event",
                        "params": event.as_dict(),
                    }
                )

    try:
        while True:
            raw_request = await websocket.receive_text()
            try:
                request = RpcRequest.model_validate_json(raw_request)
            except (ValidationError, json.JSONDecodeError) as exc:
                await send_json(
                    _rpc_error(None, -32600, "Invalid JSON-RPC request", str(exc))
                )
                continue
            async with SessionLocal() as db:
                response = await app.state.dispatcher.dispatch(request, db)
            if request.method == "session.subscribe" and response.get("result", {}).get(
                "subscribed"
            ):
                session_id = int(request.params["session_id"])
                if session_id not in subscriptions:
                    ready = asyncio.Event()
                    subscriptions[session_id] = asyncio.create_task(
                        forward_events(session_id, ready)
                    )
                    await ready.wait()
            elif request.method == "session.unsubscribe":
                session_id = int(request.params.get("session_id", 0))
                task = subscriptions.pop(session_id, None)
                if task:
                    task.cancel()
            await send_json(response)
    except WebSocketDisconnect:
        pass
    finally:
        for task in subscriptions.values():
            task.cancel()
        await asyncio.gather(*subscriptions.values(), return_exceptions=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
