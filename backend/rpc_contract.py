"""Public RPC wire contract; imports schemas, not the server or agent runtime."""

from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field, TypeAdapter

from database import schemas as s

Json = dict[str, Any]


class EmptyParams(BaseModel):
    pass


class CatalogListParams(BaseModel):
    limit: int = Field(default=500, ge=1, le=500)
    # None preserves legacy display ordering; 0 starts a stable ID-descending scan.
    before_id: int | None = Field(default=None, ge=0)


class SessionListParams(CatalogListParams):
    workspace_id: int | None = Field(default=None, gt=0)


class GitFile(TypedDict):
    path: str
    original_path: str | None
    status: str
    staged: bool
    unstaged: bool


class GitStatus(TypedDict):
    is_repository: bool
    is_root: bool
    branch: str | None
    detached: bool
    dirty_count: int
    staged_count: int
    unstaged_count: int
    files: list[GitFile]
    remotes: list[str]
    index_token: str | None


class RunDiffFile(TypedDict):
    path: str
    status: Literal["added", "modified", "deleted"]
    added: int
    deleted: int
    patch: str
    note: str | None
    final_hash: str | None


class RunDiff(TypedDict):
    run_id: int
    status: Literal["capturing", "ready", "unavailable"]
    final: bool
    reason: str | None
    files: list[RunDiffFile]
    file_count: int
    added: int
    deleted: int
    captured_at: str | None
    stale: NotRequired[bool | None]
    decision: NotRequired[Literal["accepted", "reverted"] | None]
    can_revert: NotRequired[bool]


class EvalCaseRevision(TypedDict):
    id: int
    case_id: int
    revision: int
    status: Literal["draft", "published"]
    content_hash: str | None
    workspace_id: int
    source_run_id: int | None
    starting_patch_artifact_id: int | None
    verifier_artifact_id: int | None
    base_sha: str | None
    prompt: str
    setup_spec: list[Json]
    scorer_spec: list[Json]
    path_policy: Json
    validation_status: Literal["not_validated", "valid", "invalid"]
    validation_details: Json
    published_at: str | None
    created_at: str


class EvalCase(TypedDict):
    id: int
    title: str
    description: str
    created_at: str
    updated_at: str
    latest_revision: EvalCaseRevision | None


class SuiteMember(TypedDict):
    case_id: int
    title: str
    revision_id: int
    revision: int
    ordinal: int


class SuiteVersion(TypedDict):
    id: int
    version: int
    status: Literal["draft", "frozen"]
    content_hash: str | None
    frozen_at: str | None
    cases: list[SuiteMember]


class EvalSuite(TypedDict):
    id: int
    name: str
    description: str
    created_at: str
    updated_at: str
    latest_version: SuiteVersion


class ConfigSnapshot(TypedDict):
    id: int
    content_hash: str
    model: str | None
    reasoning_effort: str | None
    instructions: list[Json]
    codex_config: Json
    sandbox_policy: Json
    cli_version: str | None
    uncontrolled_inputs: list[Json]
    reproducibility_warnings: list[str]
    created_at: str


class EvalConfig(TypedDict):
    id: int
    name: str
    description: str
    created_at: str
    snapshot: ConfigSnapshot


class EvalAttemptSummary(TypedDict):
    id: int
    case_revision_id: int
    case_title: str | None
    config_snapshot_id: int
    sample_index: int
    retry_index: int
    run_id: int | None
    status: str
    outcome: str | None
    failure_category: str | None
    setup_duration_ms: int | None
    agent_duration_ms: int | None
    scoring_duration_ms: int | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    reasoning_output_tokens: int | None


class DurationStats(TypedDict):
    median: float | None
    min: float | None
    max: float | None
    observed: int


class TokenStats(TypedDict):
    total: int | None
    observed: int


class CasePassRate(TypedDict):
    case_revision_id: int
    passed: int
    failed: int
    evaluable: int
    excluded: int
    pass_rate: float | None


