import asyncio
import json
import logging
import os
import signal
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from artifacts import ArtifactStore, ArtifactWriter, StoredArtifact
from codebase_map import MAP_INSTRUCTIONS, extract_codebase_map
from event_broker import AgentEvent, EventBroker

EventPersister = Callable[
    [int | None, int, str, dict[str, Any], str | None], Awaitable[AgentEvent]
]
DiffFinalizer = Callable[[int], Awaitable[dict[str, Any] | None]]
ArtifactPersister = Callable[[int, StoredArtifact], Awaitable[dict[str, Any]]]
logger = logging.getLogger(__name__)
SandboxMode = Literal["read-only", "workspace-write"]
ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]
MAX_PARSED_JSONL_LINE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ExecutionOptions:
    """Per-run inputs that may differ between chat and eval executions."""

    model: str | None = None
    reasoning_effort: ReasoningEffort | None = None
    sandbox: SandboxMode | None = None
    config_overrides: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None
    ephemeral: bool = False
    ignore_user_config: bool = False

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("Execution timeout must be greater than zero")
        if any("=" not in override for override in self.config_overrides):
            raise ValueError("Codex config overrides must use key=value syntax")
        if any(not key or "=" in key or "\0" in key for key in self.environment):
            raise ValueError("Execution environment contains an invalid variable name")
        if any("\0" in value for value in self.environment.values()):
            raise ValueError("Execution environment values cannot contain null bytes")


class AgentAdapter(Protocol):
    async def start(
        self,
        workspace_path: str,
        prompt: str,
        thread_id: str | None = None,
        options: ExecutionOptions | None = None,
    ) -> asyncio.subprocess.Process: ...


class CodexAgentAdapter:
    def __init__(
        self,
        command: str = "codex",
        model: str | None = None,
        sandbox: SandboxMode = "workspace-write",
        skip_git_repo_check: bool = False,
    ) -> None:
        if sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("Codex sandbox must be read-only or workspace-write")
        self.command = command
        self.model = model
        self.sandbox = sandbox
        self.skip_git_repo_check = skip_git_repo_check

    def build_command(
        self,
        workspace_path: str,
        prompt: str,
        thread_id: str | None,
        options: ExecutionOptions | None = None,
    ) -> list[str]:
        options = options or ExecutionOptions()
        sandbox = options.sandbox or self.sandbox
        if sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("Codex sandbox must be read-only or workspace-write")
        command = [
            self.command,
            "exec",
            "--json",
            "--color",
            "never",
            "--sandbox",
            sandbox,
        ]
        model = options.model if options.model is not None else self.model
        if model:
            command.extend(["--model", model])
        if options.reasoning_effort:
            command.extend(
                [
                    "--config",
                    f'model_reasoning_effort="{options.reasoning_effort}"',
                ]
            )
        for override in options.config_overrides:
            command.extend(["--config", override])
        if options.ephemeral:
            command.append("--ephemeral")
        if options.ignore_user_config:
            command.append("--ignore-user-config")
        workspace = Path(workspace_path).resolve()
        is_git_workspace = any(
            (candidate / ".git").exists()
            for candidate in (workspace, *workspace.parents)
        )
        if self.skip_git_repo_check or not is_git_workspace:
            command.append("--skip-git-repo-check")
        if thread_id:
            command.extend(["resume", thread_id, "-"])
        else:
            command.extend(["--cd", workspace_path, "-"])
        return command

    @staticmethod
    def build_environment(options: ExecutionOptions | None = None) -> dict[str, str]:
        options = options or ExecutionOptions()
        safe_environment = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "CODEX_HOME",
                "HOME",
                "LANG",
                "LC_ALL",
                "LC_CTYPE",
                "LOGNAME",
                "PATH",
                "SHELL",
                "SSH_AUTH_SOCK",
                "TERM",
                "TMPDIR",
                "USER",
            }
        }
        safe_environment.update(options.environment)
        return safe_environment

    async def start(
        self,
        workspace_path: str,
        prompt: str,
        thread_id: str | None = None,
        options: ExecutionOptions | None = None,
    ) -> asyncio.subprocess.Process:
        options = options or ExecutionOptions()
        safe_environment = self.build_environment(options)
        process_options: dict[str, Any] = {}
        if os.name != "nt":
            process_options["start_new_session"] = True
        try:
            process = await asyncio.create_subprocess_exec(
                *self.build_command(workspace_path, prompt, thread_id, options),
                cwd=workspace_path,
                env=safe_environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024 * 1024,
                **process_options,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Codex CLI was not found. Install Codex and sign in before sending a message."
            ) from None
        except PermissionError:
            raise RuntimeError(
                "Codex CLI was found but could not be executed. Check its file permissions."
            ) from None
        if not process.stdin:
            process.terminate()
            raise RuntimeError("Codex stdin is unavailable")
        try:
            process.stdin.write(prompt.encode())
            await process.stdin.drain()
        except BrokenPipeError, ConnectionResetError:
            await process.wait()
            raise RuntimeError("Codex exited before accepting the prompt") from None
        finally:
            process.stdin.close()
        return process


