import subprocess

import pytest

from evals.worktrees import WorktreeError, WorktreeService


def git(repository, *arguments, input_bytes=None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        input=input_bytes,
        capture_output=True,
        check=True,
    )
    return result.stdout.decode().strip()


def create_repository(path) -> str:
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.email", "evals@example.com")
    git(path, "config", "user.name", "Evals Test")
    (path / "app.txt").write_text("base\n")
    git(path, "add", "app.txt")
    git(path, "commit", "-qm", "base")
    return git(path, "rev-parse", "HEAD")


@pytest.mark.asyncio
async def test_provision_applies_patch_without_touching_live_checkout(tmp_path) -> None:
    repository = tmp_path / "repository"
    base_sha = create_repository(repository)
    (repository / "app.txt").write_text("live dirty change\n")
    patch = (
        b"diff --git a/app.txt b/app.txt\n"
        b"--- a/app.txt\n"
        b"+++ b/app.txt\n"
        b"@@ -1 +1 @@\n"
        b"-base\n"
        b"+starting patch\n"
    )
    service = WorktreeService(tmp_path / "worktrees")

    worktree = await service.provision(repository, base_sha, 1, starting_patch=patch)

    assert worktree.path != repository
    assert (worktree.path / "app.txt").read_text() == "starting patch\n"
    assert (repository / "app.txt").read_text() == "live dirty change\n"
    assert git(worktree.path, "rev-parse", "HEAD") == base_sha
    assert git(worktree.path, "branch", "--show-current") == ""

    (worktree.path / "app.txt").write_text("agent edit\n")
    (worktree.path / "new.txt").write_text("untracked\n")
    assert await service.changed_paths(worktree) == {"app.txt", "new.txt"}

    await service.cleanup(worktree)

    assert not worktree.path.exists()
    assert str(worktree.path) not in git(repository, "worktree", "list", "--porcelain")
    assert (repository / "app.txt").read_text() == "live dirty change\n"


@pytest.mark.asyncio
async def test_invalid_starting_patch_cleans_failed_worktree(tmp_path) -> None:
    repository = tmp_path / "repository"
    base_sha = create_repository(repository)
    service = WorktreeService(tmp_path / "worktrees")

    with pytest.raises(WorktreeError):
        await service.provision(
            repository,
            base_sha,
            2,
            starting_patch=b"this is not a patch",
        )

    assert not list((tmp_path / "worktrees").glob("attempt-*"))
    assert "attempt-2" not in git(repository, "worktree", "list", "--porcelain")


@pytest.mark.asyncio
async def test_provision_requires_full_commit_and_repository_root(tmp_path) -> None:
    repository = tmp_path / "repository"
    base_sha = create_repository(repository)
    nested = repository / "nested"
    nested.mkdir()
    service = WorktreeService(tmp_path / "worktrees")

    with pytest.raises(WorktreeError, match="full Git commit SHA"):
        await service.provision(repository, base_sha[:8], 3)
    with pytest.raises(WorktreeError, match="repository root"):
        await service.provision(nested, base_sha, 3)
