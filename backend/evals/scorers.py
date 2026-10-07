from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import re
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ScoreStatus = Literal["pass", "fail", "unavailable"]
AttemptOutcome = Literal["pass", "fail", "infra_error"]
FileAssertionKind = Literal["exists", "absent", "contains", "regex", "json_value"]
MAX_EVIDENCE_CHARS = 16_000
MAX_COMMAND_OUTPUT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class ScoreResult:
    scorer_key: str
    version: int
    required: bool
    status: ScoreStatus
    passed: bool | None
    value: dict[str, Any]
    summary: str
    evidence: dict[str, Any]
    full_output: dict[str, str] | None = None


@dataclass(frozen=True)
class CommandScorerSpec:
    key: str
    argv: tuple[str, ...]
    expected_exit_codes: tuple[int, ...] = (0,)
    timeout_seconds: float = 120
    environment: dict[str, str] = field(default_factory=dict)
    required: bool = True


@dataclass(frozen=True)
class FileAssertionSpec:
    key: str
    path: str
    assertion: FileAssertionKind
    expected: Any = None
    json_path: str | None = None
    required: bool = True


@dataclass(frozen=True)
class DiffConstraintSpec:
    key: str
    allowed: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    required_paths: tuple[str, ...] = ()
    required: bool = True


