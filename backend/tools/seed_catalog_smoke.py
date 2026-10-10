"""Create a fresh disposable large-catalog fixture; never overwrite an existing DB."""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import models
from database.migrations import run_migrations


async def seed(path: Path) -> None:
    if await asyncio.to_thread(path.exists):
        raise ValueError("Smoke fixture database must not already exist")
    url = f"sqlite+aiosqlite:///{await asyncio.to_thread(path.resolve)}"
    engine = create_async_engine(url)
    try:
        await run_migrations(engine, database_url=url)
        async with async_sessionmaker(engine)() as db:
            db.add_all(
                [
                    models.Workspace(
                        id=i,
                        name=f"Workspace {i:04}",
                        path=str(path.parent / f"workspace-{i}"),
                    )
                    for i in range(1, 602)
                ]
            )
            db.add_all(
                [
                    models.Session(
                        id=i,
                        workspace_id=601,
                        title=f"Catalog chat {i:04}",
                        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                    )
                    for i in range(1, 602)
                ]
            )
            await db.commit()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed(Path(sys.argv[1])))
