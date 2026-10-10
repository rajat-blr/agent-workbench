import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

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
from pydantic import ValidationError
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_runtime import AgentRuntimeManager, CodexAgentAdapter
from artifacts import ArtifactStore, StoredArtifact
from database import SessionLocal, engine, get_db, models
from database.migrations import run_migrations
from database.schemas import (
    RpcRequest,
    RunArtifactRecord,
)
from evals.scheduler import (
    EvalScheduler,
    reconcile_eval_worktrees,
    reconcile_interrupted_evals,
)
from evals.service import EvalService, EvalServiceError
from evals.worktrees import WorktreeService
from event_broker import AgentEvent, EventBroker
from event_payloads import event_payload_preview
from rpc_contract import RESULT_ADAPTERS, RPC_METHODS
from rpc_handlers.common import RpcMethodError
from rpc_handlers.health import HealthHandlers
from rpc_handlers.run import RunHandlers
from rpc_handlers.session import SessionHandlers
from rpc_handlers.workspace import WorkspaceHandlers
from rpc_registry import bind_handlers
from run_diffs import RunDiffService
from settings import settings


def _rpc_result(request_id: int | str | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(
    request_id: int | str | None, code: int, message: str, data: Any = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


class RpcDispatcher(HealthHandlers, WorkspaceHandlers, SessionHandlers, RunHandlers):
    def __init__(
        self,
        runtime: AgentRuntimeManager,
        diff_service: RunDiffService | None = None,
        artifact_store: ArtifactStore | None = None,
        event_broker: EventBroker | None = None,
        worktrees: WorktreeService | None = None,
    ) -> None:
        self.runtime = runtime
        self.diff_service = diff_service
        worktrees = worktrees or WorktreeService(
            settings.resolved_eval_worktree_directory
        )
        self.eval_scheduler = EvalScheduler(
            SessionLocal,
            runtime,
            worktrees,
            diff_service,
            artifact_store,
            event_broker,
        )
        self.eval_service = EvalService(
            worktrees,
            self.eval_scheduler,
            artifact_store,
            cli_command=settings.codex_command,
        )
        self._repository_import_locks: dict[str, asyncio.Lock] = {}
        self._workspace_locks: dict[int, asyncio.Lock] = {}
        self._rpc_handlers = bind_handlers(self)

    async def dispatch(self, request: RpcRequest, db: AsyncSession) -> dict[str, Any]:
        try:
            contract = RPC_METHODS.get(request.method)
            if contract is None:
                raise NotImplementedError(f"Unknown method: {request.method}")
            contract.params.model_validate(request.params)
            result = await self._dispatch_method(request.method, request.params, db)
            try:
                RESULT_ADAPTERS[request.method].validate_json(
                    json.dumps(result), strict=True
                )
            except (ValidationError, TypeError):
                # Response bugs are internal errors, never invalid client input.
                raise RpcMethodError(-32603, "Response contract mismatch") from None
            return _rpc_result(request.id, result)
        except ValidationError as exc:
            return _rpc_error(
                request.id, -32602, "Invalid method parameters", exc.errors()
            )
        except RpcMethodError as exc:
            return _rpc_error(request.id, exc.code, exc.message)
        except EvalServiceError as exc:
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
        except (OSError, RuntimeError, SQLAlchemyError):
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
        if method.startswith("eval."):
            return await self.eval_service.dispatch(method, params, db)
        handler = self._rpc_handlers.get(method)
        if handler is None:
            raise NotImplementedError(f"Unknown method: {method}")
        return await handler(method, params, db)

    async def _mark_run_start_failed(
        self, session_id: int, run_id: int, error: str
    ) -> None:
        await mark_run_start_failed(session_id, run_id, error)


async def persist_event(
    session_id: int | None,
    run_id: int,
    event_type: str,
    payload: dict[str, Any],
    source_event_id: str | None,
) -> AgentEvent:
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        session = await db.get(models.Session, session_id) if session_id else None
        run = await db.get(models.Run, run_id)
        if not run or run.session_id != session_id:
            raise RuntimeError(
                "Cannot persist an event for a missing or mismatched run"
            )
        payload_preview = event_payload_preview(payload)
        event = models.RunEvent(
            session_id=session_id,
            run_id=run_id,
            source_event_id=source_event_id,
            event_type=event_type,
            payload=payload_preview,
            created_at=now,
        )
        db.add(event)
        if event_type == "session.started":
            if session:
                session.status = "running"
            run.status = "running"
            run.pid = payload.get("pid")
            run.started_at = now
        elif event_type == "codex.thread.started":
            thread_id = payload.get("thread_id")
            if session and isinstance(thread_id, str):
                session.codex_thread_id = thread_id
        elif event_type == "assistant.text":
            content = payload.get("content")
            if session and isinstance(content, str) and content:
                db.add(
                    models.Message(
                        session_id=session_id,
                        run_id=run_id,
                        role="assistant",
                        content=content,
                    )
                )
        elif event_type == "session.stopping":
            if session:
                session.status = "stopping"
            run.status = "stopping"
        elif event_type in {"session.completed", "session.failed", "session.cancelled"}:
            status = event_type.removeprefix("session.")
            if session:
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
            payload=payload_preview,
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


async def persist_artifact(run_id: int, artifact: StoredArtifact) -> dict[str, Any]:
    async with SessionLocal() as db:
        if not await db.get(models.Run, run_id):
            raise RuntimeError("Cannot persist an artifact for a missing run")
        record = models.RunArtifact(
            run_id=run_id,
            artifact_type=artifact.artifact_type,
            relative_path=artifact.relative_path,
            sha256=artifact.sha256,
            byte_size=artifact.byte_size,
            metadata_json=artifact.metadata,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return RunArtifactRecord.model_validate(record).model_dump(mode="json")


async def reconcile_interrupted_runs() -> None:
    async with SessionLocal() as db:
        now = datetime.now(UTC)
        interrupted_run_ids = (
            await db.scalars(
                select(models.Run.id).where(
                    models.Run.status.in_(("queued", "running", "stopping"))
                )
            )
        ).all()
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
        if interrupted_run_ids:
            await db.execute(
                update(models.RunDiff)
                .where(models.RunDiff.run_id.in_(interrupted_run_ids))
                .values(
                    status="unavailable",
                    reason="Backend stopped before the run diff was finalized",
                    baseline=None,
                    final=True,
                    updated_at=now,
                )
            )
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.local_auth_token:
        raise RuntimeError("LOCAL_AUTH_TOKEN is required")
    await run_migrations(engine, database_url=settings.database_url)
    await reconcile_interrupted_runs()
    await reconcile_interrupted_evals(SessionLocal)
    worktrees = WorktreeService(settings.resolved_eval_worktree_directory)
    await reconcile_eval_worktrees(SessionLocal, worktrees)
    broker = EventBroker()
    adapter = CodexAgentAdapter(
        command=settings.codex_command,
        model=settings.codex_model,
        sandbox=settings.agent_sandbox,
        skip_git_repo_check=settings.codex_skip_git_repo_check,
    )
    diff_service = RunDiffService(SessionLocal)
    artifact_store = ArtifactStore(settings.resolved_artifact_directory)
    runtime = AgentRuntimeManager(
        broker,
        adapter,
        persist_event,
        timeout_seconds=settings.agent_timeout_seconds,
        diff_finalizer=lambda run_id: diff_service.refresh(run_id, final=True),
        artifact_store=artifact_store,
        artifact_persister=persist_artifact,
    )
    app.state.broker = broker
    app.state.runtime = runtime
    app.state.dispatcher = RpcDispatcher(
        runtime, diff_service, artifact_store, broker, worktrees
    )
    try:
        yield
    finally:
        await app.state.dispatcher.eval_scheduler.shutdown()
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
    experiment_subscriptions: dict[int, asyncio.Task[None]] = {}

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

    async def forward_experiment_events(
        experiment_id: int, ready: asyncio.Event
    ) -> None:
        async with app.state.broker.subscribe_experiment(experiment_id) as queue:
            ready.set()
            while True:
                event = await queue.get()
                await send_json(
                    {
                        "jsonrpc": "2.0",
                        "method": "eval.experiment.event",
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
            elif request.method == "eval.experiment.subscribe" and response.get(
                "result", {}
            ).get("subscribed"):
                experiment_id = int(request.params["experiment_id"])
                if experiment_id not in experiment_subscriptions:
                    ready = asyncio.Event()
                    experiment_subscriptions[experiment_id] = asyncio.create_task(
                        forward_experiment_events(experiment_id, ready)
                    )
                    await ready.wait()
            elif request.method == "eval.experiment.unsubscribe":
                experiment_id = int(request.params.get("experiment_id", 0))
                task = experiment_subscriptions.pop(experiment_id, None)
                if task:
                    task.cancel()
            await send_json(response)
    except WebSocketDisconnect:
        pass
    finally:
        for task in subscriptions.values():
            task.cancel()
        for task in experiment_subscriptions.values():
            task.cancel()
        await asyncio.gather(
            *subscriptions.values(),
            *experiment_subscriptions.values(),
            return_exceptions=True,
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
