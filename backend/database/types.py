from typing import Literal

AgentProvider = Literal["codex"]
SessionStatus = Literal[
    "idle", "running", "stopping", "completed", "failed", "cancelled"
]
RunStatus = Literal["queued", "running", "stopping", "completed", "failed", "cancelled"]
MessageRole = Literal["user", "assistant"]
