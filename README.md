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

The Work panel condenses each run into status, changed files, completed checks, and
errors. Expand Technical details to inspect raw events. Use **Map codebase** (or ask
Codex to explain the codebase or architecture) to create a saved, interactive
component map. Map generation is part of that Codex run, so it does not launch a
second agent request. The map only links to files that exist in the workspace.

For Git workspaces, each new run also captures a read-only before/after file diff.
The Work panel offers **Review changes** as files change, and the user prompt in
chat links to that run's saved final review. Pre-existing edits are excluded;
changes made by other processes during the run may still appear. Binary and very
large files are listed without a text preview. Older runs and non-Git folders
have no saved Git diff.

## Checks

```sh
cd backend
.venv/bin/pytest -q
.venv/bin/ruff check main.py settings.py event_broker.py agent_runtime.py codebase_map.py run_diffs.py database tests

cd ../frontend
npm run build
npm run lint
```

The generated development builds are unsigned; public distribution signing is
described below.

## Package for macOS

Create a self-contained local build from the repository root:

```sh
npm --prefix frontend run package
```

The command builds the React renderer, freezes the FastAPI backend with
PyInstaller, and creates an Electron `.app` under `frontend/out/`.

Create distributable ZIP and DMG artifacts with:

```sh
npm --prefix frontend run make
```

These local artifacts are unsigned. Code signing and notarization are required
before distributing the DMG as a trusted public macOS release. Codex CLI remains
a user-installed prerequisite and must already be authenticated on the machine.
