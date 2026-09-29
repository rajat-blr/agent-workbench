import type { ActivityEvent, ConnectionStatus, GitStatus, RunDiff, Session, SessionHistory, StoredActivityEvent, StoredMessage, Workspace } from './runtime'

type EventHandler = (event: ActivityEvent & { session_id: number }) => void

const workspaces: Workspace[] = [
  { id: 1, name: 'T3 Code', path: '/demo/t3-code', created_at: '2026-09-19T12:47:00Z' },
]

const sessions: Session[] = [
  { id: 101, workspace_id: 1, provider: 'codex', status: 'completed', title: 'Explain this codebase and map its main components', created_at: '2026-09-19T12:47:08Z', updated_at: '2026-09-19T12:49:43Z' },
  { id: 102, workspace_id: 1, provider: 'codex', status: 'completed', title: 'Make sample changes to test the review experience', created_at: '2026-09-19T12:50:53Z', updated_at: '2026-09-19T12:51:25Z' },
]

const map = {
  nodes: [
    { id: 'client-apps', label: 'Web and Mobile Clients', summary: 'React and React Native interfaces that render projects, threads, messages, settings, reviews, and runtime controls.', files: ['apps/web/src/main.tsx', 'apps/web/src/AppRoot.tsx', 'apps/mobile/src/App.tsx'] },
    { id: 'desktop-host', label: 'Desktop Host', summary: 'Electron main process that manages native windows, IPC, local backends, SSH, WSL, updates, previews, and secure storage.', files: ['apps/desktop/src/main.ts', 'apps/desktop/src/app/DesktopApp.ts'] },
    { id: 'client-runtime', label: 'Shared Client Runtime', summary: 'Owns environment connections, reconnection policy, RPC sessions, cached projections, and durable subscriptions.', files: ['packages/client-runtime/src/connection/registry.ts', 'packages/client-runtime/src/rpc/client.ts'] },
    { id: 'contracts', label: 'Contracts', summary: 'Defines the typed RPC surface and schemas for commands, events, projections, provider events, messages, turns, and checkpoints.', files: ['packages/contracts/src/rpc.ts', 'packages/contracts/src/orchestration.ts'] },
    { id: 'server-gateway', label: 'Server Gateway', summary: 'Authenticates requests, dispatches commands, and serves projection subscriptions and environment operations.', files: ['apps/server/src/server.ts', 'apps/server/src/ws.ts'] },
    { id: 'orchestration', label: 'Orchestration Engine', summary: 'Serializes commands, applies pure decision logic, projects events into state, and publishes committed domain events.', files: ['apps/server/src/orchestration/Layers/OrchestrationEngine.ts', 'apps/server/src/orchestration/decider.ts'] },
    { id: 'persistence', label: 'SQLite Event Store and Projections', summary: 'Stores the event log, command receipts, query projections, authentication state, settings, and provider session data.', files: ['apps/server/src/persistence/Layers/Sqlite.ts', 'apps/server/src/persistence/Layers/OrchestrationEventStore.ts'] },
    { id: 'reactors', label: 'Side Effect Reactors', summary: 'Consumes committed intent and provider events, invokes external work, and feeds results back through orchestration commands.', files: ['apps/server/src/orchestration/Layers/OrchestrationReactor.ts', 'apps/server/src/orchestration/Layers/ProviderCommandReactor.ts'] },
    { id: 'providers', label: 'Provider Adapters', summary: 'Normalizes configured coding-agent providers behind one session and event interface.', files: ['apps/server/src/provider/Services/ProviderAdapter.ts', 'apps/server/src/provider/Layers/ProviderAdapterRegistry.ts'] },
    { id: 'workspace', label: 'Workspace and Checkpoints', summary: 'Runs environment-local operations and captures, restores, and diffs workspace state through hidden VCS checkpoint refs.', files: ['apps/server/src/checkpointing/CheckpointStore.ts'] },
  ],
  edges: [
    { source: 'client-apps', target: 'client-runtime', label: 'UI reads shared state and issues operations through runtime services.' },
    { source: 'desktop-host', target: 'client-apps', label: 'Electron hosts the web renderer and exposes native capabilities through IPC.' },
    { source: 'desktop-host', target: 'server-gateway', label: 'Can launch and manage a local server backend.' },
    { source: 'client-runtime', target: 'contracts', label: 'Uses shared schemas for typed RPC calls and streams.' },
    { source: 'client-runtime', target: 'server-gateway', label: 'Maintains authenticated sessions with reconnectable subscriptions.' },
    { source: 'server-gateway', target: 'contracts', label: 'Implements and authorizes the shared RPC contract.' },
    { source: 'server-gateway', target: 'orchestration', label: 'Dispatches client commands and subscribes to projections.' },
    { source: 'orchestration', target: 'persistence', label: 'Atomically stores events, projections, and command receipts.' },
    { source: 'orchestration', target: 'reactors', label: 'Publishes committed events that trigger asynchronous work.' },
    { source: 'reactors', target: 'orchestration', label: 'Reports side-effect results as new commands.' },
    { source: 'reactors', target: 'providers', label: 'Starts sessions and turns and answers provider requests.' },
    { source: 'providers', target: 'reactors', label: 'Streams normalized runtime events for durable ingestion.' },
    { source: 'reactors', target: 'workspace', label: 'Captures, restores, and diffs workspace checkpoints around turns.' },
    { source: 'server-gateway', target: 'client-runtime', label: 'Streams shell summaries, thread snapshots, and incremental events.' },
  ],
}

