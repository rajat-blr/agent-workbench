from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .types import AgentProvider, MessageRole, RunStatus, SessionStatus


class DatabaseRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class WorkspaceRecord(DatabaseRecord):
    id: int
    path: str
    name: str
    created_at: datetime


class SessionRecord(DatabaseRecord):
    id: int
    workspace_id: int
    provider: AgentProvider
    status: SessionStatus
    title: str | None
    created_at: datetime
    updated_at: datetime


class RunRecord(DatabaseRecord):
    id: int
    session_id: int
    status: RunStatus
    prompt: str
    pid: int | None
    return_code: int | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class MessageRecord(DatabaseRecord):
    id: int
    run_id: int | None
    role: MessageRole
    content: str
    created_at: datetime


class SessionEventRecord(DatabaseRecord):
    id: int
    run_id: int | None
    sequence: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


class SessionHistoryRecord(BaseModel):
    session: SessionRecord
    conversation: list[MessageRecord]
    events: list[SessionEventRecord]
    last_sequence: int
    has_more: bool


class WorkspaceCreate(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    name: str = Field(min_length=1, max_length=200)


class WorkspaceIdParams(BaseModel):
    workspace_id: int = Field(gt=0)


class WorkspaceRename(WorkspaceIdParams):
    name: str = Field(min_length=1, max_length=200)


class GitCommitParams(WorkspaceIdParams):
    message: str = Field(min_length=1, max_length=500)


class SessionCreate(BaseModel):
    workspace_id: int = Field(gt=0)
    provider: AgentProvider = "codex"


class SessionIdParams(BaseModel):
    session_id: int = Field(gt=0)


class RunDiffParams(SessionIdParams):
    run_id: int = Field(gt=0)


class SessionHistoryParams(SessionIdParams):
    after_sequence: int = Field(default=0, ge=0)
    limit: int = Field(default=500, ge=1, le=2000)


class SessionSend(SessionIdParams):
    content: str = Field(min_length=1, max_length=100_000)
    mode: Literal["chat", "map"] = "chat"


class RpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None = None
    method: str = Field(min_length=1, max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)
