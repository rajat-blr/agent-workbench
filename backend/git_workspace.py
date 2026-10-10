import asyncio
import hashlib
from pathlib import Path, PurePosixPath
from typing import Any


async def git_read(path: str, *arguments: str) -> tuple[int, bytes]:
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            path,
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return 1, b""
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise ValueError("Git inspection timed out; no action was performed") from None
    return process.returncode or 0, stdout


def parse_status(raw: bytes) -> list[dict[str, Any]]:
    records = iter(raw.decode("utf-8").split("\0"))
    files = []
    for record in records:
        if not record:
            continue
        state, name = record[:2], record[3:]
        original = next(records) if "R" in state or "C" in state else None
        files.append(
            {
                "path": name,
                "original_path": original,
                "status": state,
                "staged": state[0] not in {" ", "?"},
                "unstaged": state == "??" or state[1] != " ",
            }
        )
    return files


async def git_status(path: str) -> dict[str, Any]:
    code, _ = await git_read(path, "rev-parse", "--is-inside-work-tree")
    if code:
        return {
            "is_repository": False,
            "is_root": False,
            "branch": None,
            "detached": False,
            "dirty_count": 0,
            "staged_count": 0,
            "unstaged_count": 0,
            "files": [],
            "remotes": [],
            "index_token": None,
        }
    root_code, root = await git_read(path, "rev-parse", "--show-toplevel")
    branch_code, branch_raw = await git_read(path, "symbolic-ref", "--short", "HEAD")
    status_code, raw = await git_read(
        path, "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )
    index_code, patch = await git_read(
        path, "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv"
    )
    remote_code, remotes = await git_read(path, "remote")
    if any((root_code, status_code, index_code, remote_code)):
        raise ValueError("Could not inspect Git safely; refresh before acting")
    branch = branch_raw.decode().strip() if not branch_code else None
    files = parse_status(raw)
    repository_root = await asyncio.to_thread(Path(root.decode().rstrip("\n")).resolve)
    requested_path = await asyncio.to_thread(Path(path).resolve)
    return {
        "is_repository": True,
        "is_root": repository_root == requested_path,
        "branch": branch,
        "detached": branch is None,
        "dirty_count": len(files),
        "staged_count": sum(item["staged"] for item in files),
        "unstaged_count": sum(item["unstaged"] for item in files),
        "files": files,
        "remotes": remotes.decode().splitlines(),
        "index_token": hashlib.sha256(
            (branch or "").encode() + b"\0" + patch
        ).hexdigest(),
    }


def staging_paths(status: dict[str, Any], selected: list[str]) -> list[str]:
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("Select one or more distinct files to stage")
    available = {item["path"]: item for item in status["files"] if item["unstaged"]}
    result = []
    for name in selected:
        parts = PurePosixPath(name).parts
        if (
            not name
            or "\0" in name
            or "\\" in name
            or PurePosixPath(name).is_absolute()
            or ".." in parts
            or ".git" in parts
            or name not in available
        ):
            raise ValueError(
                "Selected file is not an available changed path; refresh the review"
            )
        item = available[name]
        result.append(name)
        if item["original_path"] and item["status"][1] == "R":
            result.append(item["original_path"])
    return list(dict.fromkeys(result))
