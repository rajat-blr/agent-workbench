from __future__ import annotations

import json
from typing import Any

MAX_EVENT_PAYLOAD_BYTES = 64 * 1024
MAX_INLINE_STRING_CHARS = 8_000
MAX_INLINE_ITEMS = 100
MAX_INLINE_DEPTH = 8


def _truncate(value: Any, depth: int = 0) -> Any:
    if depth >= MAX_INLINE_DEPTH:
        return {"_truncated": True, "reason": "maximum nesting depth"}
    if isinstance(value, str):
        if len(value) <= MAX_INLINE_STRING_CHARS:
            return value
        return value[:MAX_INLINE_STRING_CHARS] + "\n… [truncated]"
    if isinstance(value, list):
        items = [_truncate(item, depth + 1) for item in value[:MAX_INLINE_ITEMS]]
        if len(value) > MAX_INLINE_ITEMS:
            items.append(
                {"_truncated": True, "omitted_items": len(value) - MAX_INLINE_ITEMS}
            )
        return items
    if isinstance(value, dict):
        items = list(value.items())
        result = {
            str(key): _truncate(item, depth + 1)
            for key, item in items[:MAX_INLINE_ITEMS]
        }
        if len(items) > MAX_INLINE_ITEMS:
            result["_truncated"] = True
            result["_omitted_keys"] = len(items) - MAX_INLINE_ITEMS
        return result
    return value


def event_payload_preview(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, default=str).encode()
    if len(encoded) <= MAX_EVENT_PAYLOAD_BYTES:
        return payload
    preview = _truncate(payload)
    encoded_preview = json.dumps(preview, ensure_ascii=False, default=str).encode()
    if len(encoded_preview) <= MAX_EVENT_PAYLOAD_BYTES:
        if isinstance(preview, dict):
            preview["_payload_truncated"] = True
        return preview
    text_preview = encoded.decode(errors="replace")[: MAX_EVENT_PAYLOAD_BYTES // 2]
    return {
        "_payload_truncated": True,
        "preview": text_preview + "\n… [truncated]",
    }
