"""History-free baseline export and validation helpers for any repository."""

import io
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout


def extract_baseline(archive: bytes, destination: Path, withheld: set[str]) -> None:
    """Exclude held-out files before the first commit, including their Git blobs."""
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        members = []
        for member in source.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
                raise ValueError(f"Unsafe source archive path: {member.name}")
            if member.name not in withheld:
                members.append(member)
        source.extractall(destination, members=members, filter="data")


def audit_baseline(repository: Path, withheld: set[str], expected_sha: str) -> dict:
    if git(repository, "rev-list", "--count", "--all").strip() != b"1":
        raise ValueError("Baseline must contain exactly one commit")
    if git(repository, "remote").strip():
        raise ValueError("Baseline must not have upstream remotes")
    if git(repository, "status", "--porcelain").strip():
        raise ValueError("Baseline is not clean")
    if git(repository, "rev-parse", "HEAD").decode().strip() != expected_sha:
        raise ValueError("Baseline commit does not match")
    tracked = set(git(repository, "ls-files", "-z").decode().split("\0"))
    if tracked & withheld or any(
        (repository / path).exists() or (repository / path).is_symlink()
        for path in withheld
    ):
        raise ValueError("A held-out test leaked into the baseline")
    return {
        "commits": 1,
        "remotes": [],
        "clean": True,
        "held_out_paths_absent": sorted(withheld),
    }
