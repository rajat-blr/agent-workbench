"""Import GitHub repositories into the local evaluation repository catalog."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from rpc_handlers.common import RpcMethodError


def github_repository(url: str) -> tuple[str, str, str]:
    """Accept repository links only, without credentials or arbitrary Git transports."""
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Enter a GitHub repository link: https://github.com/owner/repository"
        )
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 2:
        raise ValueError("Use the repository link, without a branch or file path")
    owner, name = parts
    if name.endswith(".git"):
        name = name[:-4]
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", owner)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
        or name in {".", ".."}
    ):
        raise ValueError("Invalid GitHub repository name")
    return owner, name, f"https://github.com/{owner.lower()}/{name.lower()}.git"


async def _git(*arguments: str) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.https.allow=always",
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
        )
    except FileNotFoundError as exc:
        raise RpcMethodError(-32030, "Install Git to add a repository") from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    except (TimeoutError, asyncio.CancelledError) as exc:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise RpcMethodError(
            -32030, "Repository download timed out. Try again."
        ) from exc
    if process.returncode:
        detail = re.sub(
            r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1***@", stderr.decode(errors="replace")
        )[:1000].strip()
        raise RpcMethodError(
            -32030, f"Could not add repository. Check the link and Git access. {detail}"
        )
    return stdout.decode(errors="replace").strip()


async def clone_github_repository(url: str, root: Path) -> tuple[Path, str]:
    owner, name, canonical = github_repository(url)
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
    root = await asyncio.to_thread(root.resolve)
    await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
    destination = root / f"{owner.lower()}--{name.lower()}-{digest}"
    if await asyncio.to_thread(destination.is_symlink):
        raise RpcMethodError(-32030, "Repository destination is a symbolic link")
    if await asyncio.to_thread(destination.exists):
        # Reuse a previous successful clone, including one whose catalog write failed.
        origin = await _git("-C", str(destination), "remote", "get-url", "origin")
        if github_repository(origin)[2] != canonical:
            raise RpcMethodError(
                -32030, "Repository destination belongs to a different repository"
            )
        await _git("-C", str(destination), "rev-parse", "--verify", "HEAD")
        return destination, f"{owner}/{name}"
    staging = Path(
        await asyncio.to_thread(tempfile.mkdtemp, prefix=".clone-", dir=root)
    )
    try:
        await _git("clone", "--", canonical, str(staging))
        await _git("-C", str(staging), "rev-parse", "--verify", "HEAD")
        await asyncio.to_thread(staging.rename, destination)
    finally:
        # Only the temporary directory created by this operation is removed.
        if await asyncio.to_thread(staging.exists):
            await asyncio.to_thread(shutil.rmtree, staging)
    return destination, f"{owner}/{name}"
