from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ItemCreate(BaseModel):
    title: str
    description: str | None = None


class ItemResponse(ItemCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_completed: bool


class WorkspaceCreate(BaseModel):
    path: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)


class SessionCreate(BaseModel):
    workspace_id: int
    provider: str = Field(default="command", min_length=1, max_length=100)


class SessionSend(BaseModel):
    session_id: int
    content: str = Field(min_length=1)


class RpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
