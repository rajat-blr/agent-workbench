# Agent Workbench: Evals Mode

**Document status:** Proposed  
**Target release:** Post-v1 / Evals MVP  
**Last updated:** 2026-09-30  
**Product type:** Extension of the shipped local-first desktop application  
**Indicative effort:** 7–9 weeks at approximately 15 hours per week  

## 1. Executive summary

Agent Workbench v1 lets a developer open a local repository, work with Codex in persistent conversations, observe a concise activity summary, inspect a per-run Git diff, and explicitly accept, revert, stage, commit, or push changes.

Evals Mode will extend that workflow from **using Codex** to **measuring Codex**.

The product will let a developer:

1. Turn a real task or failure into a reusable eval case.
2. Define objective, reproducible success checks.
3. Run the same versioned cases against two Codex configurations in disposable Git worktrees.
4. Compare pass rate, paired case flips, runtime, token use, and infrastructure reliability.
5. Inspect the scorer evidence, code diff, and normalized execution steps for any attempt.

The primary product question is:

> Given the same tasks, did this specific Codex configuration perform better, and what evidence supports that conclusion?

Evals Mode is not intended to become a hosted eval platform, generic observability system, prompt playground, or multi-agent orchestration framework. It remains a focused capability inside the existing local desktop application.

## 2. Current product baseline

This PRD is designed around the implementation already shipped in Agent Workbench v1.

### 2.1 Shipped capabilities

- Electron desktop shell for macOS.
- React and TypeScript frontend built with Vite.
- Bundled FastAPI backend frozen with PyInstaller.
- Authenticated local HTTP/WebSocket communication.
- SQLite database stored in the app-data directory.
- WAL mode, foreign keys, and a SQLite busy timeout.
- Local workspaces and persistent chat sessions.
- One durable run record per user prompt.
- Full Codex JSONL event persistence.
- Persistent assistant and user messages.
- Codex thread resumption within a chat session.
- Per-run Git baseline and final diff capture.
- Accept and safe-revert controls for completed run changes.
- Explicit stage, commit, and push controls.
- Static recorded demo build deployed through Vercel.
- Apple Silicon DMG and ZIP packaging.

### 2.2 Relevant current constraints

- A run currently belongs to a chat session.
- Session events currently require a session ID.
- Runtime process ownership is keyed by session ID.
- Only one run may be active for a registered workspace.
- Backend restart marks active runs as failed.
- Database startup uses SQLAlchemy `create_all()`; there is no migration system.
- Codex model and sandbox settings are configured globally when the backend starts, not per run.
- The frontend is a single chat-oriented application shell rather than a routed multi-mode product.
- The demo runtime contains hard-coded recorded chat data.
- Current stored event samples are dominated by command execution events and are not diverse enough to validate sophisticated trajectory heuristics.
- The app relies on the user’s separately installed and authenticated Codex CLI.
- v1 distribution is unsigned and not notarized.

### 2.3 Product maturity implication

Evals Mode must be built as a careful extension of a small shipped product. It should not introduce a separate service, hosted account system, distributed queue, or large framework. The work should proceed in independently shippable vertical slices, with existing chat and Git review behavior protected throughout.

## 3. Problem statement

Agent Workbench currently helps a user complete and review individual Codex tasks, but it does not help them answer whether a change to their Codex setup improved performance.

Users currently judge changes such as a new model, reasoning setting, or AGENTS instructions through anecdotal experience. This creates four problems:

1. **No repeatability.** A useful or failed real-world task is not easily converted into a reusable test.
2. **No objective outcome.** A successful process exit or plausible final response does not prove the task was completed correctly.
3. **No controlled comparison.** Configurations are not run against identical task and repository states.
4. **Weak diagnosis.** Raw events exist, but they are too verbose to efficiently explain a failed attempt.

## 4. Product principles

### 4.1 Evidence before interpretation

Deterministic verifier results, code diffs, commands, and raw events take precedence over inferred explanations.

### 4.2 Immutable inputs

Any case, suite, or configuration used by an experiment must remain reproducible. Editing creates a new revision or snapshot.

### 4.3 Local-first by default

Source code, prompts, traces, outputs, and eval results stay on the user’s machine unless the user explicitly exports them.

### 4.4 Honest uncertainty

The product may conclude that a result is inconclusive. It must not turn small or noisy samples into confident claims.

### 4.5 Outcomes are distinct from execution status

A Codex process can complete while the task fails. An environment can fail before Codex starts. These states must never be conflated.

### 4.6 Useful abstraction with inspectable evidence

Results should open at the highest useful level, while every aggregate and inference links back to concrete attempts and raw evidence.

### 4.7 Protect the shipped workflow

Chat, session history, live activity, diff review, and Git controls must continue to work throughout development and after release.

## 5. Goals

### G1. Create reusable cases from real work

A user can create a prefilled draft eval case from a completed chat run in no more than two explicit actions.

### G2. Produce trustworthy objective outcomes

Every runnable v1 case has at least one validated deterministic scorer. Process completion alone never produces a passing outcome.

### G3. Protect the live checkout

Every eval attempt runs in a disposable Git worktree at a pinned commit and never operates directly in the user’s active checkout.

### G4. Compare configurations fairly

Two immutable configuration snapshots can be run against the same immutable suite version, producing paired per-case results.

### G5. Survive normal desktop interruptions

Experiment state persists across app restarts. Interrupted attempts remain recorded and can be retried without losing evidence.

