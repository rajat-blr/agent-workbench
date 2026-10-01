from __future__ import annotations

import asyncio
import os
import re
import signal
import uuid
from dataclasses import dataclass
from pathlib import Path

FULL_COMMIT_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


class WorktreeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProvisionedWorktree:
    attempt_id: int
    repository_path: Path
    path: Path
    base_sha: str


class WorktreeService:
    def __init__(
        self, root: str | Path, *, command_timeout_seconds: float = 30
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.command_timeout_seconds = command_timeout_seconds

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "TMPDIR"}
        }
        environment.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"})
        return environment

    async def _git(
        self,
        repository: Path,
        *arguments: str,
        stdin: bytes | None = None,
    ) -> bytes:
        process_options = {"start_new_session": True} if os.name != "nt" else {}
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repository),
                *arguments,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._environment(),
                **process_options,
            )
        except FileNotFoundError as exc:
            raise WorktreeError("Git is not installed") from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin), timeout=self.command_timeout_seconds
            )
        except TimeoutError as exc:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            await process.wait()
            raise WorktreeError("Git worktree command timed out") from exc
        if process.returncode:
            message = stderr.decode(errors="replace").strip()[:2000]
            raise WorktreeError(message or "Git worktree command failed")
        return stdout

    async def provision(
        self,
        repository_path: str | Path,
        base_sha: str,
        attempt_id: int,
        *,
        starting_patch: bytes | None = None,
    ) -> ProvisionedWorktree:
        if attempt_id <= 0:
            raise ValueError("Attempt ID must be positive")
        if not FULL_COMMIT_RE.fullmatch(base_sha):
            raise WorktreeError("Base commit must be a full Git commit SHA")
        repository = Path(repository_path).expanduser().resolve()
        if not repository.is_dir():
            raise WorktreeError("Repository path does not exist")
        try:
            is_repository = await self._git(
                repository, "rev-parse", "--is-inside-work-tree"
            )
            repository_root = Path(
                (await self._git(repository, "rev-parse", "--show-toplevel"))
                .decode()
                .strip()
            ).resolve()
            resolved_sha = (
                (await self._git(repository, "rev-parse", f"{base_sha}^{{commit}}"))
                .decode()
                .strip()
            )
        except WorktreeError as exc:
            raise WorktreeError(
                "Could not resolve the case repository and base commit"
            ) from exc
        if is_repository.decode().strip() != "true" or repository_root != repository:
            raise WorktreeError("Case repository path must be the Git repository root")
        if resolved_sha.lower() != base_sha.lower():
            raise WorktreeError("Base commit did not resolve to the pinned SHA")

        destination = (
            self.root / f"attempt-{attempt_id}-{uuid.uuid4().hex[:12]}"
        ).resolve()
        if not destination.is_relative_to(self.root) or destination.exists():
            raise WorktreeError("Could not allocate a safe worktree path")
        await self._git(
            repository,
            "worktree",
            "add",
            "--detach",
            str(destination),
            resolved_sha,
        )
        worktree = ProvisionedWorktree(
            attempt_id=attempt_id,
            repository_path=repository,
            path=destination,
            base_sha=resolved_sha,
        )
        if starting_patch:
            try:
                await self._git(
                    destination,
                    "apply",
                    "--whitespace=nowarn",
                    "-",
                    stdin=starting_patch,
                )
            except WorktreeError:
                await self.cleanup(worktree)
                raise
        return worktree

    async def cleanup(self, worktree: ProvisionedWorktree) -> None:
        path = worktree.path.resolve()
        if not path.is_relative_to(self.root):
            raise WorktreeError("Refusing to clean a worktree outside the eval root")
        if path.exists():
            await self._git(
                worktree.repository_path,
                "worktree",
                "remove",
                "--force",
                str(path),
            )
        await self._git(worktree.repository_path, "worktree", "prune")

    async def changed_paths(self, worktree: ProvisionedWorktree) -> set[str]:
        if not worktree.path.is_dir():
            raise WorktreeError("Attempt worktree no longer exists")
        tracked = await self._git(
            worktree.path,
            "diff",
            "--name-only",
            "-z",
            worktree.base_sha,
            "--",
        )
        untracked = await self._git(
            worktree.path,
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        )
        return {
            path.decode("utf-8", errors="surrogateescape")
            for path in (tracked + untracked).split(b"\0")
            if path
        }