def _bounded(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_EVIDENCE_CHARS:
        return text, False
    return text[:MAX_EVIDENCE_CHARS] + "\n… [truncated]", True


def _safe_path(worktree: str | Path, relative_path: str) -> Path:
    root = Path(worktree).resolve()
    requested = Path(relative_path)
    if requested.is_absolute():
        raise ValueError("Scorer paths must be relative to the worktree")
    candidate = (root / requested).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Scorer path escapes the worktree")
    return candidate


async def score_command(
    spec: CommandScorerSpec,
    worktree: str | Path,
    *,
    capture_full_output: bool = False,
) -> ScoreResult:
    if not spec.argv:
        return ScoreResult(
            spec.key,
            1,
            spec.required,
            "unavailable",
            None,
            {},
            "Command scorer has no executable",
            {},
        )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "TMPDIR"}
    }
    environment.update(spec.environment)
    process_options = {"start_new_session": True} if os.name != "nt" else {}
    try:
        process = await asyncio.create_subprocess_exec(
            *spec.argv,
            cwd=str(Path(worktree).resolve()),
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **process_options,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return ScoreResult(
            spec.key,
            1,
            spec.required,
            "unavailable",
            None,
            {},
            "Command scorer could not start",
            {"error": str(exc)},
        )

    async def read_output(stream: asyncio.StreamReader) -> bytes:
        result = bytearray()
        while chunk := await stream.read(64 * 1024):
            if len(result) + len(chunk) > MAX_COMMAND_OUTPUT_BYTES:
                raise OverflowError("Scorer output limit exceeded")
            result.extend(chunk)
        return bytes(result)

    tasks = [
        asyncio.create_task(read_output(process.stdout)),
        asyncio.create_task(read_output(process.stderr)),
        asyncio.create_task(process.wait()),
    ]
    try:
        stdout, stderr, _ = await asyncio.wait_for(
            asyncio.gather(*tasks), timeout=spec.timeout_seconds
        )
    except (TimeoutError, OverflowError, asyncio.CancelledError) as exc:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.returncode is None:
            process.kill()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Drain residual pipe buffers after killing the group so paused transports
        # cannot prevent process reaping after an output-limit failure.
        await process.communicate()
        if isinstance(exc, asyncio.CancelledError):
            raise
        oversized = isinstance(exc, OverflowError)
        return ScoreResult(
            spec.key,
            1,
            spec.required,
            "unavailable",
            None,
            {"output_limit_bytes_per_stream": MAX_COMMAND_OUTPUT_BYTES}
            if oversized
            else {"timeout_seconds": spec.timeout_seconds},
            "Command scorer exceeded the output limit"
            if oversized
            else "Command scorer timed out",
            {},
        )
    stdout_text = stdout.decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")
    stdout_preview, stdout_truncated = _bounded(stdout_text)
    stderr_preview, stderr_truncated = _bounded(stderr_text)
    passed = process.returncode in spec.expected_exit_codes
    return ScoreResult(
        spec.key,
        1,
        spec.required,
        "pass" if passed else "fail",
        passed,
        {"exit_code": process.returncode},
        "Command exited with an accepted code"
        if passed
        else f"Command exited with code {process.returncode}",
        {
            "argv": list(spec.argv),
            "stdout": stdout_preview,
            "stderr": stderr_preview,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        },
        {"stdout": stdout_text, "stderr": stderr_text}
        if capture_full_output and (stdout_truncated or stderr_truncated)
        else None,
    )


def _json_value(value: Any, path: str) -> Any:
    current = value
    for component in path.split(".") if path else ():
        if isinstance(current, list):
            current = current[int(component)]
        elif isinstance(current, dict):
            current = current[component]
        else:
            raise KeyError(component)
    return current


def score_file_assertion(spec: FileAssertionSpec, worktree: str | Path) -> ScoreResult:
    try:
        path = _safe_path(worktree, spec.path)
        exists = path.exists()
        actual: Any = None
        if spec.assertion == "exists":
            passed = exists
        elif spec.assertion == "absent":
            passed = not exists
        elif not exists or not path.is_file():
            passed = False
        elif spec.assertion == "contains":
            actual = path.read_text(errors="replace")
            passed = str(spec.expected) in actual
        elif spec.assertion == "regex":
            actual = path.read_text(errors="replace")
            passed = re.search(str(spec.expected), actual) is not None
        elif spec.assertion == "json_value":
            actual = _json_value(json.loads(path.read_text()), spec.json_path or "")
            passed = actual == spec.expected
        else:
            raise ValueError(f"Unsupported file assertion: {spec.assertion}")
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        IndexError,
        ValueError,
        re.error,
    ) as exc:
        return ScoreResult(
            spec.key,
            1,
            spec.required,
            "unavailable",
            None,
            {},
            "File assertion could not be evaluated",
            {"path": spec.path, "error": str(exc)},
        )
    return ScoreResult(
        spec.key,
        1,
        spec.required,
        "pass" if passed else "fail",
        passed,
        {"actual": actual if spec.assertion == "json_value" else exists},
        f"File assertion {spec.assertion} {'passed' if passed else 'failed'}",
        {"path": spec.path},
    )


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def score_diff_constraints(
    spec: DiffConstraintSpec, changed_paths: set[str]
) -> ScoreResult:
    outside_allowed = (
        sorted(path for path in changed_paths if not _matches(path, spec.allowed))
        if spec.allowed
        else []
    )
    forbidden = sorted(path for path in changed_paths if _matches(path, spec.forbidden))
    missing_required = sorted(
        pattern
        for pattern in spec.required_paths
        if not any(fnmatch.fnmatchcase(path, pattern) for path in changed_paths)
    )
    passed = not outside_allowed and not forbidden and not missing_required
    return ScoreResult(
        spec.key,
        1,
        spec.required,
        "pass" if passed else "fail",
        passed,
        {"changed_paths": sorted(changed_paths)},
        "Diff constraints passed" if passed else "Diff constraints failed",
        {
            "outside_allowed": outside_allowed,
            "forbidden": forbidden,
            "missing_required": missing_required,
        },
    )


def score_tamper(
    changed_paths: set[str], forbidden_paths: tuple[str, ...], *, required: bool = True
) -> ScoreResult:
    return score_diff_constraints(
        DiffConstraintSpec(
            key="tamper",
            forbidden=forbidden_paths,
            required=required,
        ),
        changed_paths,
    )


def classify_required_scores(scores: list[ScoreResult]) -> AttemptOutcome:
    required = [score for score in scores if score.required]
    if not required or any(score.status == "unavailable" for score in required):
        return "infra_error"
    if any(score.status == "fail" for score in required):
        return "fail"
    return "pass"
