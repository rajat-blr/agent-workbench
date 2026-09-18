# Agent Workbench

A native desktop control surface for Codex. The project contains a FastAPI environment server and an Electron/React client connected over authenticated JSON-RPC and WebSocket.

## Stack

- `backend/`: FastAPI, SQLite, the Codex CLI runtime, and durable run events
- `frontend/`: Electron, React, and TypeScript

PostgreSQL is not required. The Electron launcher stores `agent-workbench.db` in the operating system's application-data directory.

## Prerequisites

- Python 3.14 and `uv`
- Node.js and npm
- The Codex CLI installed and authenticated with `codex login`

## Local development

Install dependencies once:

```sh
cd backend
uv sync --group dev
cd ../frontend
npm install
```

Start the desktop application from the repository root:

```sh
npm --prefix frontend run dev
```

Electron launches the backend, generates a random local authentication token, and passes the token only to the backend and renderer connection. Codex runs once per prompt with JSONL output and the `workspace-write` sandbox.

## Checks

```sh
cd backend
.venv/bin/pytest -q
.venv/bin/ruff check main.py settings.py event_broker.py agent_runtime.py database tests

cd ../frontend
npm run build
npm run lint
```

The desktop packaging/distribution pipeline is not implemented yet.
