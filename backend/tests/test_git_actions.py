import subprocess

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import main
from database import Base, models
from database.schemas import RpcRequest


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
            dispatcher,
            db,
            "workspace.git_commit",
            {
                **params,
                "message": "Too early",
                "expected_branch": "main",
                "index_token": status["result"]["index_token"],
            },
        )
        assert no_stage["error"]["message"] == "Stage changes before committing"

        staged = await call(
            dispatcher,
            db,
            "workspace.git_stage",
            {**params, "paths": ["file.txt"], "expected_branch": "main"},
        )
        assert staged["result"]["status"]["staged_count"] == 1
        assert staged["result"]["status"]["unstaged_count"] == 0

        message = 'Save $(touch should-not-run) "quoted"'
        committed = await call(
            dispatcher,
            db,
            "workspace.git_commit",
            {
                **params,
                "message": message,
                "expected_branch": "main",
                "index_token": staged["result"]["status"]["index_token"],
            },
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
            dispatcher,
            db,
            "workspace.git_stage",
            {
                "workspace_id": nested_id,
                "paths": ["file.txt"],
                "expected_branch": "main",
            },
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
            dispatcher,
            db,
            "workspace.git_stage",
            {
                "workspace_id": root_id,
                "paths": ["file.txt"],
                "expected_branch": "feature",
            },
        )
        assert "active run" in active_result["error"]["message"]
    await engine.dispose()


@pytest_asyncio.fixture
async def registered_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "seed.txt").write_text("seed\n")
    git(repo, "add", "seed.txt")
    git(repo, "commit", "-qm", "seed")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'git.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        workspace = models.Workspace(path=str(repo), name="Fixture")
        db.add(workspace)
        await db.commit()
        yield repo, db, main.RpcDispatcher(None), {"workspace_id": workspace.id}
    await engine.dispose()


@pytest.mark.asyncio
async def test_selective_staging_literal_paths_does_not_sweep_secrets_or_builds(
    registered_repo,
):
    repo, db, dispatcher, params = registered_repo
    chosen = ["space name.txt", "line\nbreak.txt", "-option.txt", ":(glob)*.txt"]
    for name in [*chosen, ".env"]:
        (repo / name).write_text("fixture\n")
    (repo / "build").mkdir()
    (repo / "build" / "output.txt").write_text("generated\n")
    result = await call(
        dispatcher,
        db,
        "workspace.git_stage",
        {**params, "paths": chosen, "expected_branch": "main"},
    )
    assert "result" in result, result
    files = result["result"]["status"]["files"]
    assert {item["path"] for item in files if item["staged"]} == set(chosen)
    assert {item["path"] for item in files if not item["staged"]} == {
        ".env",
        "build/output.txt",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "paths",
    [
        ["."],
        ["../outside"],
        ["/tmp/outside"],
        ["seed.txt"],
        ["new.txt", "new.txt"],
        [":(glob)*"],
        [],
    ],
)
async def test_stage_rejects_nonreviewed_paths(registered_repo, paths):
    repo, db, dispatcher, params = registered_repo
    (repo / "new.txt").write_text("new\n")
    result = await call(
        dispatcher,
        db,
        "workspace.git_stage",
        {**params, "paths": paths, "expected_branch": "main"},
    )
    assert "error" in result
    assert not git(repo, "diff", "--cached", "--name-only")


@pytest.mark.asyncio
async def test_commit_rejects_stale_index_and_branch(registered_repo):
    repo, db, dispatcher, params = registered_repo
    (repo / "seed.txt").write_text("changed\n")
    git(repo, "add", "seed.txt")
    review = (await call(dispatcher, db, "workspace.git_status", params))["result"]
    (repo / ".env").write_text("not a secret, test only\n")
    git(repo, "add", ".env")
    commit = {
        **params,
        "message": "reviewed",
        "expected_branch": "main",
        "index_token": review["index_token"],
    }
    result = await call(dispatcher, db, "workspace.git_commit", commit)
    assert "Staged contents changed" in result["error"]["message"]
    assert git(repo, "log", "-1", "--format=%s") == "seed"
    git(repo, "checkout", "-qb", "feature")
    result = await call(dispatcher, db, "workspace.git_commit", commit)
    assert "Branch changed" in result["error"]["message"]


@pytest.mark.asyncio
async def test_rename_and_deletion_are_reviewed_without_quoted_path_corruption(
    registered_repo,
):
    repo, db, dispatcher, params = registered_repo
    git(repo, "mv", "seed.txt", "renamed file.txt")
    (repo / "renamed file.txt").write_text("changed\n")
    status = (await call(dispatcher, db, "workspace.git_status", params))["result"]
    assert status["files"][0]["original_path"] == "seed.txt"
    result = await call(
        dispatcher,
        db,
        "workspace.git_stage",
        {**params, "paths": ["renamed file.txt"], "expected_branch": "main"},
    )
    assert "result" in result, result
    # Once committed, a selected deletion stages removal without requiring the file to exist.
    git(repo, "commit", "-qm", "rename")
    (repo / "renamed file.txt").unlink()
    result = await call(
        dispatcher,
        db,
        "workspace.git_stage",
        {**params, "paths": ["renamed file.txt"], "expected_branch": "main"},
    )
    assert result["result"]["status"]["files"][0]["status"] == "D "


@pytest.mark.asyncio
async def test_configured_push_supports_feature_branch_and_rejects_bad_destinations(
    registered_repo, tmp_path
):
    repo, db, dispatcher, params = registered_repo
    remote = tmp_path / "review.git"
    git(tmp_path, "init", "--bare", "-q", str(remote))
    git(repo, "remote", "add", "review", str(remote))
    git(repo, "checkout", "-qb", "feature/evals")
    push = {
        **params,
        "remote": "review",
        "branch": "review/evals",
        "expected_branch": "feature/evals",
    }
    for changes in [
        {"remote": "--all"},
        {"remote": "https://example.invalid/repo"},
        {"branch": "--delete"},
        {"branch": "bad..branch"},
        {"expected_branch": "main"},
    ]:
        result = await call(dispatcher, db, "workspace.git_push", {**push, **changes})
        assert "error" in result
    result = await call(dispatcher, db, "workspace.git_push", push)
    assert result["result"]["action"] == "pushed", result
    assert git(remote, "rev-parse", "review/evals") == git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "--detach", "-q")
    status = (await call(dispatcher, db, "workspace.git_status", params))["result"]
    assert status["detached"] and status["branch"] is None
    result = await call(dispatcher, db, "workspace.git_push", push)
    assert "Check out a branch" in result["error"]["message"]
