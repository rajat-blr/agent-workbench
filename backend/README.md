# Agent Workbench backend

The backend owns workspace registration, SQLite history, Codex processes, and live session events. Each prompt creates a durable run and launches `codex exec --json` in the selected workspace. Later prompts resume the Codex thread recorded for that session.

## Database

The default URL is:

```text
sqlite+aiosqlite:///./agent_workbench.db
```

Electron overrides this with a database inside its application-data directory. Set `DATABASE_URL` to choose another SQLite file. Ordered migrations run on startup, and destructive table-copy migrations create a timestamped SQLite backup first.

SQLite is configured with foreign keys, WAL mode, and a five-second busy timeout.

The durable schema is defined in `database/models.py` and its Python record/response
types in `database/schemas.py` and `database/types.py`:

| Table | Stored data |
| --- | --- |
| `workspaces` | Unique local folder path, display name, creation time |
| `sessions` | Workspace, Codex thread ID, title, status, timestamps |
| `runs` | One chat or eval execution, durable origin, workspace, process/status/error details |
| `messages` | Ordered user and assistant conversation text, linked to a run |
| `run_events` | Ordered runtime events with a SQLite JSON payload, queryable by run |
| `run_diffs` | Per-run Git baseline while active and saved final change review |
| `run_artifacts` | Immutable artifact metadata, hashes, sizes, and relative storage paths |
| `eval_cases` | Stable case identity, title, description, and timestamps |
| `eval_case_revisions` | Draft or immutable published task inputs and validation state |
| `eval_suites`, `eval_suite_versions` | Named suites and immutable ordered case collections |
| `eval_configs`, `eval_config_snapshots` | Named configurations and redacted immutable setup snapshots |
| `eval_experiments`, `eval_attempts` | Immutable launch plans and deterministically expanded attempt queues |

Conversation messages remain rows of text, not one large JSON document. Event payloads
use SQLAlchemy's `JSON` type, which stores JSON text in SQLite. Session deletion
cascades to its chat runs, messages, and events. Eval runs are independent of chat
sessions. Database constraints enforce valid origins, providers, statuses, and
message roles. Existing v1 data is upgraded and retained by the migration runner.

## Start manually

The local API requires a secret. Use the same value in clients connecting to the WebSocket.

```sh
uv sync --group dev
LOCAL_AUTH_TOKEN=development-only-token uv run fastapi dev main.py
```

To connect the Electron client to that manually started server:

```sh
START_BACKEND=false BACKEND_AUTH_TOKEN=development-only-token npm --prefix ../frontend run dev
```

Optional settings:

- `CODEX_COMMAND`: Codex executable, default `codex`
- `CODEX_MODEL`: optional model override
- `AGENT_SANDBOX`: `read-only` or `workspace-write`, default `workspace-write`
- `CODEX_SKIP_GIT_REPO_CHECK`: always skip the Git check, default `false`. The backend enables it automatically for a user-selected workspace that is not inside a Git repository.
- `AGENT_TIMEOUT_SECONDS`: maximum runtime for one prompt, default 3600
- `ARTIFACT_DIRECTORY`: optional artifact root; defaults to `artifacts` beside the SQLite database
- `EVAL_WORKTREE_DIRECTORY`: disposable eval worktree root; defaults beside the SQLite database
- `ALLOWED_ORIGINS`: comma-separated WebSocket/HTTP origins

The backend deliberately rejects `danger-full-access`. Codex inherits a filtered environment rather than every secret available to the desktop process.

## Transport

HTTP JSON-RPC is available at `POST /rpc` with `Authorization: Bearer <token>`.

The desktop client uses `ws://127.0.0.1:8000/ws` and sends the token through the `auth.<token>` WebSocket subprotocol. This keeps the secret out of access-log URLs. Connections require both the token and an allowed `Origin`.

Supported methods:

- `health.check`
- `workspace.create`, `workspace.list`, `workspace.get`
- `workspace.git_status`, `workspace.git_stage`, `workspace.git_commit`, `workspace.git_push_main`
- `session.create`, `session.list`, `session.get`, `session.history`
- `session.send`, `session.cancel`, `session.stop`
- `session.subscribe`, `session.unsubscribe`
- `run.get`, `run.events`, `run.artifacts`
- `eval.case.create_from_run`, `eval.case.create`, `eval.case.update_draft`, `eval.case.validate`, `eval.case.publish`, `eval.case.list`, `eval.case.get`
- `eval.suite.create`, `eval.suite.update_draft`, `eval.suite.freeze`, `eval.suite.list`, `eval.suite.get`
- `eval.config.capture`, `eval.config.diff`, `eval.config.list`, `eval.config.get`
- `eval.experiment.preflight`, `eval.experiment.create`, `eval.experiment.start`, `eval.experiment.cancel`, `eval.experiment.list`, `eval.experiment.get`
- `eval.attempt.get`, `eval.attempt.steps`, `eval.attempt.events`

`session.history.after_sequence` uses the durable SQLite event ID. Clients should subscribe first, then request history so events produced during synchronization can be deduplicated safely.

`session.send` accepts optional `mode: "map"` in addition to its default chat mode.
Map runs ask Codex to include structured component data in its answer; the backend
validates the data, saves it as an `artifact.codebase_map` event, and keeps the JSON
out of conversation text. All Codex events remain in SQLite for history and
diagnostics, but the live WebSocket forwards only status, meaningful item, error,
assistant-text, and artifact events.

Full Codex stdout is retained as a compressed, immutable `raw_jsonl` artifact.
SQLite event payloads are bounded previews; artifact records include SHA-256 and
byte size so large traces do not need to be loaded with run or session history.

`run.diff.get` takes `session_id` and `run_id`. It refreshes a running diff and
returns the saved final review after completion. The diff service reads Git's
index and worktree but never stages, stashes, commits, or resets user files.
Only one run can be active in a workspace at a time, so simultaneous sessions
do not produce overlapping change reviews. The new `run_diffs` table is created
on startup without altering existing tables; runs recorded before this feature
report that no diff was captured.

The workspace Git actions require a workspace at the repository root on the
`main` branch, with no active run. Stage executes `git add .`; commit requires a
message and executes `git commit -m <message>`; push executes
`git push -u origin main`. Commands run without a shell, and push uses the
machine's existing Git credentials. No branch is created automatically.

## Checks

```sh
.venv/bin/pytest -q
.venv/bin/ruff format --check main.py settings.py event_broker.py agent_runtime.py codebase_map.py run_diffs.py database tests
.venv/bin/ruff check main.py settings.py event_broker.py agent_runtime.py codebase_map.py run_diffs.py database tests
```

The tests use small subprocess adapters and never consume a Codex subscription.
