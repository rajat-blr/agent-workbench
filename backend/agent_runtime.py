import asyncio
import json
import os
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from event_broker import AgentEvent, EventBroker

EventPersister = Callable[
    [int, int, str, dict[str, Any], str | None], Awaitable[AgentEvent]
]


class AgentAdapter(Protocol):
    async def start(
        self, workspace_path: str, prompt: str, thread_id: str | None = None
    ) -> asyncio.subprocess.Process: ...


class CodexAgentAdapter:
    def __init__(
        self,
        command: str = "codex",
        model: str | None = None,
        sandbox: str = "workspace-write",
        skip_git_repo_check: bool = False,
    ) -> None:
        if sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("Codex sandbox must be read-only or workspace-write")
        self.command = command
        self.model = model
        self.sandbox = sandbox
        self.skip_git_repo_check = skip_git_repo_check

    def build_command(
        self, workspace_path: str, prompt: str, thread_id: str | None
    ) -> list[str]:
        command = [
            self.command,
            "exec",
            "--json",
            "--color",
            "never",
            "--sandbox",
            self.sandbox,
        ]
        if self.model:
            command.extend(["--model", self.model])
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

    async def start(
        self, workspace_path: str, prompt: str, thread_id: str | None = None
    ) -> asyncio.subprocess.Process:
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
        process_options: dict[str, Any] = {}
        if os.name != "nt":
            process_options["start_new_session"] = True
        process = await asyncio.create_subprocess_exec(
            *self.build_command(workspace_path, prompt, thread_id),
            cwd=workspace_path,
            env=safe_environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1024 * 1024,
            **process_options,
        )
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
    process: asyncio.subprocess.Process
    output_task: asyncio.Task[None]
    error_task: asyncio.Task[None]
    watch_task: asyncio.Task[None] | None = None
    cancel_ready: asyncio.Event | None = None


class AgentRuntimeManager:
    def __init__(
        self,
        broker: EventBroker,
        adapter: AgentAdapter,
        persist_event: EventPersister,
        timeout_seconds: int = 3600,
    ) -> None:
        self.broker = broker
        self.adapter = adapter
        self.persist_event = persist_event
        self.timeout_seconds = timeout_seconds
        self._agents: dict[int, RunningAgent] = {}
        self._cancelled: set[int] = set()
        self._lock = asyncio.Lock()

    async def _emit(
        self,
        session_id: int,
        run_id: int,
        event_type: str,
        payload: dict[str, Any],
        source_event_id: str | None = None,
    ) -> AgentEvent:
        event = await self.persist_event(
            session_id, run_id, event_type, payload, source_event_id
        )
        self.broker.publish(event)
        return event

    async def start(
        self,
        session_id: int,
        run_id: int,
        workspace_path: str,
        prompt: str,
        thread_id: str | None = None,
    ) -> None:
        async with self._lock:
            existing = self._agents.get(session_id)
            if existing and existing.process.returncode is None:
                raise RuntimeError("A run is already active for this session")
            if not Path(workspace_path).is_dir():
                raise ValueError("Workspace path must be an existing directory")
            process = await self.adapter.start(workspace_path, prompt, thread_id)
            output_task = asyncio.create_task(
                self._read_stdout(session_id, run_id, process.stdout)
            )
            error_task = asyncio.create_task(
                self._read_stderr(session_id, run_id, process.stderr)
            )
            agent = RunningAgent(run_id, process, output_task, error_task)
            self._agents[session_id] = agent
            try:
                await self._emit(
                    session_id,
                    run_id,
                    "session.started",
                    {"pid": process.pid, "workspace_path": workspace_path},
                )
            except Exception:
                self._terminate_process(process)
                self._agents.pop(session_id, None)
                raise
            agent.watch_task = asyncio.create_task(
                self._watch_process(session_id, agent)
            )

    async def cancel(self, session_id: int) -> bool:
        agent = self._agents.get(session_id)
        if not agent or agent.process.returncode is not None:
            return False
        agent.cancel_ready = asyncio.Event()
        self._cancelled.add(session_id)
        try:
            await self._emit(
                session_id, agent.run_id, "session.stopping", {"reason": "cancelled"}
            )
        finally:
            self._terminate_process(agent.process)
            agent.cancel_ready.set()
        return True

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
        self, session_id: int, run_id: int, stream: asyncio.StreamReader | None
    ) -> None:
        if not stream:
            return
        while line := await stream.readline():
            text = line.decode(errors="replace").rstrip("\r\n")
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
                await self._emit(
                    session_id,
                    run_id,
                    "assistant.text",
                    {"content": item["text"], "item": item},
                    source_event_id,
                )
            else:
                payload = {
                    key: value for key, value in message.items() if key != "type"
                }
                await self._emit(
                    session_id, run_id, f"codex.{raw_type}", payload, source_event_id
                )

    async def _read_stderr(
        self, session_id: int, run_id: int, stream: asyncio.StreamReader | None
    ) -> None:
        if not stream:
            return
        while line := await stream.readline():
            content = line.decode(errors="replace").rstrip("\r\n")
            if content:
                await self._emit(
                    session_id, run_id, "agent.error", {"content": content}
                )

    async def _watch_process(self, session_id: int, agent: RunningAgent) -> None:
        timed_out = False
        try:
            try:
                return_code = await asyncio.wait_for(
                    agent.process.wait(), timeout=self.timeout_seconds
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
            cancelled = session_id in self._cancelled
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
                    f"Codex exceeded the {self.timeout_seconds}s run timeout"
                )
            await self._emit(session_id, agent.run_id, event_type, payload)
        finally:
            self._cancelled.discard(session_id)
            if self._agents.get(session_id) is agent:
                self._agents.pop(session_id, None)

    async def shutdown(self) -> None:
        agents = tuple(self._agents.items())
        await asyncio.gather(
            *(self.cancel(session_id) for session_id, _agent in agents)
        )
        watch_tasks = [
            agent.watch_task for _session_id, agent in agents if agent.watch_task
        ]
        if watch_tasks:
            await asyncio.gather(*watch_tasks, return_exceptions=True)
