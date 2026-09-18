import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_runtime import AgentRuntimeManager, CommandAgentAdapter, FakeAgentAdapter
from database import Base, SessionLocal, engine, get_db, models
from database.schemas import RpcRequest
from event_broker import AgentEvent, EventBroker
from settings import settings


def _timestamp(value: Any) -> str | None:
    return value.isoformat() if value else None


def _workspace_dict(workspace: models.Workspace) -> dict[str, Any]:
    return {"id": workspace.id, "path": workspace.path, "name": workspace.name, "created_at": _timestamp(workspace.created_at)}


def _session_dict(session: models.Session) -> dict[str, Any]:
    return {
        "id": session.id,
        "workspace_id": session.workspace_id,
        "provider": session.provider,
        "status": session.status,
        "created_at": _timestamp(session.created_at),
        "updated_at": _timestamp(session.updated_at),
    }


def _rpc_result(request_id: int | str | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: int | str | None, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _resolve_workspace(path: str) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError("Workspace path must be an existing directory")
    return str(resolved)


class RpcDispatcher:
    def __init__(self, runtime: AgentRuntimeManager) -> None:
        self.runtime = runtime

    async def dispatch(self, request: RpcRequest, db: AsyncSession) -> dict[str, Any]:
        try:
            result = await self._dispatch_method(request.method, request.params, db)
            return _rpc_result(request.id, result)
        except KeyError as exc:
            return _rpc_error(request.id, -32602, str(exc))
        except ValueError as exc:
            return _rpc_error(request.id, -32602, str(exc))
        except NotImplementedError as exc:
            return _rpc_error(request.id, -32601, str(exc))
        except (OSError, RuntimeError, SQLAlchemyError) as exc:
            return _rpc_error(request.id, -32603, "Internal server error", str(exc))

    async def _dispatch_method(self, method: str, params: dict[str, Any], db: AsyncSession) -> Any:
        if method == "health.check":
            return {"status": "ok"}
        if method == "workspace.create":
            path = _resolve_workspace(str(params.get("path", "")))
            name = str(params.get("name", "")).strip()
            if not name:
                raise ValueError("Workspace name is required")
            workspace = models.Workspace(path=path, name=name)
            db.add(workspace)
            await db.commit()
            await db.refresh(workspace)
            return _workspace_dict(workspace)
        if method == "workspace.list":
            workspaces = (await db.scalars(select(models.Workspace).order_by(models.Workspace.name))).all()
            return [_workspace_dict(workspace) for workspace in workspaces]
        if method == "workspace.get":
            workspace = await db.get(models.Workspace, int(params.get("workspace_id", 0)))
            if not workspace:
                raise KeyError("Workspace not found")
            return _workspace_dict(workspace)
        if method == "session.create":
            workspace = await db.get(models.Workspace, int(params.get("workspace_id", 0)))
            if not workspace:
                raise KeyError("Workspace not found")
            session = models.Session(workspace_id=workspace.id, provider=str(params.get("provider", "command")))
            db.add(session)
            await db.commit()
            await db.refresh(session)
            return _session_dict(session)
        if method == "session.list":
            sessions = (await db.scalars(select(models.Session).order_by(models.Session.updated_at.desc()))).all()
            return [_session_dict(session) for session in sessions]
        if method == "session.get":
            session = await db.get(models.Session, int(params.get("session_id", 0)))
            if not session:
                raise KeyError("Session not found")
            return _session_dict(session)
        if method == "session.history":
            session = await db.get(models.Session, int(params.get("session_id", 0)))
            if not session:
                raise KeyError("Session not found")
            after_sequence = int(params.get("after_sequence", 0))
            events = (await db.scalars(select(models.SessionEvent).where(models.SessionEvent.session_id == session.id, models.SessionEvent.sequence > after_sequence).order_by(models.SessionEvent.sequence))).all()
            return {"session": _session_dict(session), "conversation": session.conversation, "events": [{"id": event.id, "sequence": event.sequence, "type": event.event_type, "payload": event.payload, "text": event.text, "created_at": _timestamp(event.created_at)} for event in events], "last_sequence": max((event.sequence for event in events), default=after_sequence)}
        if method == "session.send":
            session = await db.get(models.Session, int(params.get("session_id", 0)))
            if not session:
                raise KeyError("Session not found")
            content = str(params.get("content", "")).strip()
            if not content:
                raise ValueError("Message content is required")
            workspace = await db.get(models.Workspace, session.workspace_id)
            if not workspace:
                raise KeyError("Workspace not found")
            session.conversation = [*session.conversation, {"role": "user", "content": content}]
            session.status = "running"
            await db.commit()
            await self.runtime.start(session.id, workspace.path)
            await self.runtime.send(session.id, content)
            return {"accepted": True, "session_id": session.id}
        if method in {"session.cancel", "session.stop"}:
            session = await db.get(models.Session, int(params.get("session_id", 0)))
            if not session:
                raise KeyError("Session not found")
            await self.runtime.cancel(session.id)
            session.status = "cancelled"
            await db.commit()
            return {"accepted": True, "session_id": session.id}
        if method in {"session.subscribe", "session.unsubscribe"}:
            session = await db.get(models.Session, int(params.get("session_id", 0)))
            if not session:
                raise KeyError("Session not found")
            return {"session_id": session.id, "subscribed": method == "session.subscribe"}
        raise NotImplementedError(f"Unknown method: {method}")


async def persist_event(event: AgentEvent) -> None:
    async with SessionLocal() as db:
        session = await db.get(models.Session, event.session_id)
        if not session:
            return
        text = event.payload.get("content") if event.type == "assistant.text" else None
        db.add(models.SessionEvent(session_id=event.session_id, sequence=event.sequence, event_type=event.type, payload=event.payload, text=text))
        if event.type == "assistant.text" and text:
            session.conversation = [*session.conversation, {"role": "assistant", "content": text}]
        if event.type == "session.completed":
            session.status = "completed"
        elif event.type == "session.failed":
            session.status = "failed"
        elif event.type == "session.stopping":
            session.status = "stopping"
        elif event.type == "session.cancelled":
            session.status = "cancelled"
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()"))
        await connection.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS provider VARCHAR DEFAULT 'command'"))
        await connection.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'idle'"))
        await connection.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS conversation JSONB DEFAULT '[]'::jsonb"))
        await connection.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()"))
        await connection.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()"))
        await connection.execute(text("ALTER TABLE session_events ADD COLUMN IF NOT EXISTS sequence INTEGER"))
        await connection.execute(text("UPDATE session_events SET sequence = id WHERE sequence IS NULL"))
        await connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_session_events_sequence ON session_events (session_id, sequence)"))
    broker = EventBroker()
    adapter = FakeAgentAdapter() if settings.agent_mode == "fake" else CommandAgentAdapter(settings.agent_command)
    runtime = AgentRuntimeManager(broker, adapter, persist_event)
    app.state.broker = broker
    app.state.runtime = runtime
    app.state.dispatcher = RpcDispatcher(runtime)
    yield
    await runtime.shutdown()
    await engine.dispose()


app = FastAPI(title="Agent Harness", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
db_dependency = Depends(get_db)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/rpc")
async def rpc(request: RpcRequest, db: AsyncSession = db_dependency) -> JSONResponse:
    response = await app.state.dispatcher.dispatch(request, db)
    return JSONResponse(response)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    send_lock = asyncio.Lock()
    subscriptions: dict[int, asyncio.Task[None]] = {}

    async def send_json(message: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(message)

    async def forward_events(session_id: int) -> None:
        async with app.state.broker.subscribe(session_id) as queue:
            while True:
                event = await queue.get()
                await send_json({"jsonrpc": "2.0", "method": "session.event", "params": event.as_dict()})

    try:
        while True:
            request = RpcRequest.model_validate_json(await websocket.receive_text())
            async with SessionLocal() as db:
                response = await app.state.dispatcher.dispatch(request, db)
            await send_json(response)
            if request.method == "session.subscribe" and response.get("result", {}).get("subscribed"):
                session_id = int(request.params.get("session_id", 0))
                if session_id not in subscriptions:
                    subscriptions[session_id] = asyncio.create_task(forward_events(session_id))
                    await asyncio.sleep(0)
            elif request.method == "session.unsubscribe":
                session_id = int(request.params.get("session_id", 0))
                task = subscriptions.pop(session_id, None)
                if task:
                    task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        for task in subscriptions.values():
            task.cancel()
        await asyncio.gather(*subscriptions.values(), return_exceptions=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8000")), reload=True)