class CaseComparison(TypedDict):
    case_revision_id: int
    paired_samples: int
    a_pass_rate: float
    b_pass_rate: float
    difference: float


class ConfigResults(TypedDict):
    config_snapshot_id: int
    passed: int
    failed: int
    infrastructure_errors: int
    evaluable: int
    pass_rate: float | None
    attempt_pass_rate: float | None
    case_count: int
    case_pass_rates: list[CasePassRate]
    confidence_method: str
    confidence_low: float | None
    confidence_high: float | None
    pending: int
    outcome_counts: dict[str, int]
    durations_ms: dict[str, DurationStats]
    tokens: dict[str, TokenStats]


class PairedResults(TypedDict):
    a_only_pass: int
    b_only_pass: int
    both_pass: int
    both_fail: int
    sample_count: int
    discordant: int
    p_value: float | None
    inference_available: bool
    method: str
    case_count: int
    improved_cases: int
    regressed_cases: int
    mean_difference: float | None
    confidence_low: float | None
    confidence_high: float | None
    case_comparisons: list[CaseComparison]


class Comparison(TypedDict):
    case_revision_id: int
    sample_index: int
    category: str
    attempt_ids: list[int]


class EvalResults(TypedDict):
    configurations: list[ConfigResults]
    paired: PairedResults
    comparisons: list[Comparison]
    verdict: Literal["inconclusive", "configuration_a_better", "configuration_b_better"]
    verdict_summary: str
    is_final: bool
    analysis_unit: Literal["case_revision"]
    warnings: list[str]


class ConfigLabel(TypedDict):
    snapshot_id: int
    name: str


class EvalExperiment(TypedDict):
    id: int
    name: str
    suite_version_id: int
    status: Literal["ready", "running", "completed", "cancelled", "failed"]
    samples_per_case: int
    concurrency: int
    timeout_seconds: int
    config_snapshot_ids: list[int]
    configurations: list[ConfigLabel]
    attempt_count: int
    attempt_status_counts: dict[str, int]
    attempts: list[EvalAttemptSummary]
    results: EvalResults
    created_at: str
    started_at: str | None
    completed_at: str | None


class EvalStep(TypedDict):
    sequence: int
    source_event_start_id: int
    source_event_end_id: int
    source_item_id: str | None
    kind: str
    title: str
    status: str
    duration_ms: int | None
    signature: str
    flags: list[str]
    summary: str
    normalizer_version: int


class EvalAttemptEvent(TypedDict):
    id: int
    type: str
    payload: Json
    created_at: str


class EvalScorerOutput(TypedDict):
    artifact_id: int
    attempt_id: int
    scorer_key: str | None
    stdout: str
    stderr: str
    offset: int
    next_offset: int
    has_more: bool
    total_length: int


class CaseLabel(TypedDict):
    id: int
    title: str


class AttemptConfig(TypedDict):
    snapshot_id: int
    name: str
    model: str | None
    reasoning_effort: str | None


class AttemptDurations(TypedDict):
    setup: int | None
    agent: int | None
    scoring: int | None


class AttemptTokens(TypedDict):
    input: int | None
    cached_input: int | None
    output: int | None
    reasoning_output: int | None


class AttemptScore(TypedDict):
    key: str
    required: bool
    passed: bool | None
    value: Json
    summary: str
    evidence: Json
    artifact_id: int | None


class AttemptArtifact(TypedDict):
    id: int
    type: str
    sha256: str
    byte_size: int
    metadata: Json


class EvalAttemptDetail(TypedDict):
    id: int
    experiment_id: int
    case: CaseLabel | None
    case_revision_id: int
    configuration: AttemptConfig | None
    sample_index: int
    retry_index: int
    run_id: int | None
    status: str
    outcome: str | None
    failure_category: str | None
    durations_ms: AttemptDurations
    tokens: AttemptTokens
    scores: list[AttemptScore]
    diff: RunDiff | None
    artifacts: list[AttemptArtifact]


