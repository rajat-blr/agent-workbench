import json

from event_payloads import MAX_EVENT_PAYLOAD_BYTES, event_payload_preview


def test_small_event_payload_is_unchanged() -> None:
    payload = {"item": {"type": "command_execution", "output": "ok"}}

    assert event_payload_preview(payload) is payload


def test_large_event_payload_keeps_a_bounded_preview() -> None:
    payload = {
        "item": {
            "type": "command_execution",
            "command": "pytest",
            "output": "x" * (MAX_EVENT_PAYLOAD_BYTES * 2),
        }
    }

    preview = event_payload_preview(payload)

    assert preview["item"]["type"] == "command_execution"
    assert preview["item"]["command"] == "pytest"
    assert preview["item"]["output"].endswith("… [truncated]")
    assert preview["_payload_truncated"] is True
    assert len(json.dumps(preview).encode()) <= MAX_EVENT_PAYLOAD_BYTES
