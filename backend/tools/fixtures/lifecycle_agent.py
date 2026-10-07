#!/usr/bin/env python3
"""Synthetic CLI protocol fixture. Never calls a model or reads user data."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def emit(value):
    print(json.dumps(value), flush=True)


if "--version" in sys.argv:
    print("synthetic-lifecycle-fixture 1.0")
    raise SystemExit(0)

prompt = sys.stdin.read()
root = Path.cwd()
emit({"type": "thread.started", "thread_id": "synthetic-lifecycle-thread"})
emit({"type": "turn.started"})
if "LIFECYCLE_BLOCK" in prompt:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    ready = root / ".runtime-ready.json"
    ready.write_text(json.dumps({"parent": os.getpid(), "child": child.pid}))
    deadline = time.monotonic() + 120
    while not (root / ".release").exists():
        if time.monotonic() > deadline:
            raise SystemExit("Synthetic fixture release deadline exceeded")
        time.sleep(0.02)
    child.terminate()
    child.wait(timeout=5)
    (root / ".release").unlink()
    ready.unlink()
(root / "done.txt").write_text("synthetic fixture complete\n")
emit(
    {
        "type": "item.completed",
        "item": {
            "id": "reply",
            "type": "agent_message",
            "text": "Synthetic lifecycle fixture reply; no model was called.",
        },
    }
)
emit(
    {
        "type": "turn.completed",
        "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0},
    }
)
