# Agent Workbench

A local-first desktop workspace for coding with Codex and evaluating agent configurations against reproducible tasks. Chat with your codebase, review changes, and inspect evaluation results in one app.

[Download v1 for macOS (Apple Silicon)](https://github.com/rajat-blr/agent-workbench/releases/download/v1/Agent.Workbench-0.1.0-arm64.dmg) · [v1 release](https://github.com/rajat-blr/agent-workbench/releases/tag/v1)

The linked v1 release predates the current source build's Evals lab. Build from source for the features described below. macOS Apple Silicon packaging is verified; other platforms are not release-verified.

## Install and start

1. Install the Codex CLI separately and authenticate with `codex login`.
2. Open the downloaded DMG and drag Agent Workbench to Applications.
3. Launch the app, add a workspace folder, and start a conversation. Adding a workspace creates its first session.

The DMG bundles the backend: Python, Node.js, and a database service are not required for end users. Codex CLI is **not bundled**. Local builds are unsigned; macOS may warn on first launch. Signing/notarization is not configured in this repository.

## Chat workspace

- Register, rename, and organize local workspaces with persistent conversation sessions.
- Ask Codex to explain or change a project; later prompts resume the session's recorded Codex thread.
- Follow live assistant output and a concise work summary, with cancellation controls and retained run history.
- Generate an interactive codebase map for project-explanation requests.
- Inspect per-run Git diffs and explicitly accept or revert changes. Runs without a usable Git baseline cannot provide a reproducible change review.
- Stage, commit, and push with explicit controls. These actions require the repository root on `main`, with no active run; staging uses `git add .` and pushing targets `origin main`. Nothing is committed or pushed automatically.

Only one chat run can be active in a workspace at a time, preventing overlapping change reviews. Chat can also run in non-Git folders, without Git-backed review features.

## Evals lab

Use the separate **Chat workspace** and **Evals lab** buttons to switch modes. Evals history is independent of chat sessions.

### Cases and suites

Create a task directly or from a recorded run, with a repository, pinned Git baseline, prompt, optional starting patch, setup commands, and graders. Validate the case before publishing. Published revisions are immutable; clone a revision to edit its prompt while retaining its grading setup. Group published cases into an ordered suite and freeze a version for experiments.

Graders support command execution, file assertions, and diff constraints such as allowed production paths. Held-out verifier bundles are materialized after agent execution and diff capture. Each attempt uses a disposable Git worktree; setup, agent execution, scoring, and cleanup remain separate stages.

### Configurations and experiments

Capture immutable configuration snapshots, then compare them on the same frozen suite. Snapshots record model, reasoning effort, instruction preamble, sandbox/network policy, discovered instruction files, and detected CLI version. Configuration diffs expose changed inputs before launch.

Preflight checks the experiment inputs before execution. Choose configurations, samples per case, concurrency, and a per-attempt timeout; start or cancel the queue, explicitly resume interrupted work, or retry an attempt. Retries retain the original attempt and evidence rather than overwriting history.

### Results and evidence

- Per-case/configuration outcomes and filters, including improvements, regressions, and unchanged pairs.
- Pass rates with explicit evaluable denominators, confidence intervals, and paired comparisons. Timeouts, invalid cases, cancellations, and infrastructure errors remain distinct outcomes; unavailable evidence is not a functional failure.
- Separate setup, agent, and scoring durations, plus available input/cached/output/reasoning token counts. Missing usage remains unknown, not zero.
- Attempt details with normalized execution steps, ordered events, source diffs, scorer summaries, and full-output artifacts where available.
- Compressed raw Codex JSONL traces and immutable artifact metadata with SHA-256 checksums and byte sizes.

Paired results can be inconclusive; repeated-sample comparisons remain descriptive until case-level uncertainty is implemented. Small curated suites do not establish broad model rankings.

### Instruction capture and execution boundaries

In **Evals lab → Configurations**, select a workspace to capture global guidance followed by the Git root down to that workspace. A non-empty `AGENTS.override.md` takes precedence over `AGENTS.md`; nested files below the selected workspace are not scanned. Capture skips symlinks, limits instruction text to 32 KiB, reports missing/truncated sources, and stores ordered, redacted copies.

Instruction files and CLI versions are **observed, not pinned**. Attempts use the case baseline's project files and the installed executable. Only explicit model/reasoning settings, the preamble, and restricted sandbox/network policy are applied; arbitrary project settings are not forwarded. Custom instruction fallback names and external authentication remain uncontrolled. Capture a new snapshot when inputs change.

Recognizable credential assignments and bearer/API-key patterns are redacted, but this is not a general secret detector. Never put secrets in prompts, preambles, or instruction files. Disposable worktrees and delayed verifiers are not a hardened secrecy boundary.

## Architecture and local data

Electron hosts a React/TypeScript/Vite UI and launches a local FastAPI backend. Authenticated WebSocket JSON-RPC carries desktop requests and live events; authenticated HTTP JSON-RPC is also available. The backend runs the separately installed `codex exec --json`, manages agent processes and Git worktrees, and persists history through SQLAlchemy and SQLite.

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
cd ..

# Frontend build, lint, and demo checks
npm --prefix frontend run build
npm --prefix frontend run lint
npm --prefix frontend run test:demo
```

For a backend-free browser demo, run `npm --prefix frontend run build:demo`, then `npm --prefix frontend run preview`. Its Evals comparison is explicitly **synthetic and read-only**, with example results, configuration differences, traces, and diffs. It is not evidence of real model performance. Rebuild normally before packaging a production app.

## Real evaluation coverage and release status

Five external T3 Code scenarios cover trimmed-ID schemas, worker failure/shutdown recovery, cache pruning, concurrent settings updates, and IndexedDB recovery. Frozen baselines, held-out checks, immutable configurations, real traces, and cleanup audits are documented in the [suite record](docs/evals-t3code-suite.md).

The v1 and scope-explicit v2 comparisons are **inconclusive**, not a model recommendation. V2 completed ten attempts, including a timeout overlapping host sleep; original outcomes and evidence are retained. See the [v1 comparison](docs/evals-t3code-comparison-report.md), [v2 comparison](docs/evals-t3code-v2-comparison-report.md), and [timeout investigation](docs/evals-timeout-investigation-2026-10-08.md).

For verified packaging/lifecycle checks and remaining interactive restart/resume, window-resizing, real-demo, and release-signing work, see the [release checklist](docs/evals-release-checklist.md). Source-build capabilities do not imply full release sign-off.