### G6. Explain failures efficiently

For any failed attempt, the user can move from failed scorer to verifier output, final diff, normalized steps, and raw events.

### G7. Fit the existing product

Evals Mode uses the existing Electron, FastAPI, WebSocket, SQLite, Git, and Codex CLI architecture without adding a hosted backend.

## 6. Non-goals for the MVP

- Hosted execution or cloud synchronization.
- Multi-user collaboration, authentication, or roles.
- Support for agents other than Codex.
- Generic OTLP or third-party trace ingestion.
- A general prompt playground.
- Replay from an arbitrary trajectory step.
- Automatic pull request creation.
- Continuous production monitoring.
- LLM-as-judge scoring.
- More than two configurations in one comparison.
- Full MCP or plugin reproducibility.
- Guaranteed machine-level isolation.
- Automatic monetary cost calculation.
- Statistical claims from insufficient sample sizes.

## 7. Users and jobs to be done

### Primary user: Codex power user

**Job:** When I change my model, reasoning setting, or project instructions, I want to know whether the change improves outcomes on tasks that matter to me.

### Secondary user: repository maintainer

**Job:** When I standardize Codex instructions for a project, I want evidence that they help across representative tasks rather than one demonstration.

### Secondary user: reviewer or portfolio visitor

**Job:** When I inspect an experiment, I want to understand the hypothesis, result, uncertainty, and supporting evidence without learning the entire application.

## 8. Terminology

| Term | Definition |
| --- | --- |
| Case | Stable identity for an eval task across revisions. |
| Case revision | Immutable prompt, repository state, setup, verifier, and constraints. |
| Suite | Named collection of related cases. |
| Suite version | Immutable ordered collection of case revisions. |
| Configuration | Named Codex setup across snapshots. |
| Configuration snapshot | Immutable, hashed effective setup used for an experiment. |
| Experiment | Evaluation of one suite version against one or two configuration snapshots. |
| Attempt | One case revision × configuration snapshot × sample execution. |
| Run | Underlying Codex process and its durable events/artifacts. |
| Scorer | Deterministic evaluator that returns a result and evidence. |
| Outcome | Pass, fail, infrastructure error, timeout, cancellation, or invalid case. |
| Step | Derived, human-readable projection over one or more raw runtime events. |
| Review signal | Heuristic indication of potentially problematic behavior; not a claimed cause. |

## 9. Core user journeys

### 9.1 Convert a real run into a case

1. User opens a completed chat run.
2. User selects **Create eval case**.
3. The app creates a draft containing:
   - source workspace;
   - prompt;
   - starting commit;
   - starting dirty patch, when present;
   - source run and resulting diff;
   - candidate verification commands detected from completed command events.
4. User selects or enters a deterministic verifier.
5. User optionally attaches held-out verifier files and path constraints.
6. User runs **Validate case**.
7. The app provisions the base state, runs setup, confirms the verifier behavior, and reports problems.
8. User publishes an immutable case revision.

### 9.2 Build and freeze a suite

1. User creates a suite.
2. User adds published case revisions.
3. The app shows repository, language, validation state, and estimated setup cost.
4. User orders the cases and freezes a suite version.
5. Future changes create a new suite version.

### 9.3 Define configurations

1. User creates Config A from the current effective setup.
2. User duplicates it to create Config B.
3. User changes one intended variable, such as model, reasoning effort, or AGENTS instructions.
4. The app displays a structured diff and highlights uncontrolled inputs.
5. Launch preflight warns when more than the intended variable differs.

### 9.4 Launch an experiment

1. User chooses a frozen suite version.
2. User chooses one or two configuration snapshots.
3. User selects samples per case, timeout, and concurrency.
4. Preflight displays:
   - number of attempts;
   - invalid or stale cases;
   - configuration differences;
   - repositories involved;
   - isolation level;
   - expected token/quota use without fabricating a monetary estimate;
   - whether network or external MCP dependencies are present.
5. User starts the experiment.
6. The app streams attempt status and aggregate progress.
7. User may cancel queued/running work.

### 9.5 Compare results

1. User opens a completed or partial experiment.
2. The app presents pass rate, paired flips, tokens, duration, and infrastructure errors.
3. The app provides a plain-language verdict: better, worse, or inconclusive.
4. User filters cases by improved, regressed, unchanged, failed, or infrastructure error.
5. User opens an attempt to inspect its evidence.

### 9.6 Diagnose an attempt

1. Attempt opens with outcome and required scorer results.
2. Failed scorer evidence is visible before trajectory information.
3. User inspects verifier output and final diff.
4. User inspects derived steps and review signals.
5. User expands a step to inspect linked raw events or complete output artifacts.

## 10. Scope and priority

### 10.1 P0: MVP

- Database migrations and schema versioning.
- Runs that may originate from chat or eval attempts.
- Immutable case revisions.
- Immutable suite versions.
- Immutable configuration snapshots.
- Config comparison limited to two snapshots.
- Worktree provisioning and cleanup.
- Starting patch support.
- Deterministic command, file assertion, diff constraint, and tamper scorers.
- Held-out verifier bundle support.
- Case validation.
- Persistent experiment scheduler.
- Concurrency, timeout, cancellation, retry, and restart reconciliation.
- Tokens and duration when emitted by Codex.
- Raw JSONL and large output artifacts.
- Basic step normalization.
- Experiment result matrix and paired flips.
- Attempt evidence view.
- Existing chat and Git-review regression coverage.

