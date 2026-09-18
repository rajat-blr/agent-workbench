from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    name: str = Field(min_length=1, max_length=200)


class SessionCreate(BaseModel):
    workspace_id: int = Field(gt=0)
    provider: Literal["codex"] = "codex"


class SessionIdParams(BaseModel):
    session_id: int = Field(gt=0)


class SessionHistoryParams(SessionIdParams):
    after_sequence: int = Field(default=0, ge=0)
    limit: int = Field(default=500, ge=1, le=2000)


class SessionSend(SessionIdParams):
    content: str = Field(min_length=1, max_length=100_000)


class RpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None = None
    method: str = Field(min_length=1, max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)
