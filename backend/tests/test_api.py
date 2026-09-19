import main
import pytest
from database import Base, models
from database.schemas import RpcRequest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class RuntimeStub:
    def __init__(self) -> None:
        self.started: list[tuple] = []

    async def start(self, *args, **kwargs) -> None:
        self.started.append((args, kwargs))

    async def cancel(self, session_id: int) -> bool:
        return False


async def dispatch(dispatcher, db, method, params=None):
    response = await dispatcher.dispatch(
        RpcRequest(id=1, method=method, params=params or {}), db
    )
    assert "error" not in response, response
    return response["result"]


@pytest.mark.asyncio
async def test_sqlite_dispatch_and_durable_events(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(main, "SessionLocal", session_factory)

    runtime = RuntimeStub()
    dispatcher = main.RpcDispatcher(runtime)
    async with session_factory() as db:
        workspace = await dispatch(
            dispatcher,
            db,
            "workspace.create",
            {"path": str(tmp_path), "name": "Test"},
        )
        session = await dispatch(
            dispatcher,
            db,
            "session.create",
            {"workspace_id": workspace["id"], "provider": "codex"},
        )
        sent = await dispatch(
            dispatcher,
            db,
            "session.send",
            {"session_id": session["id"], "content": "Inspect the project"},
        )

    run_id = sent["run_id"]
    assert runtime.started[0][0][:2] == (session["id"], run_id)
    assert runtime.started[0][1] == {"mode": "chat"}
    started = await main.persist_event(
        session["id"], run_id, "session.started", {"pid": 123}, None
    )
    assistant = await main.persist_event(
        session["id"],
        run_id,
        "assistant.text",
        {
            "content": "Inspection complete",
            "item": {"type": "agent_message", "metadata": {"tokens": 10}},
        },
        "item-1",
    )
    completed = await main.persist_event(
        session["id"], run_id, "session.completed", {"return_code": 0}, None
    )

    async with session_factory() as db:
        history = await dispatch(
            dispatcher,
            db,
            "session.history",
            {"session_id": session["id"]},
        )
        stored_session = await db.get(models.Session, session["id"])

    assert started.sequence < assistant.sequence < completed.sequence
    assert [message["role"] for message in history["conversation"]] == [
        "user",
        "assistant",
    ]
    assert history["conversation"][1]["content"] == "Inspection complete"
    assert history["conversation"][1]["run_id"] == run_id
    assert history["events"][1]["payload"]["item"]["metadata"] == {"tokens": 10}
    assert history["events"][1]["sequence"] == assistant.sequence
    assert history["has_more"] is False
    assert stored_session and stored_session.status == "completed"

    async with session_factory() as db:
        renamed = await dispatch(
            dispatcher,
            db,
            "workspace.rename",
            {"workspace_id": workspace["id"], "name": "Renamed project"},
        )
        git_status = await dispatch(
            dispatcher,
            db,
            "workspace.git_status",
            {"workspace_id": workspace["id"]},
        )
        deleted_session = await dispatch(
            dispatcher,
            db,
            "session.delete",
            {"session_id": session["id"]},
        )
        deleted_workspace = await dispatch(
            dispatcher,
            db,
            "workspace.delete",
            {"workspace_id": workspace["id"]},
        )

    assert renamed["name"] == "Renamed project"
    assert git_status == {
        "is_repository": False,
        "branch": None,
        "dirty_count": 0,
    }
    assert deleted_session == {"deleted": True, "session_id": session["id"]}
    assert deleted_workspace == {"deleted": True, "workspace_id": workspace["id"]}
    await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_schema_rejects_invalid_persisted_types(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'schema.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "INSERT INTO workspaces (id, path, name) VALUES (1, '/tmp/project', 'Project')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO sessions (id, workspace_id, provider, status) "
                "VALUES (1, 1, 'codex', 'idle')"
            )
        )

    for statement in (
        "INSERT INTO sessions (workspace_id, provider, status) VALUES (1, 'fake', 'idle')",
        "INSERT INTO sessions (workspace_id, provider, status) VALUES (1, 'codex', 'unknown')",
        "INSERT INTO runs (session_id, status, prompt) VALUES (1, 'unknown', 'Hi')",
        "INSERT INTO messages (session_id, role, content) VALUES (1, 'system', 'Hi')",
    ):
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(text(statement))
    await engine.dispose()