### 10.2 P1: Strong follow-up

- Multiple samples per case in the primary UI.
- Case-level paired bootstrap.
- Review signals and trajectory aggregates.
- Notes and failure tags.
- Suite import/export.
- Rerun selected failures.
- Dependency setup cache.
- Static experiment export with redaction preview.
- Recorded read-only demo experiment.

### 10.3 P2: Deferred

- LLM judge and calibration workflow.
- More than two configurations.
- Side-by-side step alignment.
- Hosted report publishing.
- MCP/plugin configuration comparison.
- Container or remote runner.
- Team collaboration.

## 11. Functional requirements

### 11.1 Execution foundation

| ID | Requirement | Priority |
| --- | --- | --- |
| EX-01 | A run can originate from a chat session or an eval attempt. | P0 |
| EX-02 | A run has exactly one origin and retains a durable origin reference. | P0 |
| EX-03 | Run events remain ordered, durable, and queryable without a chat session. | P0 |
| EX-04 | The Codex executor accepts per-run model, reasoning, sandbox, config, working directory, timeout, and environment inputs. | P0 |
| EX-05 | Chat continues to resume its Codex thread; eval attempts always start fresh. | P0 |
| EX-06 | Large raw outputs are retained as artifacts without forcing complete payloads into every list response. | P0 |
| EX-07 | A fake executor can drive scheduler and lifecycle tests without consuming Codex usage. | P0 |

### 11.2 Cases

| ID | Requirement | Priority |
| --- | --- | --- |
| CA-01 | Create a draft case from a completed chat run. | P0 |
| CA-02 | Create and edit a draft case manually. | P0 |
| CA-03 | Publish an immutable case revision with a content hash. | P0 |
| CA-04 | Pin each revision to a repository and full base commit SHA. | P0 |
| CA-05 | Store an optional starting patch for tasks captured from a dirty repository state. | P0 |
| CA-06 | Require at least one deterministic scorer before publication. | P0 |
| CA-07 | Support a held-out verifier bundle stored outside the agent-visible worktree. | P0 |
| CA-08 | Validate provisioning, setup, verifier availability, and base-state behavior. | P0 |
| CA-09 | Never mutate a revision already used in a frozen suite or experiment. | P0 |

### 11.3 Suites

| ID | Requirement | Priority |
| --- | --- | --- |
| SU-01 | Create, rename, and describe a suite. | P0 |
| SU-02 | Add, remove, and order published case revisions in a draft version. | P0 |
| SU-03 | Freeze a suite version with a content hash. | P0 |
| SU-04 | Experiments reference a frozen suite version. | P0 |
| SU-05 | Editing a frozen suite creates a new version. | P0 |

### 11.4 Configuration snapshots

| ID | Requirement | Priority |
| --- | --- | --- |
| CF-01 | Capture model, reasoning effort, effective instructions, project configuration, sandbox policy, and CLI version. | P0 |
| CF-02 | Preserve instruction files in resolution order, including applicable AGENTS and override files. | P0 |
| CF-03 | Never persist credential or secret values. | P0 |
| CF-04 | Record uncontrolled inputs that cannot be reproduced or isolated. | P0 |
| CF-05 | Hash the canonical redacted snapshot for identity. | P0 |
| CF-06 | Show a structured diff between two snapshots. | P0 |
| CF-07 | Warn when multiple dimensions differ. | P0 |
| CF-08 | Add MCP/plugin snapshots only after credential and availability semantics are defined. | P1 |

### 11.5 Experiment scheduler

| ID | Requirement | Priority |
| --- | --- | --- |
| SC-01 | Expand an experiment into deterministic attempts before execution begins. | P0 |
| SC-02 | Interleave Config A and B attempts rather than running all of A before B. | P0 |
| SC-03 | Default concurrency to one and permit a low configurable limit. | P0 |
| SC-04 | Enforce per-attempt timeout and experiment cancellation. | P0 |
| SC-05 | Do not launch new attempts after cancellation is requested. | P0 |
| SC-06 | Preserve completed and interrupted attempt evidence. | P0 |
| SC-07 | Retry creates a new attempt with an incremented retry index. | P0 |
| SC-08 | On restart, running attempts become interrupted and may be requeued by explicit user action. | P0 |
| SC-09 | Clean or quarantine orphan worktrees during startup reconciliation. | P0 |

### 11.6 Worktree and setup

| ID | Requirement | Priority |
| --- | --- | --- |
| WT-01 | Create a detached worktree at the pinned commit for every attempt. | P0 |
| WT-02 | Apply the case starting patch before setup and agent execution. | P0 |
| WT-03 | Run every subprocess with the worktree as its working directory and a filtered environment. | P0 |
| WT-04 | Use process groups so timeout or cancellation terminates subprocess descendants. | P0 |
| WT-05 | Capture setup time separately from agent time. | P0 |
| WT-06 | A setup failure produces `infra_error`, not `fail`. | P0 |
| WT-07 | Clean the worktree after artifacts are safely captured. | P0 |
| WT-08 | Retain a failed worktree only through an explicit debugging option and show its disk impact. | P1 |

### 11.7 Scoring

