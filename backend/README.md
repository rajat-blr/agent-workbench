## Agent Harness Backend

This backend is the local environment server for a native coding-agent client. It owns the workspace path, agent process, PostgreSQL history, and live session events. The desktop client communicates over HTTP JSON-RPC and one shared WebSocket connection.

### Run PostgreSQL

From the repository root:

```sh
docker compose up -d postgres
```

The default connection is `postgresql+asyncpg://rajat:rajat@localhost:5432/fastapi_db`. Set `DATABASE_URL` to override it. Standard `postgresql://` URLs are converted automatically for the async driver.

### Start the server

From `backend/`:

```sh
source .venv/bin/activate
AGENT_MODE=fake fastapi dev main.py
```

The default `AGENT_MODE=fake` runs the local subscription-free test agent. It reads prompts from stdin and streams a deterministic response back through the same runtime path as a real provider.

For a real CLI, use `AGENT_MODE=command AGENT_COMMAND=codex fastapi dev main.py`. Use `AGENT_COMMAND=claude` for a Claude-style CLI, or provide another quoted command. The command runs with the registered workspace as its current directory and receives prompts on stdin.

### JSON-RPC

HTTP endpoint: `POST /rpc`

```json
{
	"jsonrpc": "2.0",
	"id": 1,
	"method": "workspace.create",
	"params": {"path": "/Users/me/project", "name": "Project"}
}
```

Supported methods include `health.check`, `workspace.create`, `workspace.list`, `workspace.get`, `session.create`, `session.list`, `session.get`, `session.history`, `session.send`, `session.cancel`, and `session.stop`.

### WebSocket

Connect to `ws://127.0.0.1:8000/ws` and send the same JSON-RPC request objects. The server sends live events as JSON-RPC notifications:

```json
{
	"jsonrpc": "2.0",
	"method": "session.event",
	"params": {
		"session_id": 1,
		"type": "agent.stdout",
		"payload": {"content": "Reading files..."}
	}
}
```

The WebSocket is a transport connection, not the owner of the agent. Closing the native client does not intentionally stop the agent. Reconnect by fetching `session.history` and then listening for new notifications.

### Development checks

The backend currently uses development-time `Base.metadata.create_all`. Add Alembic before production migrations.

```sh
PYTHONPATH=. .venv/bin/pytest -q tests
.venv/bin/ruff check main.py settings.py event_broker.py agent_runtime.py database
```
