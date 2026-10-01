from datetime import UTC, datetime, timedelta

from evals.normalizer import NORMALIZER_VERSION, normalize_events


def test_normalizer_pairs_items_and_preserves_incomplete_and_error_events() -> None:
    started = datetime.now(UTC)
    events = [
        {
            "id": 1,
            "type": "codex.item.started",
            "created_at": started,
            "payload": {
                "item": {
                    "id": "cmd-1",
                    "type": "command_execution",
                    "command": "pytest -q",
                }
            },
        },
        {
            "id": 2,
            "type": "codex.item.completed",
            "created_at": started + timedelta(milliseconds=250),
            "payload": {
                "item": {
                    "id": "cmd-1",
                    "type": "command_execution",
                    "command": "pytest -q",
                    "exit_code": 0,
                    "output": "2 passed",
                }
            },
        },
        {
            "id": 3,
            "type": "codex.item.started",
            "created_at": started + timedelta(seconds=1),
            "payload": {
                "item": {
                    "id": "edit-1",
                    "type": "file_change",
                    "changes": [{"path": "app.py"}],
                }
            },
        },
        {
            "id": 4,
            "type": "agent.error",
            "created_at": started + timedelta(seconds=2),
            "payload": {"content": "connection closed"},
        },
    ]

    steps = normalize_events(events)

    assert [step["kind"] for step in steps] == [
        "command",
        "file_change",
        "runtime_error",
    ]
    assert steps[0]["duration_ms"] == 250
    assert steps[0]["status"] == "pass"
    assert steps[1]["flags"] == ["incomplete"]
    assert steps[2]["status"] == "fail"
    assert all(step["normalizer_version"] == NORMALIZER_VERSION for step in steps)