| ID | Requirement | Priority |
| --- | --- | --- |
| SR-01 | Command scorer passes on configured exit-code criteria. | P0 |
| SR-02 | File assertion scorer supports existence, absence, contains, regex, and JSON-value checks. | P0 |
| SR-03 | Diff constraint scorer supports allowed, forbidden, and required changed paths. | P0 |
| SR-04 | Tamper scorer detects agent changes to forbidden paths. | P0 |
| SR-05 | Held-out verifier files are materialized only after the Codex process exits. | P0 |
| SR-06 | Scorer results contain pass/fail, value, summary, and evidence. | P0 |
| SR-07 | All required scorers must pass for an attempt outcome of `pass`. | P0 |
| SR-08 | Scorer infrastructure failures produce `infra_error` or `invalid`, not task failure. | P0 |
| SR-09 | Adding a scorer can rescore stored attempt artifacts when agent re-execution is unnecessary. | P1 |

### 11.8 Steps and evidence

| ID | Requirement | Priority |
| --- | --- | --- |
| ST-01 | Pair item start and completion events by source item ID. | P0 |
| ST-02 | Convert completed Codex items into ordered derived steps. | P0 |
| ST-03 | Link every step to its source event range. | P0 |
| ST-04 | Store normalizer version and permit recomputation. | P0 |
| ST-05 | Preserve full raw JSONL as the source of truth. | P0 |
| ST-06 | Show truncated previews while allowing full artifact inspection. | P0 |
| ST-07 | Review signals are explicitly labeled as heuristic. | P1 |
| ST-08 | Initial signals include repeated failing command, missing verification after edits, forbidden change, timeout, and unusually late first edit. | P1 |

### 11.9 Results and comparison

| ID | Requirement | Priority |
| --- | --- | --- |
| RS-01 | Show sample-level pass rate with Wilson confidence interval. | P0 |
| RS-02 | Show paired per-case flips: A-only pass and B-only pass. | P0 |
| RS-03 | Show tokens, agent duration, setup duration, changed files, and diff size. | P0 |
| RS-04 | Show infrastructure errors separately and exclude them from the task pass-rate denominator. | P0 |
| RS-05 | Every aggregate links to its attempts. | P0 |
| RS-06 | Use exact McNemar only for one binary paired outcome per case. | P0 |
| RS-07 | Use case-level resampling when repeated samples are introduced. | P1 |
| RS-08 | Verdict language supports better, worse, and inconclusive. | P0 |
| RS-09 | Do not calculate monetary cost unless an authoritative price and billing basis are available. | P0 |

## 12. User experience and information architecture

### 12.1 Global navigation

The app header gains a persistent product-mode switch:

```text
Chat | Evals
```

Switching modes does not stop active work. Running chat and experiment state remains accessible through status indicators.

### 12.2 Evals navigation

Evals Mode contains:

1. **Experiments** — default landing page.
2. **Cases** — draft and published cases.
3. **Suites** — suite composition and version history.
4. **Configurations** — definitions, snapshots, and diffs.

### 12.3 Experiments list

Each row shows:

- experiment name or generated hypothesis label;
- suite version;
- compared configurations;
- status and progress;
- pass-rate summary when available;
- infrastructure error count;
- creation/completion time;
- resume or open action.

### 12.4 Experiment launch

Launch is a short staged form:

1. Suite version.
2. Config A and optional Config B.
3. Samples, timeout, and concurrency.
4. Preflight review.

The primary action states the number of attempts, for example: **Run 24 attempts**.

### 12.5 Experiment detail

The detail screen prioritizes:

1. Plain-language verdict.
2. Pass rates and uncertainty.
3. Improved/regressed/unchanged case counts.
4. Infrastructure health.
5. Tokens and runtime.
6. Case-by-configuration matrix.

Matrix cells show pass, fail, infrastructure error, running, queued, timeout, cancelled, or invalid. Selecting a cell opens the attempt.

### 12.6 Attempt detail

Display order:

1. Outcome and status.
2. Required scorer results.
3. Failed scorer evidence and verifier output.
4. Final diff.
5. Steps.
6. Raw events and complete artifacts.

This screen should reuse the existing run diff presentation where practical rather than build a second diff renderer.

### 12.7 Case editor

Sections:

- Identity and source run.
- Repository and base state.
- Prompt.
- Setup.
- Required scorers.
- Held-out verifier files.
- Allowed and forbidden paths.
- Validation report.

Publishing remains disabled until required validation checks succeed.

### 12.8 Empty, partial, and error states

- First-time Evals Mode explains cases, suites, configurations, and experiments in one short flow.
- Partial experiments show available results without presenting them as final.
- Invalid cases link directly to the failed validation stage.
- Missing base commits or repository paths provide recovery actions rather than generic errors.
- A missing Codex CLI or expired login uses the same actionable language as chat execution.

## 13. Technical architecture

### 13.1 Target component structure

```text
Electron shell
  └── React application
       ├── Chat mode
       └── Evals mode
            ├── Experiments
            ├── Cases and suites
            ├── Configurations
            └── Attempt evidence

Authenticated local HTTP/WebSocket
  └── FastAPI backend
       ├── existing chat/session services
       ├── execution service
       ├── eval case service
       ├── configuration snapshot service
       ├── persistent experiment scheduler
       ├── worktree service
       ├── scorer registry
       ├── step normalizer
       └── comparison/statistics service

SQLite metadata
App-data artifact directory
Git worktrees
Separately installed Codex CLI
```

### 13.2 Backend module boundaries

Suggested structure:

```text
backend/
  executions/
    executor.py
    lifecycle.py
    artifacts.py
  evals/
    cases.py
    configs.py
    worktrees.py
    scheduler.py
    scorers.py
    normalizer.py
    statistics.py
    service.py
  database/
    migrations/
```

