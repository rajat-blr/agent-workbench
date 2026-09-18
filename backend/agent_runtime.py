import asyncio
import json
import shlex
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from event_broker import AgentEvent, EventBroker

EventHandler = Callable[[AgentEvent], Awaitable[None]]


class AgentAdapter(Protocol):
    async def start(self, workspace_path: str) -> asyncio.subprocess.Process: ...


class CommandAgentAdapter:
    def __init__(self, command: str) -> None:
        self.command = command

    async def start(self, workspace_path: str) -> asyncio.subprocess.Process:
        command = shlex.split(self.command)
        if not command:
            raise ValueError("AGENT_COMMAND cannot be empty")
        return await asyncio.create_subprocess_exec(
            *command,
            cwd=workspace_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )


class FakeAgentAdapter:
    async def start(self, workspace_path: str) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            str(Path(__file__).with_name("fake_agent.py")),
            cwd=workspace_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )


@dataclass
class RunningAgent:
    process: asyncio.subprocess.Process
    workspace_path: str
    output_task: asyncio.Task[None]
    error_task: asyncio.Task[None]


class AgentRuntimeManager:
    def __init__(self, broker: EventBroker, adapter: AgentAdapter, on_event: EventHandler | None = None) -> None:
        self.broker = broker
        self.adapter = adapter
        self.on_event = on_event
        self._agents: dict[int, RunningAgent] = {}
        self._cancelled: set[int] = set()
        self._lock = asyncio.Lock()

    async def _emit(self, session_id: int, event_type: str, payload: dict) -> AgentEvent:
        event = await self.broker.publish(session_id, event_type, payload)
        if self.on_event:
            await self.on_event(event)
        return event

    async def start(self, session_id: int, workspace_path: str) -> None:
        async with self._lock:
            if session_id in self._agents:
                return
            if not Path(workspace_path).is_dir():
                raise ValueError("Workspace path must be an existing directory")
            process = await self.adapter.start(workspace_path)
            output_task = asyncio.create_task(self._read_stream(session_id, process.stdout, "agent.stdout"))
            error_task = asyncio.create_task(self._read_stream(session_id, process.stderr, "agent.stderr"))
            self._agents[session_id] = RunningAgent(process, workspace_path, output_task, error_task)
            asyncio.create_task(self._watch_process(session_id, process))
            await self._emit(session_id, "session.started", {"pid": process.pid, "workspace_path": workspace_path})

    async def send(self, session_id: int, content: str) -> None:
        agent = self._agents.get(session_id)
        if not agent:
            raise KeyError(f"No running agent for session {session_id}")
        if not agent.process.stdin:
            raise RuntimeError("Agent stdin is unavailable")
        agent.process.stdin.write((content.rstrip("\n") + "\n").encode())
        await agent.process.stdin.drain()
        await self._emit(session_id, "message.sent", {"content": content})

    async def stop(self, session_id: int) -> None:
        agent = self._agents.get(session_id)
        if not agent:
            return
        if agent.process.returncode is None:
            self._cancelled.add(session_id)
            agent.process.terminate()
            await self._emit(session_id, "session.stopping", {})

    async def cancel(self, session_id: int) -> None:
        await self.stop(session_id)

    async def _read_stream(self, session_id: int, stream: asyncio.StreamReader | None, event_type: str) -> None:
        if not stream:
            return
        while line := await stream.readline():
            text = line.decode(errors="replace").rstrip("\r\n")
            if event_type == "agent.stdout":
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    await self._emit(session_id, "command.output", {"content": text})
                else:
                    if isinstance(message, dict) and isinstance(message.get("type"), str):
                        payload = {key: value for key, value in message.items() if key != "type"}
                        await self._emit(session_id, message["type"], payload)
                    else:
                        await self._emit(session_id, "command.output", {"content": text})
            else:
                await self._emit(session_id, "agent.error", {"content": text})

    async def _watch_process(self, session_id: int, process: asyncio.subprocess.Process) -> None:
        return_code = await process.wait()
        agent = self._agents.pop(session_id, None)
        if agent:
            await asyncio.gather(agent.output_task, agent.error_task)
        cancelled = session_id in self._cancelled
        self._cancelled.discard(session_id)
        event_type = "session.cancelled" if cancelled else "session.completed" if return_code == 0 else "session.failed"
        await self._emit(session_id, event_type, {"return_code": return_code})

    async def shutdown(self) -> None:
        await asyncio.gather(*(self.stop(session_id) for session_id in tuple(self._agents)))