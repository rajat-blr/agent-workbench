import json
import sys
import time


def respond(prompt: str) -> list[dict[str, str]]:
    return [
        {"type": "assistant.text", "content": f"I received: {prompt}"},
        {"type": "assistant.text", "content": "This is a local test-agent response; no provider subscription is required."},
        {"type": "assistant.text", "content": "The backend streamed this response from a background process."},
    ]


for line in sys.stdin:
    prompt = line.strip()
    if not prompt:
        continue
    for response_line in respond(prompt):
        print(json.dumps(response_line), flush=True)
        time.sleep(0.08)