import subprocess

import main
import pytest
from database import Base, models
from database.schemas import RpcRequest
from run_diffs import RunDiffService, _build_diff, _capture_baseline
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def git(root, *arguments):
    return subprocess.run(
        ["git", "-C", str(root), *arguments], check=True, capture_output=True
    ).stdout


@pytest.mark.asyncio
async def test_run_diff_excludes_preexisting_edits_and_survives_completion(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "source.txt").write_text("original\n")
    (repo / "dirty.txt").write_text("committed\n")
    (repo / "removed.txt").write_text("remove me\n")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "initial",
    )
    (repo / "dirty.txt").write_text("before run\n")
    (repo / "untracked.txt").write_text("untracked before\n")

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        workspace = models.Workspace(path=str(repo), name="Repo")
        session = models.Session(workspace=workspace, provider="codex")
        run = models.Run(session=session, status="running", prompt="edit")
        db.add(run)
        await db.commit()
        run_id = run.id

    service = RunDiffService(factory)
    await service.capture(run_id, str(repo))
    before = await service.refresh(run_id)
    assert before and before["file_count"] == 0

    (repo / "source.txt").write_text("changed\n")
    (repo / "dirty.txt").write_text("after run\n")
    (repo / "untracked.txt").write_text("untracked after\n")
    (repo / "new.txt").write_text("new file\n")
    (repo / "removed.txt").unlink()
    result = await service.refresh(run_id, final=True)
    assert result and result["final"] and result["file_count"] == 5
    by_path = {file["path"]: file for file in result["files"]}
    assert by_path["dirty.txt"]["patch"].find("-before run") >= 0
    assert "committed" not in by_path["dirty.txt"]["patch"]
    assert by_path["new.txt"]["status"] == "added"
    assert by_path["removed.txt"]["status"] == "deleted"

    (repo / "source.txt").write_text("changed again\n")
    saved = await service.get(run_id)
    assert saved and saved["stale"] is True
    assert saved["files"] == result["files"]
    async with factory() as db:
        run = await db.get(models.Run, run_id)
        assert run
        run.status = "completed"
        await db.commit()
        dispatcher = main.RpcDispatcher(None, service)
        response = await dispatcher.dispatch(
            RpcRequest(
                id=1,
                method="run.diff.get",
                params={"session_id": session.id, "run_id": run_id},
            ),
            db,
        )
    assert response["result"]["stale"] is True
    assert response["result"]["file_count"] == 5
    async with factory() as db:
        stale_revert = await dispatcher.dispatch(
            RpcRequest(
                id=2,
                method="run.diff.revert",
                params={"session_id": session.id, "run_id": run_id},
            ),
            db,
        )
    assert "changed since this review" in stale_revert["error"]["message"]
    assert (repo / "source.txt").read_text() == "changed again\n"

    (repo / "source.txt").write_text("changed\n")
    async with factory() as db:
        reverted = await dispatcher.dispatch(
            RpcRequest(
                id=3,
                method="run.diff.revert",
                params={"session_id": session.id, "run_id": run_id},
            ),
            db,
        )
    assert reverted["result"]["decision"] == "reverted"
    assert (repo / "source.txt").read_text() == "original\n"
    assert (repo / "dirty.txt").read_text() == "before run\n"
    assert (repo / "untracked.txt").read_text() == "untracked before\n"
    assert (repo / "removed.txt").read_text() == "remove me\n"
    assert not (repo / "new.txt").exists()
    await engine.dispose()


@pytest.mark.asyncio
async def test_accept_keeps_files_and_records_review(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "file.txt").write_text("before\n")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "initial",
    )
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        run = models.Run(
            session=models.Session(
                workspace=models.Workspace(path=str(repo), name="Repo"),
                provider="codex",
            ),
            status="completed",
            prompt="edit",
        )
        db.add(run)
        await db.commit()
        run_id = run.id
    service = RunDiffService(factory)
    await service.capture(run_id, str(repo))
    (repo / "file.txt").write_text("after\n")
    await service.refresh(run_id, final=True)
    accepted = await service.decide(run_id, "accept")
    assert (
        accepted and accepted["decision"] == "accepted" and not accepted["can_revert"]
    )
    assert (repo / "file.txt").read_text() == "after\n"
    with pytest.raises(RuntimeError, match="already been reviewed"):
        await service.decide(run_id, "revert")
    await engine.dispose()


@pytest.mark.asyncio
async def test_non_git_workspace_reports_unavailable_without_blocking(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        run = models.Run(
            session=models.Session(
                workspace=models.Workspace(path=str(tmp_path), name="Folder"),
                provider="codex",
            ),
            status="running",
            prompt="inspect",
        )
        db.add(run)
        await db.commit()
        run_id = run.id
    service = RunDiffService(factory)
    await service.capture(run_id, str(tmp_path))
    result = await service.refresh(run_id, final=True)
    assert result and result["status"] == "unavailable" and result["final"]
    assert result["files"] == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_interrupted_run_diff_is_not_misattributed_after_restart(
    tmp_path, monkeypatch
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'history.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        run = models.Run(
            session=models.Session(
                workspace=models.Workspace(path=str(tmp_path), name="Folder"),
                provider="codex",
                status="running",
            ),
            status="running",
            prompt="edit",
        )
        db.add(run)
        await db.flush()
        db.add(
            models.RunDiff(
                run_id=run.id,
                workspace_path=str(tmp_path),
                repo_path=str(tmp_path),
                baseline={"tracked": {}, "overrides": {}},
                result={},
                status="capturing",
            )
        )
        await db.commit()
        run_id = run.id
    monkeypatch.setattr(main, "SessionLocal", factory)
    await main.reconcile_interrupted_runs()
    async with factory() as db:
        saved = await db.get(models.RunDiff, run_id)
        assert saved and saved.status == "unavailable" and saved.final
        assert saved.baseline is None
    await engine.dispose()


def test_nested_workspace_diff_stays_inside_selected_folder(tmp_path):
    repo = tmp_path / "repo"
    selected = repo / "selected"
    selected.mkdir(parents=True)
    (selected / "app.py").write_text("before\n")
    (repo / "outside.py").write_text("outside\n")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "initial",
    )
    baseline = _capture_baseline(str(selected))
    (selected / "app.py").write_text("after")
    (repo / "outside.py").write_text("changed outside\n")
    result = _build_diff(baseline)
    assert [file["path"] for file in result["files"]] == ["selected/app.py"]
    assert "-before" in result["files"][0]["patch"]
    assert "+after" in result["files"][0]["patch"]


def test_staged_work_before_run_is_not_attributed_to_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "file.txt").write_text("committed\n")
    git(repo, "add", "file.txt")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "initial",
    )
    (repo / "file.txt").write_text("staged before run\n")
    git(repo, "add", "file.txt")
    baseline = _capture_baseline(str(repo))
    assert _build_diff(baseline)["file_count"] == 0
    (repo / "file.txt").write_text("changed during run\n")
    patch = _build_diff(baseline)["files"][0]["patch"]
    assert "-staged before run" in patch
    assert "committed" not in patch
