# Agent Workbench

A native desktop control surface for local coding agents. The project includes a FastAPI environment server and an Electron/React client connected over JSON-RPC and WebSocket.

## Components

- `backend/`: FastAPI server, PostgreSQL persistence, background agent runtime, fake local agent
- `frontend/`: Electron and React client
- `docker-compose.yml`: PostgreSQL development service

## Local development

Start PostgreSQL:

```sh
docker compose up -d postgres
```

Start the backend with the subscription-free fake agent:

```sh
cd backend
source .venv/bin/activate
AGENT_MODE=fake fastapi dev main.py
```

Start the frontend:

```sh
npm --prefix frontend run dev
```

The fake agent lets you test the complete prompt and streaming response flow without a Claude Code or Codex subscription.

## Status

This is an early development project. Provider-specific Claude Code and Codex adapters are not included yet; the runtime currently supports a generic command adapter and a deterministic fake adapter.
