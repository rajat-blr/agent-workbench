# Agent Workbench backend

The backend owns workspace registration, SQLite history, Codex processes, and live session events. Each prompt creates a durable run and launches `codex exec --json` in the selected workspace. Later prompts resume the Codex thread recorded for that session.

## Database

The default URL is:

```text
sqlite+aiosqlite:///./agent_workbench.db
```

Electron overrides this with a database inside its application-data directory. Set `DATABASE_URL` to choose another SQLite file. Tables are created on startup; migrations are intentionally deferred for now.

SQLite is configured with foreign keys, WAL mode, and a five-second busy timeout.

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
- `CODEX_SKIP_GIT_REPO_CHECK`: allow non-Git workspaces, default `false`
- `AGENT_TIMEOUT_SECONDS`: maximum runtime for one prompt, default 3600
- `ALLOWED_ORIGINS`: comma-separated WebSocket/HTTP origins

The backend deliberately rejects `danger-full-access`. Codex inherits a filtered environment rather than every secret available to the desktop process.

## Transport

HTTP JSON-RPC is available at `POST /rpc` with `Authorization: Bearer <token>`.

The desktop client uses `ws://127.0.0.1:8000/ws` and sends the token through the `auth.<token>` WebSocket subprotocol. This keeps the secret out of access-log URLs. Connections require both the token and an allowed `Origin`.

Supported methods:

- `health.check`
- `workspace.create`, `workspace.list`, `workspace.get`
- `session.create`, `session.list`, `session.get`, `session.history`
- `session.send`, `session.cancel`, `session.stop`
- `session.subscribe`, `session.unsubscribe`

`session.history.after_sequence` uses the durable SQLite event ID. Clients should subscribe first, then request history so events produced during synchronization can be deduplicated safely.

## Checks

```sh
.venv/bin/pytest -q
.venv/bin/ruff format --check main.py settings.py event_broker.py agent_runtime.py database tests
.venv/bin/ruff check main.py settings.py event_broker.py agent_runtime.py database tests
```

The tests use small subprocess adapters and never consume a Codex subscription.
