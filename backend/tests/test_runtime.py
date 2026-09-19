import asyncio
import sys
from datetime import UTC, datetime

import pytest
from agent_runtime import AgentRuntimeManager, CodexAgentAdapter
from codebase_map import MAP_CLOSE, MAP_OPEN, extract_codebase_map
from event_broker import AgentEvent, EventBroker


class ScriptAdapter:
    def __init__(self, script: str) -> None:
        self.script = script

    async def start(
        self, workspace_path: str, prompt: str, thread_id: str | None = None
    ):
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            "-c",
            self.script,
            cwd=workspace_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )


def event_persister(events: list[AgentEvent]):
    async def persist(session_id, run_id, event_type, payload, source_event_id):
        event = AgentEvent(
            session_id=session_id,
            run_id=run_id,
            type=event_type,
            payload=payload,
            sequence=len(events) + 1,
            created_at=datetime.now(UTC).isoformat(),
        )
        events.append(event)
        return event

    return persist


@pytest.mark.asyncio
async def test_event_broker_filters_sessions() -> None:
    broker = EventBroker()
    event = AgentEvent(7, 3, "first", {}, 42, datetime.now(UTC).isoformat())
    async with broker.subscribe(7) as session_queue:
        broker.publish(event)
        assert await session_queue.get() == event


def test_codex_adapter_builds_safe_json_commands(tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    adapter = CodexAgentAdapter(model="gpt-test", sandbox="workspace-write")
    workspace = str(tmp_path)
    first = adapter.build_command(workspace, "fix it", None)
    resumed = adapter.build_command(workspace, "continue", "thread-123")

    assert first == [
        "codex",
        "exec",
        "--json",
        "--color",
        "never",
        "--sandbox",
        "workspace-write",
        "--model",
        "gpt-test",
        "--cd",
        workspace,
        "-",
    ]
    assert resumed[-3:] == ["resume", "thread-123", "-"]


def test_codex_adapter_allows_an_explicit_non_git_workspace(tmp_path) -> None:
    adapter = CodexAgentAdapter()
    command = adapter.build_command(str(tmp_path), "hello", None)

    assert "--skip-git-repo-check" in command


@pytest.mark.asyncio
async def test_runtime_streams_codex_json_and_completes(tmp_path) -> None:
    messages = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {
            "type": "item.completed",
            "item": {"id": "item-1", "type": "agent_message", "text": "Done"},
        },
        {"type": "turn.completed", "usage": {"input_tokens": 2, "output_tokens": 1}},
    ]
    script = f"import json; [print(json.dumps(x), flush=True) for x in {messages!r}]"
    persisted: list[AgentEvent] = []
    broker = EventBroker()
    runtime = AgentRuntimeManager(
        broker, ScriptAdapter(script), event_persister(persisted), timeout_seconds=2
    )

    async with broker.subscribe(1) as queue:
        await runtime.start(1, 9, str(tmp_path), "test prompt")
        received = []
        while not received or received[-1].type != "session.completed":
            received.append(await asyncio.wait_for(queue.get(), timeout=2))

    assert [event.type for event in received] == [
        "session.started",
        "assistant.text",
        "session.completed",
    ]
    assert received[1].payload["content"] == "Done"
    assert [event.sequence for event in persisted] == [1, 2, 3, 4, 5]
    await runtime.shutdown()


def test_codebase_map_validates_files_and_relationships(tmp_path) -> None:
    (tmp_path / "main.py").write_text("print('hello')")
    content = (
        "The entry point starts the app.\n"
        f'{MAP_OPEN}{{"nodes":[{{"id":"app","label":"App","summary":"Entry point",'
        '"files":["main.py","../secret.txt"]}],"edges":[]}'
        f"{MAP_CLOSE}"
    )
    visible, map_data = extract_codebase_map(content, str(tmp_path))

    assert visible == "The entry point starts the app."
    assert map_data and map_data["nodes"][0]["files"] == ["main.py"]


@pytest.mark.asyncio
async def test_map_run_streams_saved_artifact_without_json_in_chat(tmp_path) -> None:
    (tmp_path / "main.py").write_text("print('hello')")
    map_content = (
        "Here is the architecture.\n"
        f'{MAP_OPEN}{{"nodes":[{{"id":"app","label":"App","summary":"Entry point",'
        '"files":["main.py"]}],"edges":[]}'
        f"{MAP_CLOSE}"
    )
    message = {
        "type": "item.completed",
        "item": {"id": "map-1", "type": "agent_message", "text": map_content},
    }
    script = f"import json; print(json.dumps({message!r}), flush=True)"
    persisted: list[AgentEvent] = []
    broker = EventBroker()
    runtime = AgentRuntimeManager(
        broker, ScriptAdapter(script), event_persister(persisted), timeout_seconds=2
    )

    await runtime.start(1, 1, str(tmp_path), "Explain this codebase", mode="map")
    while not persisted or persisted[-1].type != "session.completed":
        await asyncio.sleep(0.01)

    assert [event.type for event in persisted] == [
        "session.started",
        "assistant.text",
        "artifact.codebase_map",
        "session.completed",
    ]
    assert persisted[1].payload["content"] == "Here is the architecture."
    assert persisted[2].payload["nodes"][0]["files"] == ["main.py"]
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_runtime_enforces_timeout(tmp_path) -> None:
    persisted: list[AgentEvent] = []
    broker = EventBroker()
    runtime = AgentRuntimeManager(
        broker,
        ScriptAdapter("import time; time.sleep(10)"),
        event_persister(persisted),
        timeout_seconds=0.05,
    )

    await runtime.start(2, 10, str(tmp_path), "wait")
    while not persisted or persisted[-1].type != "session.failed":
        await asyncio.sleep(0.01)

    assert persisted[-1].payload["error"].startswith("Codex exceeded")
    await runtime.shutdown()
