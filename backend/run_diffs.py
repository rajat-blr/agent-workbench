"""Read-only, per-run Git worktree snapshots and reviewable text diffs."""

import asyncio
import base64
import difflib
import hashlib
import os
import stat
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from database import models
from sqlalchemy.ext.asyncio import async_sessionmaker

MAX_TRACKED_FILES = 50_000
MAX_DIRTY_FILES = 200
MAX_FILE_BYTES = 1_000_000
MAX_BASELINE_BYTES = 10_000_000
MAX_PATCH_CHARS = 200_000
MAX_DIFF_FILES = 500
MAX_TOTAL_PATCH_CHARS = 2_000_000
MAX_TOTAL_COMPARE_BYTES = 20_000_000


def _git(root: Path, *arguments: str) -> bytes:
    process = subprocess.run(
        ["git", "-C", str(root), "-c", "diff.autoRefreshIndex=false", *arguments],
        capture_output=True,
        timeout=8,
        check=False,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.decode(errors="replace").strip()[:300])
    return process.stdout


def _paths(raw: bytes) -> set[str]:
    return {
        name.decode("utf-8", errors="surrogateescape")
        for name in raw.split(b"\0")
        if name
    }


def _tracked(root: Path, pathspec: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in _git(root, "ls-files", "--stage", "-z", "--", pathspec).split(b"\0"):
        if not row:
            continue
        metadata, filename = row.split(b"\t", 1)
        mode, oid, stage = metadata.decode().split(" ")
        if stage == "0":
            result[filename.decode("utf-8", errors="surrogateescape")] = {
                "mode": mode,
                "oid": oid,
            }
    return result


def _read_file(root: Path, relative: str) -> tuple[str, bytes | None]:
    candidate = root / relative
    if candidate.is_symlink():
        return "symlink", None
    if not candidate.exists():
        return "missing", None
    if not candidate.is_file() or not candidate.resolve().is_relative_to(root):
        return "unavailable", None
    if candidate.stat().st_size > MAX_FILE_BYTES:
        return "too_large", None
    content = candidate.read_bytes()
    if b"\0" in content:
        return "binary", content
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return "binary", content
    return "text", content


def _encode_file(kind: str, content: bytes | None) -> dict[str, Any]:
    if kind == "text" and content is not None:
        return {"kind": kind, "content": base64.b64encode(content).decode("ascii")}
    if kind == "binary" and content is not None:
        return {"kind": kind, "hash": hashlib.sha256(content).hexdigest()}
    return {"kind": kind}


def _capture_baseline(workspace_path: str) -> dict[str, Any]:
    workspace = Path(workspace_path).resolve()
    try:
        repo = Path(
            _git(workspace, "rev-parse", "--show-toplevel").decode().strip()
        ).resolve()
    except RuntimeError as exc:
        raise RuntimeError("Git diff requires a Git repository") from exc
    prefix = workspace.relative_to(repo).as_posix()
    pathspec = "." if prefix == "." else prefix
    tracked = _tracked(repo, pathspec)
    if len(tracked) > MAX_TRACKED_FILES:
        raise RuntimeError("Too many tracked files to capture a run diff")
    dirty = _paths(
        _git(repo, "ls-files", "--modified", "--deleted", "-z", "--", pathspec)
    )
    untracked = _paths(
        _git(repo, "ls-files", "--others", "--exclude-standard", "-z", "--", pathspec)
    )
    if len(dirty | untracked) > MAX_DIRTY_FILES:
        raise RuntimeError("Too many pre-existing changed files to capture a run diff")
    overrides: dict[str, dict[str, Any]] = {}
    total = 0
    for filename in sorted(dirty | untracked):
        kind, content = _read_file(repo, filename)
        if kind in {"too_large", "symlink", "unavailable"}:
            raise RuntimeError(
                "A pre-existing changed file is too large or unsupported for an accurate run diff"
            )
        if content is not None and kind == "text":
            total += len(content)
            if total > MAX_BASELINE_BYTES:
                raise RuntimeError(
                    "Pre-existing changes exceed the diff snapshot limit"
                )
        overrides[filename] = _encode_file(kind, content)
        if kind == "text":
            overrides[filename]["mode"] = stat.S_IMODE((repo / filename).stat().st_mode)
    return {
        "repo": str(repo),
        "pathspec": pathspec,
        "tracked": tracked,
        "overrides": overrides,
    }


def _baseline_file(baseline: dict[str, Any], filename: str) -> tuple[str, bytes | None]:
    override = baseline["overrides"].get(filename)
    if override:
        kind = override["kind"]
        content = base64.b64decode(override["content"]) if kind == "text" else None
        return kind, content
    entry = baseline["tracked"].get(filename)
    if not entry:
        return "missing", None
    if entry["mode"] not in {"100644", "100755"}:
        return "unavailable", None
    repo = Path(baseline["repo"])
    size = int(_git(repo, "cat-file", "-s", entry["oid"]).strip())
    if size > MAX_FILE_BYTES:
        return "too_large", None
    content = _git(repo, "cat-file", "blob", entry["oid"])
    if b"\0" in content:
        return "binary", content
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return "binary", content
    return "text", content


def _build_diff(baseline: dict[str, Any]) -> dict[str, Any]:
    repo = Path(baseline["repo"])
    pathspec = baseline["pathspec"]
    current_tracked = _tracked(repo, pathspec)
    current_dirty = _paths(
        _git(repo, "ls-files", "--modified", "--deleted", "-z", "--", pathspec)
    )
    current_untracked = _paths(
        _git(repo, "ls-files", "--others", "--exclude-standard", "-z", "--", pathspec)
    )
    candidates = (
        set(baseline["overrides"])
        | current_dirty
        | current_untracked
        | {
            name
            for name in set(baseline["tracked"]) | set(current_tracked)
            if baseline["tracked"].get(name) != current_tracked.get(name)
        }
    )
    if len(candidates) > MAX_DIFF_FILES:
        raise RuntimeError("Too many changed files to render a run diff")
    files: list[dict[str, Any]] = []
    total_added = total_deleted = 0
    total_patch_chars = 0
    total_compare_bytes = 0
    for filename in sorted(candidates):
        old_kind, old = _baseline_file(baseline, filename)
        new_kind, new = _read_file(repo, filename)
        total_compare_bytes += len(old or b"") + len(new or b"")
        if total_compare_bytes > MAX_TOTAL_COMPARE_BYTES:
            raise RuntimeError("Changed files exceed the diff comparison limit")
        if old_kind == new_kind and old is not None and old == new:
            continue
        if old_kind == new_kind == "missing":
            continue
        override = baseline["overrides"].get(filename)
        if (
            old_kind == new_kind == "binary"
            and override
            and new is not None
            and override.get("hash") == hashlib.sha256(new).hexdigest()
        ):
            continue
        status = (
            "added"
            if old_kind == "missing"
            else "deleted"
            if new_kind == "missing"
            else "modified"
        )
        entry: dict[str, Any] = {
            "path": filename,
            "status": status,
            "added": 0,
            "deleted": 0,
            "patch": "",
            "note": None,
            "final_hash": hashlib.sha256(new).hexdigest() if new is not None else None,
            "final_mode": stat.S_IMODE((repo / filename).stat().st_mode)
            if new_kind in {"text", "binary"}
            else None,
            "revertable": old_kind in {"text", "missing"}
            and new_kind in {"text", "missing"},
        }
        if old_kind in {"text", "missing"} and new_kind in {"text", "missing"}:
            old_lines = (old or b"").decode().splitlines()
            new_lines = (new or b"").decode().splitlines()
            for tag, first, last, start, end in difflib.SequenceMatcher(
                None, old_lines, new_lines
            ).get_opcodes():
                if tag != "equal":
                    entry["deleted"] += last - first
                    entry["added"] += end - start
            patch_lines = list(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=f"a/{filename}",
                    tofile=f"b/{filename}",
                    n=3,
                    lineterm="",
                )
            )
            patch = "\n".join(patch_lines)
            if not patch and old_kind != new_kind:
                entry["note"] = "Empty file added or removed"
            elif not patch and old != new:
                entry["note"] = "Only line endings changed"
            remaining = max(0, MAX_TOTAL_PATCH_CHARS - total_patch_chars)
            patch_limit = min(MAX_PATCH_CHARS, remaining)
            if len(patch) > patch_limit:
                entry["patch"] = patch[:patch_limit]
                entry["note"] = "Diff preview truncated for this file"
            else:
                entry["patch"] = patch
            total_patch_chars += len(entry["patch"])
        else:
            entry["note"] = "Binary, symlink, or oversized file; text diff unavailable"
        total_added += entry["added"]
        total_deleted += entry["deleted"]
        files.append(entry)
    return {
        "files": files,
        "file_count": len(files),
        "added": total_added,
        "deleted": total_deleted,
        "captured_at": datetime.now(UTC).isoformat(),
    }