The existing RPC dispatcher should delegate `eval.*` methods to the eval service instead of accumulating all feature logic in `main.py`.

### 13.3 Artifact storage

SQLite stores metadata, indexes, relationships, summaries, and small evidence payloads.

The app-data artifact directory stores potentially large immutable files:

- compressed raw Codex JSONL;
- full command outputs when previews are truncated;
- starting patches;
- held-out verifier bundles;
- scorer logs;
- exported reports.

Each artifact record includes type, path, SHA-256, byte size, and redacted metadata. Writes use a temporary file followed by atomic rename.

### 13.4 Event transport

The existing broker continues to publish chat session events. It gains experiment-scoped progress events such as:

- `eval.experiment.started`
- `eval.attempt.status_changed`
- `eval.attempt.completed`
- `eval.experiment.progress`
- `eval.experiment.completed`

Clients subscribe by experiment ID. Reconnection uses durable database state plus monotonically ordered event IDs, following the existing subscribe-then-history pattern.

## 14. Data model

The exact SQLAlchemy definitions will be finalized during implementation, but the conceptual schema is:

```text
runs
  id
  kind: chat | eval
  session_id nullable
  eval_attempt_id nullable
  workspace_path
  prompt
  status
  pid, return_code, error
  created_at, started_at, completed_at

run_events
  id, run_id, source_event_id
  event_type, payload_preview
  artifact_id nullable
  created_at

run_artifacts
  id, run_id nullable
  artifact_type, relative_path, sha256, byte_size
  metadata_json, created_at

eval_cases
  id, title, description, created_at

eval_case_revisions
  id, case_id, revision, content_hash
  workspace_id, base_sha
  starting_patch_artifact_id nullable
  prompt, setup_spec_json, scorer_spec_json
  verifier_artifact_id nullable
  path_policy_json
  validation_status, validation_details_json
  created_at

eval_suites
  id, name, description, created_at

eval_suite_versions
  id, suite_id, version, content_hash, frozen_at

eval_suite_version_cases
  suite_version_id, case_revision_id, ordinal

eval_configs
  id, name, description, created_at

eval_config_snapshots
  id, config_id, content_hash
  model, reasoning_effort
  instructions_json, codex_config_json
  sandbox_policy_json, cli_version
  uncontrolled_inputs_json
  created_at

eval_experiments
  id, name, suite_version_id
  status, samples_per_case, concurrency
  timeout_seconds, cancel_requested
  created_at, started_at, completed_at

eval_experiment_configs
  experiment_id, config_snapshot_id, ordinal

eval_attempts
  id, experiment_id, case_revision_id
  config_snapshot_id, sample_index, retry_index
  run_id nullable
  status, outcome, failure_category
  worktree_path nullable
  setup_duration_ms, agent_duration_ms, scoring_duration_ms
  input_tokens nullable, cached_input_tokens nullable
  output_tokens nullable, reasoning_output_tokens nullable
  created_at, started_at, completed_at

eval_scores
  id, attempt_id, scorer_key
  required, passed nullable, value_json
  summary, evidence_json, artifact_id nullable

eval_steps
  id, run_id, sequence
  source_event_start_id, source_event_end_id
  source_item_id nullable
  kind, title, status, duration_ms nullable
  signature, flags_json, summary
  normalizer_version
```

### 14.1 Immutability rules

- Published case revisions are immutable.
- Frozen suite versions are immutable.
- Configuration snapshots used by an experiment are immutable.
- Experiment settings are immutable after attempts are expanded, except cancellation state.
- Attempt results and raw artifacts are append-only; retry creates a new attempt.
- Derived steps and statistics may be recomputed with an explicit version.

## 15. Configuration reproducibility

The MVP supports a deliberately controlled configuration surface:

- model;
- reasoning effort;
- effective project instructions;
- optional experiment-specific instruction preamble;
- sandbox mode;
- network policy where supported;
- Codex CLI version.

Snapshot capture records applicable instruction files in their resolution order and canonicalizes redacted configuration before hashing.

The app must distinguish:

- **Controlled input:** materialized or explicitly passed by Agent Workbench.
- **Observed input:** detected and recorded but not fully controlled.
- **External dependency:** authenticated service, MCP server, network endpoint, or organization policy that may change independently.

An experiment may proceed with observed or external inputs, but the UI must disclose them. Secrets are never copied into snapshots or exports.

## 16. Runner safety and isolation

### 16.1 MVP safety boundary

The MVP provides workspace isolation, not full machine isolation.

Guarantees:

- Codex runs in a disposable worktree.
- The live checkout is not the attempt working directory.
- Codex uses an explicit restricted sandbox configuration.
- Backend-launched commands use the worktree as `cwd`.
- Subprocesses receive a filtered environment.
- Process descendants are terminated on cancellation or timeout.
- Git base and final state are recorded.

Non-guarantees:

- A user-supplied setup or scorer command is not a complete OS sandbox.
- Local processes may still access machine resources permitted by the operating system.
- Network denial cannot be claimed unless independently enforced and verified.

The UI must describe this boundary accurately. Strong machine isolation through containers or VMs is deferred.

### 16.2 Setup and scorer commands

