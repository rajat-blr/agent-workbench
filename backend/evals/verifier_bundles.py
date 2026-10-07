from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path, PurePosixPath
from typing import Any

from evals.worktrees import WorktreeError

MAX_VERIFIER_FILES = 100
MAX_VERIFIER_BUNDLE_BYTES = 2 * 1024 * 1024


def _safe_path(raw: str) -> PurePosixPath:
    if not isinstance(raw, str):
        raise TypeError("Held-out verifier paths must be strings")
    components = raw.split("/")
    path = PurePosixPath(raw)
    if (
        not raw
        or "\\" in raw
        or "\x00" in raw
        or ":" in components[0]
        or path.is_absolute()
        or any(part in {"", ".", "..", ".git"} for part in components)
    ):
        raise ValueError(f"Unsafe held-out verifier path: {raw or '<empty>'}")
    return path


def build_verifier_bundle(files: list[dict[str, str]]) -> bytes:
    if len(files) > MAX_VERIFIER_FILES:
        raise ValueError(f"Verifier bundles support at most {MAX_VERIFIER_FILES} files")
    encoded = []
    seen: set[str] = set()
    for item in files:
        path = _safe_path(item["path"]).as_posix()
        if path in seen:
            raise ValueError(f"Duplicate held-out verifier path: {path}")
        seen.add(path)
        encoded.append(
            {
                "path": path,
                "content_base64": base64.b64encode(item["content"].encode()).decode(),
            }
        )
    payload = json.dumps(
        {"version": 1, "files": sorted(encoded, key=lambda item: item["path"])},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if len(payload) > MAX_VERIFIER_BUNDLE_BYTES:
        raise ValueError("Verifier bundle exceeds the 2 MiB limit")
    return payload


def parse_verifier_bundle(content: bytes) -> list[tuple[PurePosixPath, bytes]]:
    if len(content) > MAX_VERIFIER_BUNDLE_BYTES:
        raise WorktreeError("Verifier bundle exceeds the 2 MiB limit")
    try:
        payload: Any = json.loads(content)
        raw_files = payload["files"]
        if payload.get("version") != 1 or not isinstance(raw_files, list):
            raise ValueError
        files = []
        seen: set[str] = set()
        for item in raw_files:
            path = _safe_path(item["path"])
            if path.as_posix() in seen:
                raise ValueError
            seen.add(path.as_posix())
            files.append((path, base64.b64decode(item["content_base64"], validate=True)))
    except (KeyError, TypeError, ValueError, UnicodeError, binascii.Error) as exc:
        raise WorktreeError("Verifier bundle is invalid") from exc
    if len(files) > MAX_VERIFIER_FILES:
        raise WorktreeError("Verifier bundle contains too many files")
    return files


def verifier_paths(content: bytes) -> list[str]:
    return [path.as_posix() for path, _ in parse_verifier_bundle(content)]


def materialize_verifier_bundle(content: bytes, worktree: Path) -> list[str]:
    written = []
    root = worktree.resolve()
    for relative, data in parse_verifier_bundle(content):
        raw_destination = root / relative.as_posix()
        destination = raw_destination.resolve()
        if not destination.is_relative_to(root):
            raise WorktreeError("Verifier bundle escapes the worktree")
        if raw_destination.exists() or raw_destination.is_symlink():
            raise WorktreeError(
                f"Held-out verifier path is already agent-visible: {relative}"
            )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        except OSError as exc:
            raise WorktreeError(
                f"Could not materialize held-out verifier path: {relative}"
            ) from exc
        written.append(relative.as_posix())
    return written