class EvalPreflight(TypedDict):
    case_count: int
    config_count: int
    samples_per_case: int
    attempt_count: int
    repositories: list[str]
    invalid_case_revision_ids: list[int]
    configuration_differences: list[str]
    warnings: list[str]
    isolation: str
    network_enabled: bool


class EvalExperimentEvent(TypedDict):
    experiment_id: int
    type: str
    payload: Json
    sequence: int
    created_at: str


class ConfigDifference(TypedDict):
    field: str
    left: Any
    right: Any


class ConfigDiff(TypedDict):
    differences: list[ConfigDifference]


class GitActionResult(TypedDict):
    action: str
    output: str
    status: GitStatus


class HealthResult(TypedDict):
    status: Literal["ok"]


class WorkspaceDeleted(TypedDict):
    deleted: bool
    workspace_id: int


class SessionDeleted(TypedDict):
    deleted: bool
    session_id: int


class SessionAccepted(TypedDict):
    accepted: bool
    session_id: int


class SendResult(TypedDict):
    accepted: bool
    session_id: int
    run_id: int


class SessionSubscription(TypedDict):
    session_id: int
    subscribed: bool


class ExperimentAccepted(TypedDict):
    accepted: bool
    experiment_id: int


class ResumeResult(TypedDict):
    accepted: bool
    experiment_id: int
    attempt_ids: list[int]


class RetryResult(TypedDict):
    accepted: bool
    retried_attempt_id: int
    attempt_id: int


class ExperimentSubscription(TypedDict):
    experiment_id: int
    subscribed: bool


class RunEvents(TypedDict):
    run: s.RunRecord
    events: list[s.RunEventRecord]
    last_sequence: int
    has_more: bool


@dataclass(frozen=True)
class RpcMethod:
    params: type[BaseModel]
    result: Any