- Commands are stored as structured specifications with command, arguments or script, timeout, and environment allowlist.
- Commands never inherit the full Electron/backend environment.
- Output is capped and overflow is written to an artifact.
- Setup commands run before credentials needed for Codex are introduced wherever possible.
- Scoring runs after Codex credentials are no longer present in the process environment.

### 16.3 Worktree cleanup

- Cleanup happens only after event, diff, and scorer artifacts are durable.
- Cleanup failure is recorded without changing a valid task outcome.
- Startup reconciliation detects registered and orphaned eval worktrees.
- The user can view and remove retained debugging worktrees.

## 17. Scoring model

### 17.1 Scorer interface

Every scorer receives a bounded context:

- case revision;
- worktree path;
- final diff metadata;
- configured timeout;
- artifact writer;
- filtered environment.

Every scorer returns:

- scorer key and version;
- required or informational status;
- passed, failed, or unavailable;
- structured value;
- short summary;
- bounded inline evidence;
- optional complete evidence artifact.

### 17.2 Overall outcome rules

| Condition | Outcome |
| --- | --- |
| Agent completed and all required scorers passed | `pass` |
| Agent completed and at least one required scorer failed | `fail` |
| Provisioning, setup, executor, or scorer infrastructure failed | `infra_error` |
| Attempt exceeded its wall-clock timeout | `timeout` |
| User or experiment cancelled the attempt | `cancelled` |
| Case revision cannot produce a meaningful evaluation | `invalid` |

Agent process failure may result in `fail` or `infra_error` depending on whether the failure is attributable to task behavior or the execution environment. The classification and evidence must be preserved.

### 17.3 Case validation

Validation checks:

- repository path exists and is a Git repository;
- pinned commit resolves;
- starting patch applies cleanly;
- verifier bundle hash matches;
- setup succeeds;
- scorer commands can start;
- held-out files are absent from the agent-visible state;
- required paths are within the worktree;
- base-state expectation is met.

For bug-fix cases, the default base-state expectation is that at least one required verifier fails before agent work. Cases that are expected to add new behavior may define a different explicit expectation.

## 18. Step normalization

### 18.1 V1 deterministic mapping

- Pair `item.started` and `item.completed` using Codex item ID.
- Create one step per completed item.
- Preserve incomplete items when a run stops unexpectedly.
- Represent agent messages as narrative milestones.
- Represent turn-level failures and stderr errors separately.
- Derive duration where both boundaries exist.
- Store normalized command, exit code, files, tool name, and bounded preview.

### 18.2 Step types

- command execution;
- file change;
- MCP tool call;
- web search;
- plan update;
- reasoning milestone when exposed;
- agent message;
- runtime error;
- other.

### 18.3 Later phase inference

Explore/Edit/Verify phase labels are P1. They must be tuned against a diverse fixture corpus before becoming part of the primary UI.

### 18.4 Review signals

P1 signals include:

- identical failing command repeated;
- command error followed by unrelated activity;
- file edits with no later verification;
- forbidden path change;
- late first edit;
- timeout or prolonged inactivity;
- unusually large or repetitive output.

Signals are evidence links, not diagnoses. Precision should be measured against human labels before prominence increases.

## 19. Statistics and verdicts

### 19.1 Required metrics

- completed attempts;
- pass, fail, timeout, cancellation, invalid, and infrastructure-error counts;
- sample-level pass rate;
- Wilson confidence interval;
- A-only pass and B-only pass counts;
- exact McNemar result for one paired binary sample per case;
- median and distribution of agent duration;
- setup duration;
- input, cached input, output, and reasoning tokens when present;
- files changed and diff size.

### 19.2 Repeated samples

Repeated samples are P1 in the primary UX. When enabled:

- show both attempt-level pass rate and per-case pass fraction;
- preserve case as the independent resampling unit;
- compute a paired bootstrap over cases for the difference;
- never treat repeated attempts on one case as independent cases.

### 19.3 Verdict language

Verdicts must include the observed difference, sample size, flip direction, and uncertainty.

Examples:

- **Better:** “Config B passed more cases, with substantially more improvements than regressions.”
- **Worse:** “Config B regressed on more paired cases than it improved.”
- **Inconclusive:** “Config B passed 68% versus 60%, but this experiment does not contain enough evidence to distinguish the difference from run-to-run variation.”

The UI must not use “statistically significant” as a synonym for useful, nor “not significant” as proof that configurations are equal.

## 20. RPC surface

Indicative methods:

```text
eval.case.create_from_run
eval.case.create
eval.case.update_draft
eval.case.validate
eval.case.publish
eval.case.list
eval.case.get

eval.suite.create
eval.suite.update_draft
eval.suite.freeze
eval.suite.list
eval.suite.get

eval.config.capture
eval.config.create_variant
eval.config.diff
eval.config.list
eval.config.get

eval.experiment.preflight
eval.experiment.create
eval.experiment.start
eval.experiment.cancel
eval.experiment.resume
eval.experiment.list
eval.experiment.get
eval.experiment.subscribe
eval.experiment.unsubscribe

eval.attempt.get
eval.attempt.steps
eval.attempt.events
eval.attempt.artifact
eval.attempt.retry
```

Mutating methods validate state transitions server-side. Artifact reads enforce record ownership through local database relationships even though the application is single-user.

## 21. Non-functional requirements

### Reliability

- Experiment state survives backend and application restarts.
- No completed attempt is overwritten by retry or recomputation.
- Infrastructure failures never count as task failures.
- Worktree cleanup is idempotent.
- Database writes use short transactions.

### Performance