const architectureReply = `T3 Code is a control plane for coding agents. The server runs beside the user's workspace and owns provider processes, filesystem access, terminals, Git operations, credentials, and durable state. Web, desktop, and mobile clients control that environment through authenticated RPC.

Its central design is an event-sourced orchestration loop:

\`\`\`text
Client UI → shared client runtime → authenticated RPC
→ orchestration command → persisted events and projections
→ reactors run side effects → updated projections stream to clients
\`\`\`

## Main components

**Client applications** provide React web, Electron desktop, and React Native mobile interfaces.

**Shared client runtime** owns one connection per environment, manages retries, retains cached projections while offline, and resumes durable subscriptions after reconnecting.

**Contracts** define the typed RPC boundary and schemas for commands, events, projections, provider events, messages, turns, and checkpoints.

**Server gateway** composes HTTP, WebSocket RPC, authentication, persistence, providers, Git, terminals, previews, devices, and remote access.

**Orchestration engine** queues commands. A pure decider validates state and produces domain events, while projectors apply events to queryable state. Events, projections, and command receipts commit in one SQLite transaction.

**Reactors** subscribe to committed events and perform provider, checkpoint, and cleanup work outside the pure decision and database transaction.

**Provider adapters** normalize multiple coding-agent providers behind one interface. Their runtime events are converted back into orchestration commands.

## End-to-end turn flow

1. A user submits a message in a client.
2. The runtime sends a typed orchestration command.
3. The gateway authenticates the method and the engine queues the command.
4. SQLite commits domain events, projections, and a command receipt atomically.
5. Reactors start provider work only after that commit.
6. Provider output returns as normalized runtime events and new commands.
7. The checkpoint reactor captures completed workspace state and computes the turn diff.
8. Scoped subscriptions stream updated projections to interested clients.`

const histories: Record<number, SessionHistory> = {
  101: {
    session: sessions[0],
    conversation: [
      { id: 1, role: 'user', content: 'Explain this codebase and map its main components and data flow.', run_id: 301, created_at: '2026-09-19T12:47:08Z' },
      { id: 2, role: 'assistant', content: architectureReply, run_id: 301, created_at: '2026-09-19T12:49:43Z' },
    ],
    events: [
      { id: 1, run_id: 301, type: 'session.started', payload: { mode: 'map' }, sequence: 1, created_at: '2026-09-19T12:47:08Z' },
      { id: 2, run_id: 301, type: 'artifact.codebase_map', payload: map, sequence: 2, created_at: '2026-09-19T12:49:43Z' },
      { id: 3, run_id: 301, type: 'artifact.run_diff', payload: { run_id: 301, status: 'ready', final: true, file_count: 0, added: 0, deleted: 0 }, sequence: 3, created_at: '2026-09-19T12:49:45Z' },
      { id: 4, run_id: 301, type: 'session.completed', payload: { return_code: 0 }, sequence: 4, created_at: '2026-09-19T12:49:45Z' },
    ],
    last_sequence: 4,
    has_more: false,
  },
  102: {
    session: sessions[1],
    conversation: [
      { id: 3, role: 'user', content: 'Make a few harmless changes so I can test the “changes during this run” review.', run_id: 302, created_at: '2026-09-19T12:50:53Z' },
      { id: 4, role: 'assistant', content: 'I’ll make a few harmless, clearly identifiable source edits without changing runtime behavior, and first check the working tree so I don’t touch existing changes.', run_id: 302, created_at: '2026-09-19T12:51:02Z' },
      { id: 5, role: 'assistant', content: 'Made three harmless comment-only changes:\n\n- `apps/web/src/AppRoot.tsx`\n- `apps/mobile/src/App.tsx`\n- `apps/server/src/cli/server.ts`\n\nResult: **3 files changed, 3 insertions**. `git diff --check` passes.', run_id: 302, created_at: '2026-09-19T12:51:23Z' },
    ],
    events: [
      { id: 5, run_id: 302, type: 'session.started', payload: { mode: 'chat' }, sequence: 5, created_at: '2026-09-19T12:50:53Z' },
      { id: 6, run_id: 302, type: 'codex.item.completed', payload: { item: { type: 'command_execution', command: 'git status --short && git diff --stat', exit_code: 0 } }, sequence: 6, created_at: '2026-09-19T12:51:03Z' },
      { id: 7, run_id: 302, type: 'codex.item.completed', payload: { item: { type: 'file_change', changes: [{ path: 'apps/mobile/src/App.tsx' }, { path: 'apps/server/src/cli/server.ts' }, { path: 'apps/web/src/AppRoot.tsx' }] } }, sequence: 7, created_at: '2026-09-19T12:51:12Z' },
      { id: 8, run_id: 302, type: 'codex.item.completed', payload: { item: { type: 'command_execution', command: 'git diff --check', exit_code: 0 } }, sequence: 8, created_at: '2026-09-19T12:51:18Z' },
      { id: 9, run_id: 302, type: 'artifact.run_diff', payload: { run_id: 302, status: 'ready', final: true, file_count: 3, added: 3, deleted: 0 }, sequence: 9, created_at: '2026-09-19T12:51:25Z' },
      { id: 10, run_id: 302, type: 'session.completed', payload: { return_code: 0 }, sequence: 10, created_at: '2026-09-19T12:51:25Z' },
    ],
    last_sequence: 10,
    has_more: false,
  },
}