# One authoritative method/parameter/result map, also consumed by generation.
RPC_METHODS = {
    "health.check": RpcMethod(EmptyParams, HealthResult),
    "workspace.clone_github": RpcMethod(s.WorkspaceCloneGithub, s.WorkspaceRecord),
    "workspace.create": RpcMethod(s.WorkspaceCreate, s.WorkspaceRecord),
    "workspace.list": RpcMethod(CatalogListParams, list[s.WorkspaceRecord]),
    "workspace.get": RpcMethod(s.WorkspaceIdParams, s.WorkspaceRecord),
    "workspace.rename": RpcMethod(s.WorkspaceRename, s.WorkspaceRecord),
    "workspace.delete": RpcMethod(s.WorkspaceIdParams, WorkspaceDeleted),
    "workspace.git_status": RpcMethod(s.WorkspaceIdParams, GitStatus),
    "workspace.git_stage": RpcMethod(s.GitStageParams, GitActionResult),
    "workspace.git_commit": RpcMethod(s.GitCommitParams, GitActionResult),
    "workspace.git_push": RpcMethod(s.GitPushParams, GitActionResult),
    "workspace.git_push_main": RpcMethod(s.WorkspaceIdParams, GitActionResult),
    "session.create": RpcMethod(s.SessionCreate, s.SessionRecord),
    "session.list": RpcMethod(SessionListParams, list[s.SessionRecord]),
    "session.get": RpcMethod(s.SessionIdParams, s.SessionRecord),
    "session.delete": RpcMethod(s.SessionIdParams, SessionDeleted),
    "session.history": RpcMethod(s.SessionHistoryParams, s.SessionHistoryRecord),
    "session.send": RpcMethod(s.SessionSend, SendResult),
    "session.cancel": RpcMethod(s.SessionIdParams, SessionAccepted),
    "session.stop": RpcMethod(s.SessionIdParams, SessionAccepted),
    "session.subscribe": RpcMethod(s.SessionIdParams, SessionSubscription),
    "session.unsubscribe": RpcMethod(s.SessionIdParams, SessionSubscription),
    "run.get": RpcMethod(s.RunIdParams, s.RunRecord),
    "run.events": RpcMethod(s.RunEventsParams, RunEvents),
    "run.artifacts": RpcMethod(s.RunIdParams, list[s.RunArtifactRecord]),
    "run.diff.get": RpcMethod(s.RunDiffParams, RunDiff),
    "run.diff.accept": RpcMethod(s.RunDiffParams, RunDiff),
    "run.diff.revert": RpcMethod(s.RunDiffParams, RunDiff),
    "eval.case.create": RpcMethod(s.EvalCaseCreate, EvalCase),
    "eval.case.create_from_run": RpcMethod(s.EvalCaseCreateFromRun, EvalCase),
    "eval.case.list": RpcMethod(EmptyParams, list[EvalCase]),
    "eval.case.get": RpcMethod(s.EvalCaseIdParams, EvalCase),
    "eval.case.update_draft": RpcMethod(s.EvalCaseUpdateDraft, EvalCase),
    "eval.case.revise": RpcMethod(s.EvalCaseRevisionParams, EvalCase),
    "eval.case.validate": RpcMethod(s.EvalCaseRevisionParams, EvalCase),
    "eval.case.publish": RpcMethod(s.EvalCaseRevisionParams, EvalCase),
    "eval.suite.create": RpcMethod(s.EvalSuiteCreate, EvalSuite),
    "eval.suite.list": RpcMethod(EmptyParams, list[EvalSuite]),
    "eval.suite.get": RpcMethod(s.EvalSuiteIdParams, EvalSuite),
    "eval.suite.update_draft": RpcMethod(s.EvalSuiteUpdateDraft, EvalSuite),
    "eval.suite.freeze": RpcMethod(s.EvalSuiteVersionParams, EvalSuite),
    "eval.config.capture": RpcMethod(s.EvalConfigCapture, EvalConfig),
    "eval.config.list": RpcMethod(EmptyParams, list[EvalConfig]),
    "eval.config.get": RpcMethod(s.EvalConfigIdParams, EvalConfig),
    "eval.config.diff": RpcMethod(s.EvalConfigDiffParams, ConfigDiff),
    "eval.experiment.preflight": RpcMethod(s.EvalExperimentPlan, EvalPreflight),
    "eval.experiment.create": RpcMethod(s.EvalExperimentPlan, EvalExperiment),
    "eval.experiment.list": RpcMethod(EmptyParams, list[EvalExperiment]),
    "eval.experiment.get": RpcMethod(s.EvalExperimentIdParams, EvalExperiment),
    "eval.experiment.start": RpcMethod(s.EvalExperimentIdParams, ExperimentAccepted),
    "eval.experiment.cancel": RpcMethod(s.EvalExperimentIdParams, ExperimentAccepted),
    "eval.experiment.resume": RpcMethod(s.EvalExperimentIdParams, ResumeResult),
    "eval.experiment.subscribe": RpcMethod(
        s.EvalExperimentIdParams, ExperimentSubscription
    ),
    "eval.experiment.unsubscribe": RpcMethod(
        s.EvalExperimentIdParams, ExperimentSubscription
    ),
    "eval.experiment.events": RpcMethod(
        s.EvalExperimentEventsParams, list[EvalExperimentEvent]
    ),
    "eval.attempt.get": RpcMethod(s.EvalAttemptIdParams, EvalAttemptDetail),
    "eval.attempt.steps": RpcMethod(s.EvalAttemptIdParams, list[EvalStep]),
    "eval.attempt.events": RpcMethod(s.EvalAttemptIdParams, list[EvalAttemptEvent]),
    "eval.attempt.artifact": RpcMethod(s.EvalAttemptArtifactParams, EvalScorerOutput),
    "eval.attempt.retry": RpcMethod(s.EvalAttemptIdParams, RetryResult),
}

RESULT_ADAPTERS = {name: TypeAdapter(spec.result) for name, spec in RPC_METHODS.items()}