- Experiment list opens in under one second for 100 experiments on development hardware.
- Result matrix remains interactive for at least 500 attempts.
- Attempt overview opens without loading full raw outputs.
- A 500-step trace becomes interactive in under one second after data retrieval.
- Long lists and traces use virtualization where needed.

### Storage

- Large output is capped in SQLite previews.
- Complete outputs are stored as compressed artifacts.
- Experiment detail shows approximate disk usage.
- Artifact retention and cleanup policy is documented before public release.

### Security and privacy

- Everything remains local unless explicitly exported.
- Secrets are removed from configuration snapshots.
- Export performs redaction and shows a preview before writing.
- Paths in exported reports are repository-relative where possible.
- The UI does not overstate worktree isolation.

### Compatibility

- Existing v1 database data migrates without losing sessions, messages, events, or diffs.
- Existing chat runs remain readable.
- Development, packaged app, and static demo builds continue to pass.
- The initial target remains macOS Apple Silicon, matching the shipped release.

### Accessibility

- Status is never conveyed only by color.
- Experiment matrix cells have accessible labels.
- Core comparison and attempt navigation are keyboard accessible.
- Long output and diff regions have clear focus behavior.

## 22. Migration and backward compatibility

### 22.1 Migration requirement

Add a lightweight ordered migration runner before changing existing tables. It must:

- record applied migration versions;
- execute each migration transactionally where SQLite permits;
- support table-copy migrations required by SQLite;
- back up or safely preserve the existing database before a destructive schema rewrite;
- be covered by a test that upgrades a representative v1 database.

### 22.2 Existing data

- Existing runs become `kind = chat`.
- Existing run/session relationships remain intact.
- Existing events are migrated to run-scoped storage while preserving event IDs or an explicit sequence mapping.
- Existing diffs continue to resolve through their run IDs.
- Historical runs may be normalized into steps on demand.
- Historical runs without a reproducible Git base can still be viewed but may not be convertible into a valid case.

### 22.3 Rollback strategy

Before the first migration that rewrites an existing table, create a timestamped database backup in app data. If migration fails, do not start the backend against a partially migrated database; restore or retain the backup and present an actionable error.

## 23. Testing strategy

### Backend unit tests

- migration ordering and v1 upgrade;
- canonical hashing and secret removal;
- case immutability;
- suite freezing;
- attempt state transitions;
- worktree creation, patching, and cleanup;
- command and file scorers;
- held-out verifier materialization;
- outcome classification;
- Wilson interval and McNemar calculations;
- normalizer pairing and incomplete events;
- artifact truncation and hashing.

### Backend integration tests

- single case from provisioning through scoring;
- two-config experiment through comparison;
- cancellation kills descendant processes;
- backend restart reconciles running attempts;
- retry preserves the earlier attempt;
- source checkout remains unchanged;
- orphan worktree cleanup;
- concurrent SQLite writes at configured limits.

All automated lifecycle tests use a fake executor except a manually invoked smoke suite for the real Codex CLI.

### Frontend tests

- experiment launch preflight;
- partial and completed result rendering;
- matrix filtering and accessible labels;
- attempt evidence ordering;
- case validation errors;
- configuration diff;
- reconnect and history reconciliation.

### Packaging checks

- backend freeze includes new modules and migration files;
- packaged app can migrate a copied v1 database;
- app can find Git and the separately installed Codex CLI;
- application quit cancels or reconciles active attempts safely;
- DMG and ZIP builds complete;
- static demo build remains independent of a live backend.

## 24. Delivery plan

The plan assumes approximately 15 hours per week. Each phase has a product-visible exit criterion.

### Phase 0: Foundation audit and migrations — 1 week

- Introduce migration runner.
- Capture sanitized event fixtures from 20–30 diverse runs.
- Document observed Codex item and usage shapes.
- Define artifact directory and retention rules.
- Write the v1 database upgrade fixture.

**Exit:** A copied v1 database upgrades safely, and event fixtures cover commands, edits, failures, plan updates, tool calls where available, and cancellation.

### Phase 1: General execution layer — 1 week

- Make runs independently addressable from chat or eval origins.
- Refactor the current runtime into a reusable per-run executor.
- Preserve chat thread resumption.
- Add raw JSONL artifact capture and bounded previews.
- Add fake executor coverage.

**Exit:** Existing chat works through the new execution layer with no visible regression.

### Phase 2: Single-case vertical slice — 1 to 1.5 weeks

- Add case and case-revision models.
- Add worktree service and starting patches.
- Add command and file assertion scorers.
- Add held-out verifier bundle.
- Add validation and a minimal case editor.

**Exit:** One validated case runs end to end and produces a durable pass/fail, diff, usage, and evidence without changing the live checkout.

### Phase 3: Suites, configs, and experiments — 1 to 1.5 weeks

- Add suite versions.
- Add controlled configuration snapshots and diff.
- Add experiment expansion and scheduler.
- Add timeout, cancel, restart reconciliation, and retry.
- Stream live experiment progress.

**Exit:** Two configurations run across a five-case suite, and the experiment survives an app restart.

### Phase 4: Results and comparison — 1 week

- Build experiment list and detail views.
- Add pass rates, intervals, flips, tokens, duration, and infra-error reporting.
- Add case-by-config matrix and filters.
- Add plain-language verdict.

**Exit:** A user can determine which configuration performed better and open every supporting attempt.

### Phase 5: Attempt evidence and steps — 1 week