def _restore_baseline(baseline: dict[str, Any], files: list[dict[str, Any]]) -> None:
    """Restore only this run's text changes after validating the entire review."""
    root = Path(baseline["repo"]).resolve()
    workspace = root if baseline["pathspec"] == "." else root / baseline["pathspec"]
    restores: list[tuple[Path, str, bytes | None, int | None]] = []
    for file in files:
        relative = Path(file["path"])
        candidate = root / relative
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or candidate.is_symlink()
            or not candidate.resolve().is_relative_to(workspace)
            or any(
                parent.is_symlink()
                for parent in candidate.parents
                if parent != root and parent.is_relative_to(root)
            )
        ):
            raise RuntimeError(
                "A changed file is outside the workspace or is a symlink"
            )
        old_kind, old = _baseline_file(baseline, file["path"])
        if old_kind not in {"text", "missing"}:
            raise RuntimeError(
                "This run includes a file that cannot be safely restored"
            )
        current_kind, current = _read_file(root, file["path"])
        if file["status"] == "deleted":
            if current_kind != "missing":
                raise RuntimeError("A file has changed since this review was saved")
        elif (
            current_kind != "text"
            or current is None
            or hashlib.sha256(current).hexdigest() != file["final_hash"]
            or (
                file.get("final_mode") is not None
                and stat.S_IMODE(candidate.stat().st_mode) != file["final_mode"]
            )
        ):
            raise RuntimeError("A file has changed since this review was saved")
        if old_kind == "text" and (
            not candidate.parent.exists() or not candidate.parent.is_dir()
        ):
            raise RuntimeError(
                "A parent directory is missing; changes cannot be safely restored"
            )
        override = baseline["overrides"].get(file["path"], {})
        tracked = baseline["tracked"].get(file["path"], {})
        mode = override.get("mode") or (
            0o755 if tracked.get("mode") == "100755" else 0o644
        )
        restores.append((candidate, old_kind, old, mode))

    for candidate, old_kind, old, mode in restores:
        if old_kind == "missing":
            candidate.unlink()
        else:
            descriptor, temporary = tempfile.mkstemp(
                prefix=".agent-workbench-", dir=candidate.parent
            )
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(old or b"")
                if mode is not None:
                    os.chmod(temporary, mode)
                os.replace(temporary, candidate)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)


