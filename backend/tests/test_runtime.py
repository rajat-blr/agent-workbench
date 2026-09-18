import asyncio
import shlex
import sys

import pytest

from agent_runtime import AgentRuntimeManager, CommandAgentAdapter, FakeAgentAdapter
from event_broker import EventBroker


@pytest.mark.asyncio
async def test_event_broker_preserves_order_and_filters_sessions() -> None:
    broker = EventBroker()
    async with broker.subscribe(7) as session_queue:
        await broker.publish(7, "first", {})
        await broker.publish(8, "other", {})
        await broker.publish(7, "second", {})
        first = await session_queue.get()
        second = await session_queue.get()

    assert [first.type, second.type] == ["first", "second"]
    assert [first.sequence, second.sequence] == [1, 3]


@pytest.mark.asyncio
async def test_command_agent_runs_in_background_and_streams_output(tmp_path) -> None:
    command = shlex.join([sys.executable, "-u", "-c", "import sys; [print('echo:' + line.strip(), flush=True) for line in sys.stdin]"])
    broker = EventBroker()
    runtime = AgentRuntimeManager(broker, CommandAgentAdapter(command))

    async with broker.subscribe(1) as queue:
        await runtime.start(1, str(tmp_path))
        await runtime.send(1, "hello")
        events = [await asyncio.wait_for(queue.get(), timeout=2) for _ in range(3)]

    assert events[0].type == "session.started"
    assert events[1].type == "message.sent"
    assert events[2].type == "command.output"
    assert events[2].payload["content"] == "echo:hello"
    await runtime.stop(1)
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_fake_agent_returns_a_subscription_free_response(tmp_path) -> None:
    broker = EventBroker()
    runtime = AgentRuntimeManager(broker, FakeAgentAdapter())

    async with broker.subscribe(2) as queue:
        await runtime.start(2, str(tmp_path))
        await runtime.send(2, "test prompt")
        events = [await asyncio.wait_for(queue.get(), timeout=2) for _ in range(5)]

    assert [event.type for event in events[:2]] == ["session.started", "message.sent"]
    assert [event.type for event in events[2:]] == ["assistant.text", "assistant.text", "assistant.text"]
    assert [event.payload["content"] for event in events[2:]] == [
        "I received: test prompt",
        "This is a local test-agent response; no provider subscription is required.",
        "The backend streamed this response from a background process.",
    ]
    await runtime.stop(2)
    await runtime.shutdown()