- Implement normalizer v1.
- Build attempt overview, scorer evidence, diff, steps, and raw event disclosure.
- Add normalizer recomputation.
- Reuse the existing diff component.

**Exit:** A failed attempt can be diagnosed without manually reading the JSONL artifact.

### Phase 6: Hardening and release — 1 week

- Validate cancellation and cleanup under failure.
- Test large outputs and long traces.
- Complete migration, packaging, and regression testing.
- Create a recorded demo experiment.
- Update README and release documentation.

**Exit:** Packaged Evals Mode runs a small real experiment, existing chat remains stable, and the recorded demo communicates the product without a backend.

## 25. Success metrics

### Product usability

- Draft case creation from a completed run requires no more than two explicit actions.
- At least 80% of authored cases can be made runnable without editing files outside the app after scorer support stabilizes.
- A user can identify the failed scorer and relevant code change for a failed attempt in under two minutes.
- A new viewer can explain the experiment verdict and one supporting flip within three minutes.

### Reliability

- No observed changes to a live checkout across the validation suite.
- Less than 5% infrastructure-error rate on the maintained local reference suite after excluding deliberate failure tests.
- All interrupted attempts are accounted for after restart.
- No orphaned worktrees remain after successful cleanup cycles.

### Evaluation quality

- Every passing attempt has at least one required deterministic scorer.
- Every aggregate metric links to attempt evidence.
- Invalid and infrastructure-error attempts are excluded correctly.
- Review-signal precision is measured on at least 50 human-labeled signals before signals are promoted in the UI.

## 26. Risks and mitigations

| Risk | Consequence | Mitigation |
| --- | --- | --- |
| Refactoring runs breaks shipped chat behavior | Regression in the core product | Refactor behind compatibility tests before adding eval UI. |
| Existing database cannot be safely evolved | User history loss | Add migrations and tested v1 upgrade backup before schema changes. |
| Cases pass vacuously | Misleading comparison | Validate base-state expectations and require deterministic scorers. |
| Agent can read held-out tests | Inflated results | Keep verifier bundles outside the worktree until scoring. |
| Setup or scorer scripts access the machine | Safety issue | Filter environment, bound processes, document isolation honestly, add stronger isolation later. |
| User configuration leaks into attempts | Irreproducible comparisons | Controlled snapshot surface, explicit execution overrides, and uncontrolled-input warnings. |
| Event output makes SQLite huge | Slow app and disk growth | Bounded previews plus compressed immutable artifacts. |
| Batch execution exhausts account quota | Interrupted experiments | Low default concurrency, attempt preflight, cancellation, and resumable queue. |
| Configuration order creates temporal bias | Misleading A/B result | Interleave A/B attempts by case and sample. |
| Too few cases produce false confidence | Bad product guidance | Confidence intervals, paired flips, minimum-evidence warnings, and inconclusive verdicts. |
| Normalizer heuristics overstate causality | Distracting diagnosis | Deterministic v1 steps; label later signals as heuristic and measure precision. |
| Feature overwhelms the compact v1 UI | Product complexity | Separate Chat/Evals mode and progressively disclose evidence. |

## 27. Open decisions

These decisions should be resolved during the corresponding implementation phase rather than blocking the full project:

1. Whether to migrate `session_events` into `run_events` or retain a compatibility projection during the first release.
2. Exact mechanism for isolating configuration while reusing the user’s Codex authentication.
3. Whether setup specifications accept shell scripts or only argv-style commands in the MVP.
4. Maximum inline event/output size before artifact offloading.
5. Artifact retention policy and default disk budget.
6. Whether validation requires an explicit known-good patch for certain case types.
7. Minimum paired case count before displaying a stronger better/worse verdict.
8. Whether the recorded demo reuses the full Evals UI or a reduced read-only route.

## 28. Release cut lines

If schedule pressure occurs, cut in this order:

1. Review signals.
2. Multiple samples in the primary UI.
3. Suite import/export.
4. Static experiment export.
5. Dependency caching.
6. Notes and annotations.
7. Recorded hosted comparison beyond the existing demo mechanism.

Do not cut:

- database migrations;
- immutable inputs;
- disposable worktrees;
- held-out verification;
- process-status versus task-outcome separation;
- infrastructure-error separation;
- persistent restart-safe scheduling;
- paired case comparison;
- evidence drill-down;
- regression protection for chat and Git review.

## 29. Definition of done

The Evals MVP is complete when all of the following are true:

- A completed chat run can create a prefilled draft case.
- A case cannot be published without a deterministic scorer and successful validation.
- Published case revisions, suite versions, and configuration snapshots are immutable.
- Two configuration snapshots can run against the same frozen suite.
- Every attempt uses a disposable worktree at the pinned repository state.
- Held-out verifier files are unavailable to Codex during execution.
- Process completion, task outcome, and infrastructure failure are represented separately.
- Experiment progress persists through an application restart.
- Retrying an interrupted or failed attempt preserves the original evidence.
- Results show pass rates, uncertainty, paired flips, tokens, duration, and infrastructure errors.
- Every result links to scorer evidence, verifier output, final diff, steps, and raw artifacts.
- Existing chat sessions, event history, run diffs, accept/revert behavior, and Git controls continue to work.
- A representative v1 database migrates successfully.
- Backend tests, frontend build/lint, packaged application build, and recorded demo build pass.
- The UI and documentation accurately describe the limits of local worktree isolation.

