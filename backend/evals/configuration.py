from __future__ import annotations

import asyncio
import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any

INSTRUCTION_LIMIT = 32 * 1024
SECRET_ASSIGNMENT = re.compile(
    r"(?im)([\w.-]*(?:token|password|secret|credential|api[_-]?key|authorization)[\w.-]*[\"']?\s*[:=]\s*)([^\r\n]+)"
)
SECRET_VALUE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._~+/-]+=*)", re.IGNORECASE
)


def redact_text(content: str) -> str:
    return SECRET_VALUE.sub(
        "[REDACTED]", SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", content)
    )


def capture_instruction_files(
    workspace: Path | None,
    repository_root: Path | None,
    codex_home: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Observe the standard root-to-cwd chain, never recursively scan a repo."""
    directories: list[tuple[Path, str, str]] = [(codex_home, "global", "$CODEX_HOME")]
    if workspace is not None:
        workspace = workspace.resolve()
        root = (repository_root or workspace).resolve()
        if not workspace.is_relative_to(root):
            raise ValueError("Instruction workspace must be inside the repository root")
        relative = workspace.relative_to(root)
        chain = [root]
        for part in relative.parts:
            chain.append(chain[-1] / part)
        directories.extend(
            (directory, "project", directory.relative_to(root).as_posix())
            for directory in chain
        )
    files: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    remaining = INSTRUCTION_LIMIT
    for directory, scope, label in directories:
        for name in ("AGENTS.override.md", "AGENTS.md"):
            path = directory / name
            if not path.exists() and not path.is_symlink():
                continue
            try:
                # Do not follow symlinks, including swapped final path components.
                if directory.resolve() != directory.absolute():
                    raise ValueError("Instruction directory contains a symlink")
                descriptor = os.open(
                    path,
                    os.O_RDONLY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_NONBLOCK", 0),
                )
                with os.fdopen(descriptor, "rb") as handle:
                    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                        raise ValueError("Instruction source is not a regular file")
                    data = handle.read(INSTRUCTION_LIMIT + 1)
                if not data.strip():
                    continue
                original = data[:remaining].decode("utf-8", errors="replace")
                content = redact_text(original)
                truncated = len(data) > remaining
                files.append(
                    {
                        "kind": "file",
                        "scope": scope,
                        "path": f"{label}/{name}",
                        "ordinal": len(files),
                        "content": content,
                        "control": "observed",
                        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
                        "redacted": content != original,
                        "truncated": truncated,
                    }
                )
                remaining = max(0, remaining - len(data))
                if truncated:
                    observations.append(
                        {
                            "kind": "instruction_capture",
                            "detail": "Instruction chain reached the 32 KiB capture limit",
                        }
                    )
                break
            except (OSError, ValueError):
                observations.append(
                    {
                        "kind": "instruction_capture",
                        "detail": f"Could not safely read {label}/{name}",
                    }
                )
                break
        if remaining == 0:
            break
    observations.append(
        {
            "kind": "instruction_discovery",
            "detail": "Standard names only; custom fallback names and runtime discovery are not controlled",
        }
    )
    return files, observations


async def detect_cli_version(command: str | None) -> str | None:
    if not command:
        return None
    try:
        process = await asyncio.create_subprocess_exec(
            command,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None

    async def read_version() -> bytes:
        chunks = bytearray()
        while len(chunks) <= 100:
            chunk = await process.stdout.read(101 - len(chunks))
            if not chunk:
                await process.wait()
                break
            chunks.extend(chunk)
        if len(chunks) > 100:
            if process.returncode is None:
                process.kill()
            await process.wait()
        return bytes(chunks)

    try:
        output = await asyncio.wait_for(read_version(), timeout=3)
    except (TimeoutError, asyncio.CancelledError) as exc:
        if process.returncode is None:
            process.kill()
        await process.wait()
        if isinstance(exc, asyncio.CancelledError):
            raise
        return None
    value = output.decode(errors="replace").strip()
    if (
        process.returncode != 0
        or len(value) > 100
        or not re.fullmatch(r"codex(?:-cli)?\s+\d[\w.+-]*", value)
    ):
        return None
    return value


def controlled_execution(
    instructions: list[dict[str, Any]],
    codex_config: dict[str, Any],
    sandbox_policy: dict[str, Any],
) -> tuple[str, str, tuple[str, ...]]:
    """Only explicit supported controls may affect an eval process."""
    sandbox = sandbox_policy.get("mode", "workspace-write")
    if sandbox not in {"read-only", "workspace-write"}:
        raise ValueError("Eval sandbox must be read-only or workspace-write")
    if sandbox_policy.get("network", False) is not False:
        raise ValueError("Network-enabled eval configurations are not supported")
    forbidden = {
        "sandbox_mode",
        "sandbox_workspace_write",
        "sandbox_workspace_write.network_access",
        "approval_policy",
        "dangerously_bypass_approvals_and_sandbox",
    }
    if any(key in forbidden or key.startswith("sandbox_") for key in codex_config):
        raise ValueError(
            "Use sandbox_policy rather than generic sandbox or approval overrides"
        )
    preambles = [
        item["content"]
        for item in instructions
        if item.get("kind") == "preamble" and isinstance(item.get("content"), str)
    ]
    return (
        sandbox,
        "\n\n".join(preambles),
        ("sandbox_workspace_write.network_access=false",),
    )


def reproducibility_warnings(snapshot: Any) -> list[str]:
    warnings = []
    if not snapshot.model:
        warnings.append("Default model is observed, not pinned to this snapshot")
    if not snapshot.cli_version:
        warnings.append("Codex CLI version was not recorded")
    else:
        warnings.append(
            "Recorded CLI version is observed; the installed executable is not pinned"
        )
    if snapshot.codex_config_json:
        warnings.append(
            "Generic project settings are observed only and are not applied to attempts"
        )
    if any(item.get("kind") != "preamble" for item in snapshot.instructions_json):
        warnings.append(
            "Instruction files are observed only; only the explicit preamble is applied"
        )
    warnings.append(
        "Project instruction files at the case baseline and external authentication remain observed inputs"
    )
    if snapshot.uncontrolled_inputs_json:
        warnings.append("Additional uncontrolled inputs were declared")
        warnings.extend(
            f"Observed: {item['detail']}"
            for item in snapshot.uncontrolled_inputs_json
            if isinstance(item.get("detail"), str)
        )
    return warnings