class RunDiffService:
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.session_factory = session_factory
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, run_id: int) -> asyncio.Lock:
        return self._locks.setdefault(run_id, asyncio.Lock())

    async def capture(self, run_id: int, workspace_path: str) -> None:
        try:
            baseline = await asyncio.to_thread(_capture_baseline, workspace_path)
            status, reason = "capturing", None
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            baseline = None
            status, reason = "unavailable", str(exc)[:300] or "Git diff unavailable"
        async with self.session_factory() as db:
            db.add(
                models.RunDiff(
                    run_id=run_id,
                    workspace_path=workspace_path,
                    repo_path=baseline["repo"] if baseline else workspace_path,
                    baseline=baseline,
                    result={},
                    status=status,
                    reason=reason,
                )
            )
            await db.commit()

    async def refresh(
        self, run_id: int, *, final: bool = False
    ) -> dict[str, Any] | None:
        async with self._lock(run_id), self.session_factory() as db:
            record = await db.get(models.RunDiff, run_id)
            if not record:
                return None
            if record.final:
                return self._response(record)
            if record.baseline:
                try:
                    record.result = await asyncio.to_thread(
                        _build_diff, record.baseline
                    )
                    record.status = "ready"
                    record.reason = None
                except (
                    OSError,
                    RuntimeError,
                    subprocess.TimeoutExpired,
                    ValueError,
                ) as exc:
                    record.status = "unavailable"
                    record.reason = str(exc)[:300] or "Git diff unavailable"
            if final:
                record.final = True
            await db.commit()
            return self._response(record)

    async def decide(self, run_id: int, action: str) -> dict[str, Any] | None:
        if action not in {"accept", "revert"}:
            raise ValueError("Unknown review action")
        async with self._lock(run_id), self.session_factory() as db:
            record = await db.get(models.RunDiff, run_id)
            if not record:
                return None
            if not record.final or record.status != "ready":
                raise RuntimeError("The run must finish before reviewing its changes")
            if (record.result or {}).get("decision"):
                raise RuntimeError("Changes for this run have already been reviewed")
            if action == "revert":
                if not record.baseline:
                    raise RuntimeError(
                        "A before-run snapshot was not saved for this review"
                    )
                await asyncio.to_thread(
                    _restore_baseline, record.baseline, record.result.get("files", [])
                )
            record.result = {
                **record.result,
                "decision": "accepted" if action == "accept" else "reverted",
            }
            await db.commit()
            return await self.get(run_id)

    async def get(self, run_id: int) -> dict[str, Any] | None:
        async with self.session_factory() as db:
            record = await db.get(models.RunDiff, run_id)
            if not record:
                return None
            result = self._response(record)
            if record.final and result["files"]:
                try:
                    result["stale"] = await asyncio.to_thread(
                        self._is_stale, record.repo_path, result["files"]
                    )
                except OSError:
                    result["stale"] = None
            return result

    @staticmethod
    def _is_stale(repo_path: str, files: list[dict[str, Any]]) -> bool:
        root = Path(repo_path).resolve()
        for file in files:
            candidate = root / file["path"]
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(root):
                return True
            current_kind, current = _read_file(root, file["path"])
            if file["status"] == "deleted":
                if current_kind != "missing":
                    return True
            elif (
                current_kind not in {"text", "binary"}
                or (
                    current is not None
                    and file["final_hash"] is not None
                    and hashlib.sha256(current).hexdigest() != file["final_hash"]
                )
                or (
                    file.get("final_mode") is not None
                    and stat.S_IMODE(candidate.stat().st_mode) != file["final_mode"]
                )
            ):
                return True
        return False

    @staticmethod
    def _response(record: models.RunDiff) -> dict[str, Any]:
        result = record.result or {}
        return {
            "run_id": record.run_id,
            "status": record.status,
            "final": record.final,
            "reason": record.reason,
            "files": result.get("files", []),
            "file_count": result.get("file_count", 0),
            "added": result.get("added", 0),
            "deleted": result.get("deleted", 0),
            "captured_at": result.get("captured_at"),
            "stale": None,
            "decision": result.get("decision"),
            "can_revert": bool(record.baseline)
            and record.final
            and record.status == "ready"
            and not result.get("decision")
            and all(file.get("revertable") for file in result.get("files", [])),
        }
