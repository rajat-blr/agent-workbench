import pytest

from evals.verifier_bundles import (
    build_verifier_bundle,
    materialize_verifier_bundle,
)
from evals.worktrees import WorktreeError


@pytest.mark.parametrize(
    "path",
    [
        "../secret.txt",
        "/absolute.txt",
        "tests/../secret.txt",
        ".git/config",
        "tests//hidden.py",
    ],
)
def test_verifier_bundle_rejects_unsafe_paths(path) -> None:
    with pytest.raises(ValueError, match="Unsafe held-out verifier path"):
        build_verifier_bundle([{"path": path, "content": "test"}])


def test_verifier_bundle_does_not_overwrite_existing_or_escaped_files(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    target = worktree / "tests" / "hidden.py"
    target.parent.mkdir()
    target.write_text("visible to agent")
    bundle = build_verifier_bundle([{"path": "tests/hidden.py", "content": "held out"}])
    with pytest.raises(WorktreeError, match="already agent-visible"):
        materialize_verifier_bundle(bundle, worktree)
    assert target.read_text() == "visible to agent"

    target.unlink()
    target.parent.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (worktree / "tests").symlink_to(outside, target_is_directory=True)
    with pytest.raises(WorktreeError, match="escapes the worktree"):
        materialize_verifier_bundle(bundle, worktree)
    assert not (outside / "hidden.py").exists()
