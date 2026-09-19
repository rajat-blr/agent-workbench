import subprocess

import main
import pytest
from database import Base, models
from database.schemas import RpcRequest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def git(root, *arguments):
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


async def call(dispatcher, db, method, params):
    return await dispatcher.dispatch(RpcRequest(id=1, method=method, params=params), db)


@pytest.mark.asyncio
async def test_stage_commit_and_push_main_to_local_remote(tmp_path):
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    git(tmp_path, "init", "--bare", "-q", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    (repo / "file.txt").write_text("hello\n")

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        workspace = models.Workspace(path=str(repo), name="Repo")
        db.add(workspace)
        await db.commit()
        workspace_id = workspace.id

    dispatcher = main.RpcDispatcher(None)
    params = {"workspace_id": workspace_id}
    async with factory() as db:
        status = await call(dispatcher, db, "workspace.git_status", params)
        assert status["result"]["is_root"] is True
        assert status["result"]["dirty_count"] == 1
        assert status["result"]["staged_count"] == 0
        assert status["result"]["unstaged_count"] == 1

        no_stage = await call(
            dispatcher, db, "workspace.git_commit", {**params, "message": "Too early"}
        )
        assert no_stage["error"]["message"] == "Stage changes before committing"

        staged = await call(dispatcher, db, "workspace.git_stage", params)
        assert staged["result"]["status"]["staged_count"] == 1
        assert staged["result"]["status"]["unstaged_count"] == 0

        message = 'Save $(touch should-not-run) "quoted"'
        committed = await call(
            dispatcher, db, "workspace.git_commit", {**params, "message": message}
        )
        assert committed["result"]["status"]["dirty_count"] == 0
        assert git(repo, "log", "-1", "--format=%s") == message
        assert not (repo / "should-not-run").exists()

        pushed = await call(dispatcher, db, "workspace.git_push_main", params)
        assert pushed["result"]["action"] == "pushed"
        assert git(repo, "rev-parse", "main") == git(remote, "rev-parse", "main")

    await engine.dispose()


@pytest.mark.asyncio
async def test_git_actions_reject_nested_workspace_and_other_branch(tmp_path):
    repo = tmp_path / "repo"
    nested = repo / "nested"
    nested.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    (repo / "file.txt").write_text("hello\n")

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        root_workspace = models.Workspace(path=str(repo), name="Root")
        nested_workspace = models.Workspace(path=str(nested), name="Nested")
        db.add_all([root_workspace, nested_workspace])
        await db.commit()
        root_id, nested_id = root_workspace.id, nested_workspace.id

    dispatcher = main.RpcDispatcher(None)
    async with factory() as db:
        nested_result = await call(
            dispatcher, db, "workspace.git_stage", {"workspace_id": nested_id}
        )
        assert "repository root" in nested_result["error"]["message"]
        git(repo, "symbolic-ref", "HEAD", "refs/heads/feature")
        branch_result = await call(
            dispatcher, db, "workspace.git_push_main", {"workspace_id": root_id}
        )
        assert "main branch" in branch_result["error"]["message"]
        db.add(
            models.Run(
                session=models.Session(workspace_id=root_id, provider="codex"),
                status="running",
                prompt="edit",
            )
        )
        await db.commit()
        active_result = await call(
            dispatcher, db, "workspace.git_stage", {"workspace_id": root_id}
        )
        assert "active run" in active_result["error"]["message"]
    await engine.dispose()
