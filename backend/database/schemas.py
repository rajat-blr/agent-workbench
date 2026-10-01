from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .types import AgentProvider, MessageRole, RunKind, RunStatus, SessionStatus


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
    kind: RunKind
    session_id: int | None
    eval_attempt_id: int | None
    workspace_path: str
    status: RunStatus
    prompt: str
    pid: int | None
    return_code: int | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class RunArtifactRecord(DatabaseRecord):
    id: int
    run_id: int | None
    artifact_type: str
    relative_path: str
    sha256: str
    byte_size: int
    metadata_json: dict[str, Any]
    created_at: datetime


class MessageRecord(DatabaseRecord):
    id: int
    run_id: int | None
    role: MessageRole
    content: str
    created_at: datetime


class RunEventRecord(DatabaseRecord):
    id: int
    run_id: int | None
    sequence: int
    type: str
    payload: dict[str, Any]
    created_at: datetime


class SessionHistoryRecord(BaseModel):
    session: SessionRecord
    conversation: list[MessageRecord]
    events: list[RunEventRecord]
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


class RunIdParams(BaseModel):
    run_id: int = Field(gt=0)


class RunEventsParams(RunIdParams):
    after_sequence: int = Field(default=0, ge=0)
    limit: int = Field(default=500, ge=1, le=2000)


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


class EvalCaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    workspace_id: int = Field(gt=0)
    prompt: str = Field(min_length=1, max_length=100_000)
    base_sha: str | None = Field(default=None, min_length=40, max_length=64)


class EvalCaseCreateFromRun(BaseModel):
    run_id: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)


class EvalCaseUpdateDraft(BaseModel):
    case_id: int = Field(gt=0)
    revision_id: int = Field(gt=0)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    prompt: str | None = Field(default=None, min_length=1, max_length=100_000)
    base_sha: str | None = Field(default=None, min_length=40, max_length=64)
    setup_spec: list[dict[str, Any]] | None = None
    scorer_spec: list[dict[str, Any]] | None = None
    path_policy: dict[str, Any] | None = None


class EvalCaseIdParams(BaseModel):
    case_id: int = Field(gt=0)


class EvalCaseRevisionParams(EvalCaseIdParams):
    revision_id: int = Field(gt=0)


class EvalSuiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)


class EvalSuiteUpdateDraft(BaseModel):
    suite_id: int = Field(gt=0)
    version_id: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    case_revision_ids: list[int] | None = None


class EvalSuiteVersionParams(BaseModel):
    suite_id: int = Field(gt=0)
    version_id: int = Field(gt=0)


class EvalSuiteIdParams(BaseModel):
    suite_id: int = Field(gt=0)


class EvalConfigCapture(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    model: str | None = Field(default=None, max_length=100)
    reasoning_effort: str | None = Field(default=None, max_length=32)
    instructions: list[dict[str, Any]] = Field(default_factory=list)
    codex_config: dict[str, Any] = Field(default_factory=dict)
    sandbox_policy: dict[str, Any] = Field(default_factory=dict)
    cli_version: str | None = Field(default=None, max_length=100)
    uncontrolled_inputs: list[dict[str, Any]] = Field(default_factory=list)


class EvalConfigIdParams(BaseModel):
    config_id: int = Field(gt=0)


class EvalConfigDiffParams(BaseModel):
    left_snapshot_id: int = Field(gt=0)
    right_snapshot_id: int = Field(gt=0)


class EvalExperimentPlan(BaseModel):
    name: str = Field(default="", max_length=200)
    suite_version_id: int = Field(gt=0)
    config_snapshot_ids: list[int] = Field(min_length=1, max_length=2)
    samples_per_case: int = Field(default=1, ge=1, le=10)
    concurrency: int = Field(default=1, ge=1, le=4)
    timeout_seconds: int = Field(default=1800, ge=30, le=7200)


class EvalExperimentIdParams(BaseModel):
    experiment_id: int = Field(gt=0)


class EvalAttemptIdParams(BaseModel):
    attempt_id: int = Field(gt=0)
