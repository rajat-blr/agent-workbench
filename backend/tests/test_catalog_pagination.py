from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import Base, models
from database.schemas import RpcRequest
from main import RpcDispatcher
from rpc_contract import RPC_METHODS


@pytest.mark.parametrize("method", ["workspace.list", "session.list"])
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"before_id": -1}])
def test_catalog_bounds(method, params):
    with pytest.raises(ValidationError):
        RPC_METHODS[method].params.model_validate(params)


@pytest.mark.asyncio
async def test_catalog_pages_are_bounded_and_stable_under_updates(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'catalog.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        dispatcher = RpcDispatcher(None)
        async with factory() as db:
            db.add_all(
                [
                    models.Workspace(
                        id=i, path=f"/fixture/{i}", name=f"Name {602 - i:04}"
                    )
                    for i in range(1, 602)
                ]
            )
            db.add_all(
                [
                    models.Session(id=i, workspace_id=1 if i % 2 else 2)
                    for i in range(1, 602)
                ]
            )
            await db.commit()

            async def request(method, params):
                response = await dispatcher.dispatch(
                    RpcRequest(id=1, method=method, params=params), db
                )
                assert "error" not in response, response
                return response["result"]

            for method in ("workspace.list", "session.list"):
                assert len(await request(method, {})) == 500
                first = await request(method, {"before_id": 0, "limit": 200})
                assert [row["id"] for row in first] == list(range(601, 401, -1))
                # Updates across the cursor and new inserts cannot shift existing IDs.
                if method == "workspace.list":
                    (await db.get(models.Workspace, 1)).name = "AAA"
                    db.add(models.Workspace(id=602, path="/fixture/new", name="New"))
                else:
                    (await db.get(models.Session, 1)).updated_at = datetime(
                        2030, 1, 1, tzinfo=UTC
                    )
                    db.add(models.Session(id=602, workspace_id=1))
                await db.commit()
                rows = first[:]
                while True:
                    page = await request(
                        method, {"before_id": rows[-1]["id"], "limit": 200}
                    )
                    rows.extend(page)
                    if len(page) < 200:
                        break
                assert [row["id"] for row in rows] == list(range(601, 0, -1))
                assert await request(method, {"before_id": 1}) == []
            filtered = await request(
                "session.list", {"workspace_id": 2, "before_id": 0}
            )
            assert len(filtered) == 300
            assert all(row["workspace_id"] == 2 for row in filtered)
            assert (
                await request("session.list", {"workspace_id": 999, "before_id": 0})
                == []
            )
            assert (await request("session.list", {"limit": 1}))[0]["id"] == 1
            assert (await request("workspace.list", {"limit": 1}))[0]["name"] == "AAA"
    finally:
        await engine.dispose()
