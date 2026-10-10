# Agent Workbench

A local-first evaluation workbench for coding agents. Compare Codex configurations on the same frozen tasks, visualize correctness and execution time, and inspect the responses, code changes and traces behind every result. A built-in chat workspace supports everyday coding and change review.

[Download v2 for macOS (Apple Silicon)](https://github.com/rajat-blr/agent-workbench/releases/download/v2/Agent.Workbench-0.1.0-arm64.dmg) · [Release notes](https://github.com/rajat-blr/agent-workbench/releases/tag/v2)

**v2 includes Evals.** The current source build adds visual comparisons and a recorded Zod + Hono demo. These newer source features are not a claim about the contents of the previously built installer. macOS Apple Silicon packaging is verified; other platforms are not release-verified.

- **Controlled comparisons:** immutable task revisions, frozen suites and hashed configuration snapshots.
- **Visual results:** score and timing charts, a case-by-configuration grid, and improvement, regression and failure filters.
- **Inspectable evidence:** side-by-side responses, patches, grader output and execution traces with artifact checksums.
- **Local execution:** disposable Git worktrees, held-out tests, bounded concurrency, cancellation and retained retry history.

## Real benchmark showcase

Four public-history regression tasks from **Zod and Hono**, evaluated with `gpt-6.1-sol` at low and high reasoning. One sample per task/configuration: **eight real attempts, no retries**.

| Reasoning effort | Passed cases | Median agent execution | Total output tokens |
| --- | --- | --- | --- |
| Low | 4/4 | 60.5s | 7,528 |
| High | 4/4 | 102.1s | 15,607 |

Tasks cover numeric enum options, integer bounds, empty query parameters and resilient pretty-JSON responses. Held-out tests failed on parent baselines and passed after reference fixes; final grading also checks production-only changes.

**Verdict: inconclusive.** Four tied cases demonstrate the evaluation workflow, not a model ranking or general speed advantage. Public-history contamination and model training cutoff are unverified. No measured sensitivity-control result is claimed. See the [run report](docs/evals-portfolio-comparison.md), [recorded evidence](frontend/src/data/portfolioBenchmark.json) and [upstream licenses](evals/THIRD_PARTY_LICENSES.md).

## Try the recorded demo

```sh
npm --prefix frontend install
npm --prefix frontend run build:demo
npm --prefix frontend run preview
```

Open the preview URL. The demo starts in **Evals lab** with the real comparison already loaded; it needs no backend, CLI authentication or model calls. Explore score/timing charts, select **Compare outputs**, and switch between **Responses**, **Code changes**, **Scorer results** and **Execution traces**. **Configurations** shows the reasoning-only difference.

Evals is a read-only replay of captured results. Chat examples are synthetic. Rebuild with `npm --prefix frontend run build` before packaging a production app. Redeploy the demo build to update a hosted copy.

## Evals lab

Turn “does this configuration work better?” into a repeatable coding experiment. Run candidates against identical case revisions, grade their changes, and compare results without losing the underlying evidence.

Use the separate **Chat workspace** and **Evals lab** buttons to switch modes. Evals history is independent of chat sessions. The workflow is: **create and validate cases → freeze a suite → capture configurations → run and compare**.

### Cases and suites

Create a task directly or from a recorded run, with a repository, pinned Git baseline, prompt, optional starting patch, setup commands, and graders. Validate the case before publishing. Published revisions are immutable; clone a revision to edit its prompt while retaining its grading setup. Group published cases into an ordered suite and freeze a version for experiments.

Graders support command execution, file assertions, and diff constraints such as allowed production paths. Held-out verifier bundles are materialized after agent execution and diff capture. Each attempt uses a disposable Git worktree; setup, agent execution, scoring, and cleanup remain separate stages.

### Configurations and experiments

Capture immutable configuration snapshots, then compare them on the same frozen suite. Snapshots record model, reasoning effort, instruction preamble, sandbox/network policy, discovered instruction files, and detected CLI version. Configuration diffs expose changed inputs before launch.

Preflight checks the experiment inputs before execution. Choose configurations, samples per case, concurrency, and a per-attempt timeout; start or cancel the queue, explicitly resume interrupted work, or retry an attempt. Retries retain the original attempt and evidence rather than overwriting history.

### Results and evidence

- Visual case-weighted pass-rate and median execution-time charts, plus a case-by-configuration outcome grid.
- Side-by-side responses, patches, grader results and trace timelines for the same task and sample.
- Per-case/configuration outcomes and filters, including improvements, regressions, unchanged pairs and failures.
- Pass rates with explicit evaluable denominators, confidence intervals, and paired comparisons. Timeouts, invalid cases, cancellations, and infrastructure errors remain distinct outcomes; unavailable evidence is not a functional failure.
- Separate setup, agent, and scoring durations, plus available input/cached/output/reasoning token counts. Missing usage remains unknown, not zero.
- Attempt details with normalized execution steps, ordered events, source diffs, scorer summaries, and full-output artifacts where available.
- Compressed raw Codex JSONL traces and immutable artifact metadata with SHA-256 checksums and byte sizes.

The analysis unit is the case, not the attempt. Evals aggregates repeated samples into per-case pass rates, weights cases equally, and uses an exact paired case-level sign test with case-bootstrap intervals. Missing and infrastructure outcomes are excluded explicitly; uniform outcomes can produce collapsed intervals without establishing certainty. Small curated suites do not establish broad model rankings.

Optional history-mining tools export history-free baselines and validate held-out tests failing before the reference patch and passing after it. A dry-run-first sensitivity-control tool prepares normal versus deliberately no-edit instructions without automatically starting agents. See [benchmark tooling](evals/README.md) and [methodology and limits](docs/evals-benchmark-methodology.md).

### Instruction capture and execution boundaries

In **Evals lab → Configurations**, select a workspace to capture global guidance followed by the Git root down to that workspace. A non-empty `AGENTS.override.md` takes precedence over `AGENTS.md`; nested files below the selected workspace are not scanned. Capture skips symlinks, limits instruction text to 32 KiB, reports missing/truncated sources, and stores ordered, redacted copies.

Instruction files and CLI versions are **observed, not pinned**. Attempts use the case baseline's project files and the installed executable. Only explicit model/reasoning settings, the preamble, and restricted sandbox/network policy are applied; arbitrary project settings are not forwarded. Custom instruction fallback names and external authentication remain uncontrolled. Capture a new snapshot when inputs change.

Recognizable credential assignments and bearer/API-key patterns are redacted, but this is not a general secret detector. Never put secrets in prompts, preambles, or instruction files. Disposable worktrees and delayed verifiers are not a hardened secrecy boundary.

## Install the desktop app

1. Install the Codex CLI separately and authenticate with `codex login`.
2. Open the downloaded DMG and drag Agent Workbench to Applications.
3. Launch the app and add a workspace folder. Switch to **Evals lab** to create an evaluation, or use **Chat workspace** for coding.

For a new evaluation, select a repository, define and validate a task, capture configurations and start the comparison. Open **Evals lab → Evaluations → Open results** to review completed runs. The recorded portfolio dataset is bundled with the browser demo; a fresh desktop installation does not automatically import it into its local database.

The DMG bundles the backend: Python, Node.js and a database service are not required for end users. Codex CLI is **not bundled**. Local builds are unsigned; macOS may warn on first launch. Signing/notarization is not configured in this repository.

## Supporting chat workspace

- Register, rename, and organize local workspaces with persistent conversation sessions.
- Ask Codex to explain or change a project; later prompts resume the session's recorded Codex thread.
- Follow live assistant output and a concise work summary, with cancellation controls and retained run history.
- Generate an interactive codebase map for project-explanation requests.
- Inspect per-run Git diffs and explicitly accept or revert changes. Runs without a usable Git baseline cannot provide a reproducible change review.
- Stage explicitly selected files, review the staged file list before committing, and confirm a configured remote and destination branch before pushing. These actions require the repository root on a checked-out branch, with no active run. Nothing is selected, committed, or pushed automatically; there is no force-push control. Stale branch/index reviews are rejected. These safer controls are in the current source build and require rebuilding the app.

Only one chat run can be active in a workspace at a time, preventing overlapping change reviews. Chat can also run in non-Git folders, without Git-backed review features.

## Architecture and local data

Electron hosts a React/TypeScript/Vite UI and launches a local FastAPI backend. Authenticated WebSocket JSON-RPC carries desktop requests and live events; authenticated HTTP JSON-RPC is also available. The backend runs the separately installed `codex exec --json`, manages agent processes and Git worktrees, and persists history through SQLAlchemy and SQLite.

The current source build serves packaged UI files through a restricted `workbench://app` protocol, applies a CSP limited to the exact loopback backend, blocks in-app navigation/popups, and validates desktop IPC senders. HTTP(S) links open in the system browser; remote embedded resources are blocked. Backend crashes show an error rather than silently disconnecting. Normal quit waits for agent/scorer cleanup before escalating termination. These safeguards require rebuilding the desktop app; hard crashes can still leave orphaned agents. See [security and CI checks](docs/ci-electron-hardening.md).

Electron normally stores `agent-workbench.db` in its OS application-data directory. Artifacts and eval worktrees default beside the database. SQLite migrations run on startup; destructive table-copy migrations create a backup first. No PostgreSQL service or hosted application backend is required.

History is local to the computer: there is no cloud sync or built-in backup/restore UI. Preserve the database and artifact directory together when backing up. Deleting application data deletes local history and evidence. Codex may communicate with OpenAI services through your CLI authentication; local-first does not mean model execution is offline.

The backend rejects `danger-full-access` and passes a filtered environment to Codex. Command scorers retain up to 4 MiB per output stream, with bounded previews and full-output artifacts within that cap. Exceeding it is an infrastructure/unavailable result. On macOS/POSIX, scorer cancellation and timeout terminate the process group. Hard-crash reconciliation does not guarantee orphan-agent termination.

Phase durations use the event-loop clock to match timeout enforcement. Host sleep can consume timeout budget with a sleep-inclusive clock; prevent sleep during real comparisons. Historical measurements are not rewritten by later fixes.

## Develop locally

Prerequisites: Python 3.14, `uv`, Node.js compatible with Vite 8, npm, Git, and an installed/authenticated Codex CLI. Demo tests additionally require Node's `--experimental-strip-types` support.

From the repository root:

```sh
cd backend
uv sync --group dev
cd ../frontend
npm install
cd ..
npm --prefix frontend run dev
```

Electron starts the backend automatically, allocates a loopback port, and supplies a local authentication token. Restart the backend after backend source changes; rebuild packaged apps to include them.

Common overrides:

| Setting | Purpose |
| --- | --- |
| `CODEX_COMMAND`, `CODEX_MODEL` | CLI executable and optional default model |
| `AGENT_SANDBOX`, `AGENT_TIMEOUT_SECONDS` | Chat sandbox and runtime limit; defaults: `workspace-write`, 3600 seconds |
| `DATABASE_URL` | Alternate SQLite location |
| `ARTIFACT_DIRECTORY`, `EVAL_WORKTREE_DIRECTORY` | Alternate evidence and disposable-worktree roots |
| `AGENT_WORKBENCH_USER_DATA_DIR` | Absolute Electron profile path for isolated development/QA |
| `START_BACKEND=false`, `BACKEND_URL`, `BACKEND_AUTH_TOKEN` | Connect Electron to an already running authenticated backend |

For manual server startup, origin controls, remaining settings, schema details, and RPC documentation, see [backend/README.md](backend/README.md).

## Build and check

```sh
# Production UI only
npm --prefix frontend run build

# Unpacked desktop app, including frozen Python backend
npm --prefix frontend run package

# macOS DMG and ZIP artifacts
npm --prefix frontend run make
```

Packaging uses PyInstaller and Electron Forge. Installer artifacts are written under `frontend/out/make/`. Public distribution requires a signing/notarization policy.

```sh
# Backend tests and lint; tests use local adapters, not paid model runs
cd backend
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
cd ..

# Frontend build, lint, and regression checks
npm --prefix frontend run build
npm --prefix frontend run lint
npm --prefix frontend run test:demo
npm --prefix frontend run test:git
npm --prefix frontend run test:chat
npm --prefix frontend run test:catalog
npm --prefix frontend run test:contract
npm --prefix frontend run test:electron
```

[CI](.github/workflows/ci.yml) runs backend lint/tests with Python 3.14 via `uv`, frontend type checks/lint, demo/Git/chat-sync/catalog/RPC tests, Electron safeguard tests, a production build, and a hidden Electron smoke test on every push and pull request. Hook dependencies are lint-enforced. Chat synchronization merges live events with history and guards against stale session responses; see [coverage and limits](docs/frontend-chat-sync.md). Workspace/chat catalogs load through bounded pages without the previous 500-chat truncation; see [pagination limits](docs/catalog-pagination.md). Checks use locked dependencies and no real model calls. To run the smoke test locally after building, use `npm --prefix frontend run test:electron:smoke` (Linux requires a display or `xvfb-run`).

The [shared RPC contract](docs/rpc-contract.md) generates frontend method, parameter, and response types from backend definitions. [Registered domain handlers](docs/rpc-handlers.md) implement the backend methods without oversized dispatch chains. CI rejects stale generated types and checks invalid-call regressions; normal frontend builds need no Python. Regenerate after backend contract changes with `cd backend && .venv/bin/python tools/generate_rpc_contract.py`.

[Repository policy](docs/lint-repository-policy.md) documents the stronger backend lint/format checks, scoped test/tool exceptions, and private PRD naming conventions. Runtime development still requires Python 3.14; Ruff's older syntax target preserves parenthesized exception handlers without claiming older-runtime support.

## Release verification

The macOS package also passes a [601-workspace/chat UI check](docs/catalog-packaged-verification.md), including oldest-chat selection and independent sidebar scrolling. After `npm --prefix frontend run package`, rerun it with `npm --prefix frontend run test:package:catalog` (macOS; requires the backend virtualenv for fixture seeding). New source-build statistics and benchmark tooling do not imply that the previously built installer contains them.

For verified packaging/lifecycle checks and remaining interactive restart/resume, window-resizing and release-signing work, see the [release checklist](docs/evals-release-checklist.md). Source-build capabilities do not imply full release sign-off.

## License

Licensed under the [MIT License](LICENSE). Third-party dependencies and external evaluation code retain their respective licenses.
