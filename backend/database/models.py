from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .types import AgentProvider, MessageRole, RunKind, RunStatus, SessionStatus


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sessions: Mapped[list[Session]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    eval_case_revisions: Mapped[list[EvalCaseRevision]] = relationship(
        back_populates="workspace"
    )


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('idle', 'running', 'stopping', 'completed', 'failed', 'cancelled')",
            name="session_status_valid",
        ),
        CheckConstraint("provider = 'codex'", name="session_provider_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[AgentProvider] = mapped_column(String(32), default="codex")
    status: Mapped[SessionStatus] = mapped_column(
        String(32), default="idle", index=True
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    codex_thread_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )

    workspace: Mapped[Workspace] = relationship(back_populates="sessions")
    messages: Mapped[list[Message]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    runs: Mapped[list[Run]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    events: Mapped[list[RunEvent]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'stopping', 'completed', 'failed', 'cancelled')",
            name="run_status_valid",
        ),
        CheckConstraint("kind IN ('chat', 'eval')", name="run_kind_valid"),
        CheckConstraint(
            "(kind = 'chat' AND session_id IS NOT NULL AND eval_attempt_id IS NULL) "
            "OR (kind = 'eval' AND session_id IS NULL AND eval_attempt_id IS NOT NULL)",
            name="run_origin_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[RunKind] = mapped_column(String(16), default="chat")
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    eval_attempt_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, unique=True
    )
    workspace_path: Mapped[str] = mapped_column(String, default="")
    status: Mapped[RunStatus] = mapped_column(String(32), default="queued", index=True)
    prompt: Mapped[str] = mapped_column(Text)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    return_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    session: Mapped[Session | None] = relationship(back_populates="runs")
    messages: Mapped[list[Message]] = relationship(back_populates="run")
    events: Mapped[list[RunEvent]] = relationship(back_populates="run")
    artifacts: Mapped[list[RunArtifact]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    diff: Mapped[RunDiff | None] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )


class RunDiff(Base):
    __tablename__ = "run_diffs"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_path: Mapped[str] = mapped_column(String)
    repo_path: Mapped[str] = mapped_column(String)
    baseline: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="capturing")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    final: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    run: Mapped[Run] = relationship(back_populates="diff")


class RunArtifact(Base):
    __tablename__ = "run_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(64), index=True)
    relative_path: Mapped[str] = mapped_column(String, unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped[Run | None] = relationship(back_populates="artifacts")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="message_role_valid"),
        Index("ix_messages_session_id_id", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[MessageRole] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[Session] = relationship(back_populates="messages")
    run: Mapped[Run | None] = relationship(back_populates="messages")


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        CheckConstraint(
            "run_id IS NOT NULL OR session_id IS NOT NULL",
            name="run_event_origin_valid",
        ),
        Index("ix_run_events_run_id_id", "run_id", "id"),
        Index("ix_run_events_session_id_id", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[Session | None] = relationship(back_populates="events")
    run: Mapped[Run | None] = relationship(back_populates="events")


class EvalCase(Base):
    __tablename__ = "eval_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )

    revisions: Mapped[list[EvalCaseRevision]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class EvalCaseRevision(Base):
    __tablename__ = "eval_case_revisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published')",
            name="eval_case_revision_status_valid",
        ),
        CheckConstraint(
            "validation_status IN ('not_validated', 'valid', 'invalid')",
            name="eval_case_validation_status_valid",
        ),
        CheckConstraint(
            "status = 'draft' OR (content_hash IS NOT NULL AND base_sha IS NOT NULL "
            "AND published_at IS NOT NULL AND validation_status = 'valid')",
            name="eval_case_published_fields_valid",
        ),
        Index("uq_eval_case_revision", "case_id", "revision", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("eval_cases.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True
    )
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    base_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt: Mapped[str] = mapped_column(Text)
    setup_spec_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    scorer_spec_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    path_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    starting_patch_artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("run_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    verifier_artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("run_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    validation_status: Mapped[str] = mapped_column(String(24), default="not_validated")
    validation_details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    case: Mapped[EvalCase] = relationship(back_populates="revisions")
    workspace: Mapped[Workspace] = relationship(back_populates="eval_case_revisions")


class EvalSuite(Base):
    __tablename__ = "eval_suites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )
    versions: Mapped[list[EvalSuiteVersion]] = relationship(
        back_populates="suite", cascade="all, delete-orphan"
    )


class EvalSuiteVersion(Base):
    __tablename__ = "eval_suite_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'frozen')", name="eval_suite_version_status_valid"
        ),
        CheckConstraint(
            "status = 'draft' OR (content_hash IS NOT NULL AND frozen_at IS NOT NULL)",
            name="eval_suite_frozen_fields_valid",
        ),
        Index("uq_eval_suite_version", "suite_id", "version", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    suite_id: Mapped[int] = mapped_column(
        ForeignKey("eval_suites.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    frozen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    suite: Mapped[EvalSuite] = relationship(back_populates="versions")
    cases: Mapped[list[EvalSuiteVersionCase]] = relationship(
        back_populates="suite_version",
        cascade="all, delete-orphan",
        order_by="EvalSuiteVersionCase.ordinal",
    )


class EvalSuiteVersionCase(Base):
    __tablename__ = "eval_suite_version_cases"
    __table_args__ = (
        Index(
            "uq_eval_suite_version_ordinal", "suite_version_id", "ordinal", unique=True
        ),
    )

    suite_version_id: Mapped[int] = mapped_column(
        ForeignKey("eval_suite_versions.id", ondelete="CASCADE"), primary_key=True
    )
    case_revision_id: Mapped[int] = mapped_column(
        ForeignKey("eval_case_revisions.id", ondelete="RESTRICT"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    suite_version: Mapped[EvalSuiteVersion] = relationship(back_populates="cases")
    case_revision: Mapped[EvalCaseRevision] = relationship()


class EvalConfig(Base):
    __tablename__ = "eval_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    snapshots: Mapped[list[EvalConfigSnapshot]] = relationship(
        back_populates="config", cascade="all, delete-orphan"
    )


class EvalConfigSnapshot(Base):
    __tablename__ = "eval_config_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    config_id: Mapped[int] = mapped_column(
        ForeignKey("eval_configs.id", ondelete="CASCADE"), index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(32), nullable=True)
    instructions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    codex_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sandbox_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cli_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    uncontrolled_inputs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    config: Mapped[EvalConfig] = relationship(back_populates="snapshots")


class EvalExperiment(Base):
    __tablename__ = "eval_experiments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'running', 'completed', 'cancelled', 'failed')",
            name="eval_experiment_status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    suite_version_id: Mapped[int] = mapped_column(
        ForeignKey("eval_suite_versions.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="ready", index=True)
    samples_per_case: Mapped[int] = mapped_column(Integer, default=1)
    concurrency: Mapped[int] = mapped_column(Integer, default=1)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=1800)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    configs: Mapped[list[EvalExperimentConfig]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="EvalExperimentConfig.ordinal",
    )
    attempts: Mapped[list[EvalAttempt]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class EvalExperimentConfig(Base):
    __tablename__ = "eval_experiment_configs"
    __table_args__ = (
        Index(
            "uq_eval_experiment_config_ordinal", "experiment_id", "ordinal", unique=True
        ),
    )
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("eval_experiments.id", ondelete="CASCADE"), primary_key=True
    )
    config_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("eval_config_snapshots.id", ondelete="RESTRICT"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    experiment: Mapped[EvalExperiment] = relationship(back_populates="configs")
    config_snapshot: Mapped[EvalConfigSnapshot] = relationship()


class EvalAttempt(Base):
    __tablename__ = "eval_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'cancelled', 'interrupted')",
            name="eval_attempt_status_valid",
        ),
        Index(
            "uq_eval_attempt_identity",
            "experiment_id",
            "case_revision_id",
            "config_snapshot_id",
            "sample_index",
            "retry_index",
            unique=True,
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("eval_experiments.id", ondelete="CASCADE"), index=True
    )
    case_revision_id: Mapped[int] = mapped_column(
        ForeignKey("eval_case_revisions.id", ondelete="RESTRICT"), index=True
    )
    config_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("eval_config_snapshots.id", ondelete="RESTRICT"), index=True
    )
    sample_index: Mapped[int] = mapped_column(Integer)
    retry_index: Mapped[int] = mapped_column(Integer, default=0)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    worktree_path: Mapped[str | None] = mapped_column(String, nullable=True)
    setup_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scoring_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    experiment: Mapped[EvalExperiment] = relationship(back_populates="attempts")
    case_revision: Mapped[EvalCaseRevision] = relationship()
    config_snapshot: Mapped[EvalConfigSnapshot] = relationship()
    scores: Mapped[list[EvalScore]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )


class EvalScore(Base):
    __tablename__ = "eval_scores"
    __table_args__ = (
        Index("uq_eval_score_key", "attempt_id", "scorer_key", unique=True),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("eval_attempts.id", ondelete="CASCADE"), index=True
    )
    scorer_key: Mapped[str] = mapped_column(String(100))
    required: Mapped[bool] = mapped_column(default=True)
    passed: Mapped[bool | None] = mapped_column(nullable=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("run_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    attempt: Mapped[EvalAttempt] = relationship(back_populates="scores")


class EvalStep(Base):
    __tablename__ = "eval_steps"
    __table_args__ = (
        Index("uq_eval_step_sequence", "run_id", "sequence", unique=True),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    source_event_start_id: Mapped[int] = mapped_column(
        ForeignKey("run_events.id", ondelete="CASCADE")
    )
    source_event_end_id: Mapped[int] = mapped_column(
        ForeignKey("run_events.id", ondelete="CASCADE")
    )
    source_item_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(24))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signature: Mapped[str] = mapped_column(String(64))
    flags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    normalizer_version: Mapped[int] = mapped_column(Integer, default=1)
