import asyncio
import subprocess

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import github_repositories as repositories
from database import Base, models
from database.schemas import RpcRequest
from main import RpcDispatcher
from rpc_handlers.common import RpcMethodError
from settings import settings


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/OpenAI/example",
        "https://github.com/OpenAI/example.git/",
        " https://github.com/OpenAI/example/ ",
    ],
)
def test_repository_link_normalization(url):
    assert repositories.github_repository(url) == (
        "OpenAI",
        "example",
        "https://github.com/openai/example.git",
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/owner/repo",
        "https://example.com/owner/repo",
        "file:///tmp/repo",
        "git@github.com:owner/repo.git",
        "https://user:secret@github.com/owner/repo",
        "https://github.com:443/owner/repo",
        "https://github.com/owner/repo/tree/main",
        "https://github.com/owner/repo?token=secret",
        "https://github.com/owner/repo#main",
        "https://github.com/owner/..",
        "https://github.com/owner/%2e%2e",
        "https://github.com/owner/repo/extra",
    ],
)
def test_invalid_links_are_rejected(url):
    with pytest.raises(ValueError):
        repositories.github_repository(url)


@pytest.mark.asyncio
async def test_import_creates_full_clone_registers_once_and_reuses_it(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(source), *args], check=True, capture_output=True
        )

    git("init")
    git("config", "user.email", "fixture@example.test")
    git("config", "user.name", "Fixture")
    (source / "task.txt").write_text("before")
    git("add", ".")
    git("commit", "-m", "Base task")
    base = git("rev-parse", "HEAD").stdout.decode().strip()
    (source / "task.txt").write_text("after")
    git("commit", "-am", "Reference fix")
    original_git = repositories._git
    clones = []

    async def local_git(*args):
        if args[0] == "clone":
            clones.append(args)
            process = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--",
                str(source),
                args[-1],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()
            assert process.returncode == 0
            await original_git("-C", args[-1], "remote", "set-url", "origin", args[-2])
            return ""
        return await original_git(*args)

    monkeypatch.setattr(repositories, "_git", local_git)
    root = tmp_path / "imports"
    monkeypatch.setattr(settings, "eval_repository_directory", str(root))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'catalog.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        dispatcher = RpcDispatcher(None)
        async with factory() as db:

            async def request(url):
                return await dispatcher.dispatch(
                    RpcRequest(
                        id=1, method="workspace.clone_github", params={"url": url}
                    ),
                    db,
                )

            first = await request("https://github.com/Owner/Repo")
            assert "error" not in first, first
            second = await request("https://github.com/owner/repo.git/")
            assert second["result"]["id"] == first["result"]["id"]
            assert len(clones) == 1
            assert first["result"]["name"] == "Owner/Repo"
            path = first["result"]["path"]
            assert (
                await original_git("-C", path, "show", f"{base}:task.txt") == "before"
            )
            assert len((await db.scalars(select(models.Workspace))).all()) == 1
            assert not list(root.glob(".clone-*"))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [RpcMethodError(-32030, "Download failed"), asyncio.CancelledError()]
)
async def test_failed_import_cleans_its_temporary_clone(tmp_path, monkeypatch, failure):
    async def fail(*_args):
        raise failure

    monkeypatch.setattr(repositories, "_git", fail)
    root = tmp_path / "imports"
    with pytest.raises(type(failure)):
        await repositories.clone_github_repository(
            "https://github.com/owner/repo", root
        )
    assert list(root.iterdir()) == []


@pytest.mark.asyncio
async def test_import_refuses_to_reuse_another_repository(tmp_path, monkeypatch):
    async def clone(*args):
        if args[0] == "clone":
            return ""
        if "get-url" in args:
            return "https://github.com/other/repository.git"
        return "a" * 40

    monkeypatch.setattr(repositories, "_git", clone)
    await repositories.clone_github_repository(
        "https://github.com/owner/repo", tmp_path
    )
    with pytest.raises(RpcMethodError, match="different repository"):
        await repositories.clone_github_repository(
            "https://github.com/owner/repo", tmp_path
        )