@dataclass
class RunningAgent:
    run_id: int
    session_id: int | None
    process: asyncio.subprocess.Process
    output_task: asyncio.Task[None]
    error_task: asyncio.Task[None]
    timeout_seconds: float
    raw_output_writer: ArtifactWriter | None = None
    watch_task: asyncio.Task[None] | None = None
    cancel_ready: asyncio.Event | None = None


class AgentRuntimeManager:
    def __init__(
        self,
        broker: EventBroker,
        adapter: AgentAdapter,
        persist_event: EventPersister,
        timeout_seconds: int = 3600,
        diff_finalizer: DiffFinalizer | None = None,
        artifact_store: ArtifactStore | None = None,
        artifact_persister: ArtifactPersister | None = None,
    ) -> None:
        self.broker = broker
        self.adapter = adapter
        self.persist_event = persist_event
        self.timeout_seconds = timeout_seconds
        self.diff_finalizer = diff_finalizer
        self.artifact_store = artifact_store
        self.artifact_persister = artifact_persister
        self._agents: dict[int, RunningAgent] = {}
        self._cancelled: set[int] = set()
        self._lock = asyncio.Lock()

    async def _emit(
        self,
        session_id: int | None,
        run_id: int,
        event_type: str,
        payload: dict[str, Any],
        source_event_id: str | None = None,
    ) -> AgentEvent:
        event = await self.persist_event(
            session_id, run_id, event_type, payload, source_event_id
        )
        item = payload.get("item")
        meaningful_item = isinstance(item, dict) and item.get("type") in {
            "command_execution",
            "file_change",
            "plan_update",
        }
        if (
            event_type.startswith(("session.", "artifact."))
            or event_type in {"assistant.text", "agent.error"}
            or (
                event_type in {"codex.item.started", "codex.item.completed"}
                and meaningful_item
            )
        ):
            self.broker.publish(event)
        return event

    async def start(
        self,
        session_id: int | None,
        run_id: int,
        workspace_path: str,
        prompt: str,
        thread_id: str | None = None,
        *,
        mode: str = "chat",
        execution: ExecutionOptions | None = None,
    ) -> None:
        async with self._lock:
            existing = self._agents.get(run_id)
            if existing and existing.process.returncode is None:
                raise RuntimeError("This run is already active")
            if not Path(workspace_path).is_dir():
                raise ValueError("Workspace path must be an existing directory")
            agent_prompt = prompt + MAP_INSTRUCTIONS if mode == "map" else prompt
            raw_output_writer = (
                self.artifact_store.open_writer(
                    run_id,
                    "raw_jsonl",
                    {"content_type": "application/x-ndjson"},
                )
                if self.artifact_store
                else None
            )
            try:
                execution = execution or ExecutionOptions()
                process = await self.adapter.start(
                    workspace_path, agent_prompt, thread_id, execution
                )
            except Exception:
                if raw_output_writer:
                    raw_output_writer.abort()
                raise
            output_task = asyncio.create_task(
                self._read_stdout(
                    session_id,
                    run_id,
                    process.stdout,
                    workspace_path,
                    mode,
                    raw_output_writer,
                )
            )
            error_task = asyncio.create_task(
                self._read_stderr(session_id, run_id, process.stderr)
            )
            agent = RunningAgent(
                run_id,
                session_id,
                process,
                output_task,
                error_task,
                execution.timeout_seconds or self.timeout_seconds,
                raw_output_writer,
            )
            self._agents[run_id] = agent
            try:
                await self._emit(
                    session_id,
                    run_id,
                    "session.started",
                    {
                        "pid": process.pid,
                        "workspace_path": workspace_path,
                        "mode": mode,
                    },
                )
            except Exception:
                self._terminate_process(process)
                output_task.cancel()
                error_task.cancel()
                if raw_output_writer:
                    raw_output_writer.abort()
                self._agents.pop(run_id, None)
                raise
            agent.watch_task = asyncio.create_task(
                self._watch_process(session_id, agent)
            )

    async def cancel(self, run_id: int) -> bool:
        agent = self._agents.get(run_id)
        if not agent or agent.process.returncode is not None:
            return False
        agent.cancel_ready = asyncio.Event()
        self._cancelled.add(run_id)
        try:
            await self._emit(
                agent.session_id,
                agent.run_id,
                "session.stopping",
                {"reason": "cancelled"},
            )
        finally:
            self._terminate_process(agent.process)
            agent.cancel_ready.set()
        return True

    async def wait(self, run_id: int) -> None:
        """Wait for a started run to finish without exposing process internals."""
        async with self._lock:
            agent = self._agents.get(run_id)
            watch_task = agent.watch_task if agent else None
        if watch_task:
            await asyncio.shield(watch_task)

    def _terminate_process(
        self, process: asyncio.subprocess.Process, *, force: bool = False
    ) -> None:
        if process.returncode is not None:
            return
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
                return
            except ProcessLookupError:
                pass
        if force:
            process.kill()
        else:
            process.terminate()

    async def _read_stdout(
        self,
        session_id: int | None,
        run_id: int,
        stream: asyncio.StreamReader | None,
        workspace_path: str,
        mode: str,
        raw_output_writer: ArtifactWriter | None,
    ) -> None:
        if not stream:
            return
        map_emitted = False
        async for line, line_truncated in self._stdout_lines(stream, raw_output_writer):
            text = line.decode(errors="replace").rstrip("\r")
            if line_truncated:
                await self._emit(
                    session_id,
                    run_id,
                    "codex.output",
                    {"content": text + "\n… [line too large; full output in artifact]"},
                )
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                await self._emit(session_id, run_id, "codex.output", {"content": text})
                continue
            if not isinstance(message, dict) or not isinstance(
                message.get("type"), str
            ):
                await self._emit(session_id, run_id, "codex.output", {"content": text})
                continue
            raw_type = message["type"]
            item = message.get("item")
            source_event_id = item.get("id") if isinstance(item, dict) else None
            if (
                raw_type == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "agent_message"
                and isinstance(item.get("text"), str)
            ):
                content = item["text"]
                if mode == "map":
                    content, map_data = extract_codebase_map(content, workspace_path)
                else:
                    map_data = None
                if content:
                    await self._emit(
                        session_id,
                        run_id,
                        "assistant.text",
                        {"content": content},
                        source_event_id,
                    )
                if map_data:
                    map_emitted = True
                    await self._emit(
                        session_id,
                        run_id,
                        "artifact.codebase_map",
                        map_data,
                        source_event_id,
                    )
            else:
                payload = {
                    key: value for key, value in message.items() if key != "type"
                }
                await self._emit(
                    session_id, run_id, f"codex.{raw_type}", payload, source_event_id
                )
        if mode == "map" and not map_emitted:
            await self._emit(
                session_id,
                run_id,
                "artifact.map_unavailable",
                {"reason": "Codex did not return a valid codebase map"},
            )

    @staticmethod
    async def _stdout_lines(
        stream: asyncio.StreamReader,
        raw_output_writer: ArtifactWriter | None,
    ) -> AsyncIterator[tuple[bytes, bool]]:
        buffer = bytearray()
        truncated = False
        while chunk := await stream.read(64 * 1024):
            if raw_output_writer:
                raw_output_writer.write(chunk)
            parts = chunk.split(b"\n")
            for index, part in enumerate(parts):
                remaining = MAX_PARSED_JSONL_LINE_BYTES - len(buffer)
                if remaining > 0:
                    buffer.extend(part[:remaining])
                if len(part) > remaining:
                    truncated = True
                if index < len(parts) - 1:
                    yield bytes(buffer), truncated
                    buffer.clear()
                    truncated = False
        if buffer or truncated:
            yield bytes(buffer), truncated

    async def _read_stderr(
        self, session_id: int | None, run_id: int, stream: asyncio.StreamReader | None
    ) -> None:
        if not stream:
            return
        while line := await stream.readline():
            content = line.decode(errors="replace").rstrip("\r\n")
            if content:
                await self._emit(
                    session_id, run_id, "agent.error", {"content": content}
                )

    async def _watch_process(self, session_id: int | None, agent: RunningAgent) -> None:
        timed_out = False
        try:
            try:
                return_code = await asyncio.wait_for(
                    agent.process.wait(), timeout=agent.timeout_seconds
                )
            except TimeoutError:
                timed_out = True
                await self._emit(
                    session_id,
                    agent.run_id,
                    "session.stopping",
                    {"reason": "timeout"},
                )
                self._terminate_process(agent.process)
                try:
                    return_code = await asyncio.wait_for(
                        agent.process.wait(), timeout=5
                    )
                except TimeoutError:
                    self._terminate_process(agent.process, force=True)
                    return_code = await agent.process.wait()
            await asyncio.gather(
                agent.output_task, agent.error_task, return_exceptions=True
            )
            if agent.raw_output_writer:
                try:
                    artifact = agent.raw_output_writer.finish()
                    artifact_record = (
                        await self.artifact_persister(agent.run_id, artifact)
                        if self.artifact_persister
                        else {
                            "artifact_type": artifact.artifact_type,
                            "relative_path": artifact.relative_path,
                            "sha256": artifact.sha256,
                            "byte_size": artifact.byte_size,
                        }
                    )
                    await self._emit(
                        session_id,
                        agent.run_id,
                        "artifact.raw_jsonl",
                        artifact_record,
                    )
                except Exception:
                    logger.exception(
                        "Could not finalize raw output for run %s", agent.run_id
                    )
            if self.diff_finalizer:
                try:
                    diff = await self.diff_finalizer(agent.run_id)
                    if diff:
                        await self._emit(
                            session_id,
                            agent.run_id,
                            "artifact.run_diff",
                            {
                                key: diff[key]
                                for key in (
                                    "run_id",
                                    "status",
                                    "final",
                                    "reason",
                                    "file_count",
                                    "added",
                                    "deleted",
                                )
                            },
                        )
                except Exception:
                    # Diff capture must never turn a completed Codex run into a failure.
                    logger.exception("Could not finalize diff for run %s", agent.run_id)
            cancelled = agent.run_id in self._cancelled
            if cancelled and agent.cancel_ready:
                await agent.cancel_ready.wait()
            if cancelled:
                event_type = "session.cancelled"
            elif timed_out or return_code != 0:
                event_type = "session.failed"
            else:
                event_type = "session.completed"
            payload: dict[str, Any] = {"return_code": return_code}
            if timed_out:
                payload["error"] = (
                    f"Codex exceeded the {agent.timeout_seconds:g}s run timeout"
                )
            await self._emit(session_id, agent.run_id, event_type, payload)
        finally:
            self._cancelled.discard(agent.run_id)
            if self._agents.get(agent.run_id) is agent:
                self._agents.pop(agent.run_id, None)

    async def shutdown(self) -> None:
        agents = tuple(self._agents.items())
        await asyncio.gather(*(self.cancel(run_id) for run_id, _agent in agents))
        watch_tasks = [
            agent.watch_task for _run_id, agent in agents if agent.watch_task
        ]
        if watch_tasks:
            await asyncio.gather(*watch_tasks, return_exceptions=True)