const diffs: Record<number, RunDiff> = {
  301: { run_id: 301, status: 'ready', final: true, reason: null, files: [], file_count: 0, added: 0, deleted: 0, captured_at: '2026-09-19T12:49:45Z', stale: false, decision: null, can_revert: false },
  302: {
    run_id: 302, status: 'ready', final: true, reason: null, file_count: 3, added: 3, deleted: 0, captured_at: '2026-09-19T12:51:25Z', stale: false, decision: null, can_revert: true,
    files: [
      { path: 'apps/mobile/src/App.tsx', status: 'modified', added: 1, deleted: 0, note: null, final_hash: null, patch: '--- a/apps/mobile/src/App.tsx\n+++ b/apps/mobile/src/App.tsx\n@@ -69,6 +69,7 @@\n   const { themeAppearance } = useAppearancePreferences();\n   const navigationTheme = useMobileNavigationTheme();\n \n+  // Native navigation and global overlays share the same appearance context.\n   return (\n     <>\n       <SplashScreenCoordinator />' },
      { path: 'apps/server/src/cli/server.ts', status: 'modified', added: 1, deleted: 0, note: null, final_hash: null, patch: '--- a/apps/server/src/cli/server.ts\n+++ b/apps/server/src/cli/server.ts\n@@ -19,6 +19,7 @@\n   });\n \n export const startCommand = Command.make("start", { ...sharedServerCommandFlags }).pipe(\n+  // This is the interactive entry point used by the normal local-server flow.\n   Command.withDescription("Run the server."),\n   Command.withHandler((flags) => runServerCommand(flags)),\n );' },
      { path: 'apps/web/src/AppRoot.tsx', status: 'modified', added: 1, deleted: 0, note: null, final_hash: null, patch: '--- a/apps/web/src/AppRoot.tsx\n+++ b/apps/web/src/AppRoot.tsx\n@@ -12,6 +12,7 @@\n  * share the same atom registry as routed UI.\n  */\n export function AppRoot({ router }: { readonly router: AppRouter }) {\n+  // Keep application-wide hosts mounted beside the router so route changes do not recreate them.\n   return (\n     <AppAtomRegistryProvider>\n       <RouterProvider router={router} />' },
    ],
  },
}

const gitStatuses: Record<number, GitStatus> = {
  1: { is_repository: true, is_root: true, branch: 'main', dirty_count: 3, staged_count: 0, unstaged_count: 3 },
}

function copyHistory(history: SessionHistory, afterSequence: number): SessionHistory {
  const conversation = afterSequence ? [] : history.conversation.map((message) => ({ ...message })) as StoredMessage[]
  const events = history.events.filter((event) => event.sequence > afterSequence).map((event) => ({ ...event, payload: { ...event.payload } })) as StoredActivityEvent[]
  return { ...history, session: { ...history.session }, conversation, events }
}

export class DemoRpcClient {
  private statusHandler: ((status: ConnectionStatus) => void) | null = null

  async connect() { this.statusHandler?.('connected') }
  onEvent(_handler: EventHandler) { /* Recorded sessions do not emit live events. */ }
  onStatus(handler: (status: ConnectionStatus) => void) { this.statusHandler = handler }
  close() { /* Static demo data has no connection to close. */ }

  async request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    let result: unknown
    if (method === 'workspace.list') result = workspaces.map((workspace) => ({ ...workspace }))
    else if (method === 'session.list') result = sessions.map((session) => ({ ...session }))
    else if (method === 'session.subscribe' || method === 'session.unsubscribe') result = { ok: true }
    else if (method === 'session.history') {
      const history = histories[Number(params.session_id)]
      if (!history) throw new Error('Recorded session not found')
      result = copyHistory(history, Number(params.after_sequence ?? 0))
    } else if (method === 'workspace.git_status') result = { ...gitStatuses[Number(params.workspace_id)] }
    else if (method === 'run.diff.get') {
      const diff = diffs[Number(params.run_id)]
      if (!diff) throw new Error('Recorded diff not found')
      result = structuredClone(diff)
    } else throw new Error('not available in demo version')
    return result as T
  }
}
