import io
import subprocess
import tarfile

import pytest

from tools.eval_baselines import audit_baseline, extract_baseline, git


def archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as target:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            target.addfile(member, io.BytesIO(content))
    return buffer.getvalue()


def commit(repository) -> str:
    git(repository, "add", ".")
    git(
        repository,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "Baseline",
    )
    return git(repository, "rev-parse", "HEAD").decode().strip()


def test_export_excludes_verifiers_before_initial_commit(tmp_path) -> None:
    extract_baseline(
        archive(
            {
                "src/implementation.ts": b"buggy",
                "src/hidden.test.ts": b"held-out oracle",
            }
        ),
        tmp_path,
        {"src/hidden.test.ts"},
    )
    git(tmp_path, "init", "--quiet")
    sha = commit(tmp_path)
    audit = audit_baseline(tmp_path, {"src/hidden.test.ts"}, sha)
    assert audit["commits"] == 1
    assert not (tmp_path / "src/hidden.test.ts").exists()
    # The hidden file was never committed, so no recoverable Git blob exists.
    oracle_hash = (
        subprocess.run(
            ["git", "hash-object", "--stdin"],
            input=b"held-out oracle",
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    with pytest.raises(subprocess.CalledProcessError):
        git(tmp_path, "cat-file", "-e", oracle_hash)


@pytest.mark.parametrize("path", ["../outside", "/absolute", ".git/config"])
def test_export_rejects_unsafe_archive_paths(tmp_path, path) -> None:
    with pytest.raises(ValueError, match="Unsafe source archive"):
        extract_baseline(archive({path: b"bad"}), tmp_path, set())


def test_audit_rejects_remote_and_solution_history(tmp_path) -> None:
    git(tmp_path, "init", "--quiet")
    (tmp_path / "implementation.ts").write_text("buggy")
    sha = commit(tmp_path)
    git(tmp_path, "remote", "add", "origin", "https://example.invalid/source")
    with pytest.raises(ValueError, match="remotes"):
        audit_baseline(tmp_path, set(), sha)
    git(tmp_path, "remote", "remove", "origin")
    (tmp_path / "implementation.ts").write_text("fixed")
    sha = commit(tmp_path)
    with pytest.raises(ValueError, match="exactly one commit"):
        audit_baseline(tmp_path, set(), sha)


def test_audit_rejects_visible_untracked_verifier(tmp_path) -> None:
    git(tmp_path, "init", "--quiet")
    (tmp_path / ".gitignore").write_text("hidden.test.ts\n")
    sha = commit(tmp_path)
    (tmp_path / "hidden.test.ts").write_text("oracle")
    with pytest.raises(ValueError, match="leaked"):
        audit_baseline(tmp_path, {"hidden.test.ts"}, sha)
