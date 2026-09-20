# Agent Workbench

A local-first desktop app for working with Codex in your own codebase. Open a project folder, ask Codex to explain or change it, and review the result in one place.

**[Download v1 for macOS (Apple Silicon)](https://github.com/rajat-blr/agent-workbench/releases/download/v1/Agent.Workbench-0.1.0-arm64.dmg)** · [View the v1 release](https://github.com/rajat-blr/agent-workbench/releases/tag/v1)

## Get started

1. Install the Codex CLI and sign in with `codex login`. The CLI is a prerequisite; it is **not** bundled with the app.
2. Download the v1 DMG, open it, and drag Agent Workbench to Applications.
3. Open the app, add a workspace folder, and start a conversation. A new session is created when you add a workspace.

The v1 download is for **Apple Silicon Macs**. The backend is bundled, so you do not need to install Python, Node.js, or a database to use the DMG. This release has no signing or notarization configuration in the repository, so macOS may warn when opening it.

## What you can do

- Keep separate workspaces and persistent conversations with Codex.
- Follow a concise work summary while Codex runs, without putting every runtime event in the chat.
- Generate an interactive codebase map when asking Codex to explain a project.
- Inspect a readable, per-run Git diff and accept or revert changes made during a run.
- Stage, commit, and push a Git workspace to `main` using explicit controls. Nothing is committed or pushed automatically.

## How it works

Electron runs the desktop UI and starts a bundled FastAPI backend on your machine. The React frontend talks to that backend over an authenticated local WebSocket. The backend launches the **separately installed Codex CLI** for each prompt and stores workspaces, sessions, messages, events, and run diffs in SQLite. No PostgreSQL service or hosted application backend is required.

The SQLite database lives in the operating system's application-data directory, not in this repository. Conversation history is local to that computer; there is no cloud sync or built-in backup/restore yet. Deleting the app's data will delete that history. Codex itself may communicate with OpenAI services through the user's CLI sign-in.

## Develop locally

You need Python 3.14, [`uv`](https://docs.astral.sh/uv/), Node.js, npm, and an installed/authenticated Codex CLI.

```sh
cd backend
uv sync --group dev
cd ../frontend
npm install
cd ..
npm --prefix frontend run dev
```

Electron starts the local backend automatically in development. See [backend/README.md](backend/README.md) for backend configuration and transport details.

## Build a macOS app

From the repository root:

```sh
npm --prefix frontend run make
```

This builds the React frontend, freezes the FastAPI backend with PyInstaller, and creates DMG and ZIP artifacts under `frontend/out/make/`. For an unpacked `.app` instead, run `npm --prefix frontend run package`. Local artifacts are unsigned; public distribution should add signing and notarization.

To run project checks:

```sh
cd backend
.venv/bin/pytest -q
.venv/bin/ruff check main.py settings.py event_broker.py agent_runtime.py codebase_map.py run_diffs.py database tests
cd ../frontend
npm run build
npm run lint
```
