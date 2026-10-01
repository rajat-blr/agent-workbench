from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

NORMALIZER_VERSION = 1
MAX_SUMMARY_CHARS = 2_000


def _item_id(event: dict[str, Any]) -> str | None:
    item = event.get("payload", {}).get("item")
    return str(item["id"]) if isinstance(item, dict) and item.get("id") else None


def _bounded(value: Any) -> str:
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, default=str)
    )
    return (
        text
        if len(text) <= MAX_SUMMARY_CHARS
        else text[:MAX_SUMMARY_CHARS] + "… [truncated]"
    )


def _project(item: dict[str, Any]) -> tuple[str, str, str, str]:
    item_type = str(item.get("type", "other"))
    if item_type == "command_execution":
        command = item.get("command") or item.get("argv") or "Command"
        exit_code = item.get("exit_code")
        status = (
            "pass"
            if exit_code == 0
            else "fail"
            if isinstance(exit_code, int)
            else "completed"
        )
        return (
            "command",
            _bounded(command)[:300],
            status,
            _bounded(item.get("output", "")),
        )
    if item_type == "file_change":
        changes = item.get("changes", [])
        paths = [
            str(change.get("path"))
            for change in changes
            if isinstance(change, dict) and change.get("path")
        ]
        return (
            "file_change",
            f"Changed {len(paths)} file{'s' if len(paths) != 1 else ''}",
            "completed",
            ", ".join(paths),
        )
    if item_type == "agent_message":
        text = item.get("text", "Agent message")
        return (
            "agent_message",
            _bounded(text).splitlines()[0][:300],
            "completed",
            _bounded(text),
        )
    if item_type == "plan_update":
        return "plan_update", "Updated plan", "completed", _bounded(item)
    if item_type in {"mcp_tool_call", "tool_call"}:
        name = item.get("tool") or item.get("name") or "Tool call"
        return "tool_call", str(name)[:300], "completed", _bounded(item)
    if item_type == "web_search":
        return (
            "web_search",
            str(item.get("query") or "Web search")[:300],
            "completed",
            _bounded(item),
        )
    if item_type == "reasoning":
        return (
            "reasoning",
            "Reasoning milestone",
            "completed",
            _bounded(item.get("text", "")),
        )
    return (
        "other",
        item_type.replace("_", " ").title()[:300],
        "completed",
        _bounded(item),
    )


def normalize_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(events, key=lambda event: event["id"])
    starts: dict[str, dict[str, Any]] = {}
    steps: list[dict[str, Any]] = []

    def append_step(
        start: dict[str, Any],
        end: dict[str, Any],
        item: dict[str, Any],
        *,
        incomplete: bool = False,
    ) -> None:
        kind, title, status, summary = _project(item)
        start_time = start.get("created_at")
        end_time = end.get("created_at")
        duration_ms = None
        if isinstance(start_time, datetime) and isinstance(end_time, datetime):
            duration_ms = max(0, int((end_time - start_time).total_seconds() * 1000))
        flags = ["incomplete"] if incomplete else []
        signature_source = {"kind": kind, "title": title, "item_type": item.get("type")}
        steps.append(
            {
                "sequence": len(steps) + 1,
                "source_event_start_id": start["id"],
                "source_event_end_id": end["id"],
                "source_item_id": _item_id(end) or _item_id(start),
                "kind": kind,
                "title": title,
                "status": "incomplete" if incomplete else status,
                "duration_ms": duration_ms,
                "signature": hashlib.sha256(
                    json.dumps(signature_source, sort_keys=True).encode()
                ).hexdigest(),
                "flags": flags,
                "summary": summary,
                "normalizer_version": NORMALIZER_VERSION,
            }
        )

    for event in ordered:
        event_type = event["type"]
        item = event.get("payload", {}).get("item")
        item_id = _item_id(event)
        if event_type == "codex.item.started" and isinstance(item, dict) and item_id:
            starts[item_id] = event
        elif event_type == "codex.item.completed" and isinstance(item, dict):
            append_step(starts.pop(item_id, event) if item_id else event, event, item)
        elif event_type in {"agent.error", "session.failed"}:
            content = (
                event.get("payload", {}).get("content")
                or event.get("payload", {}).get("error")
                or "Runtime error"
            )
            append_step(event, event, {"type": "runtime_error", "content": content})
            steps[-1].update(
                kind="runtime_error",
                title="Runtime error",
                status="fail",
                summary=_bounded(content),
            )
    for start in starts.values():
        item = start.get("payload", {}).get("item")
        if isinstance(item, dict):
            append_step(start, start, item, incomplete=True)
    steps.sort(key=lambda step: step["source_event_start_id"])
    for sequence, step in enumerate(steps, 1):
        step["sequence"] = sequence
    return steps
