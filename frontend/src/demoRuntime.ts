import type { ActivityEvent, ConnectionStatus, EvalExperimentEvent, GitStatus, RunDiff, Session, SessionHistory, Workspace } from './runtime'
import { demoEvalRequest, portfolioRecording } from './demoEvals.ts'
import type { RpcArgs, RpcMethod, RpcResult } from './generated/rpcContract'

type EventHandler = (event: ActivityEvent & { session_id: number }) => void
const timestamp = '2026-10-09T10:00:00Z'
const workspaces: Workspace[] = [
  { id: 1, name: 'Synthetic web example', path: '/demo/example', created_at: timestamp },
  ...portfolioRecording.cases.map(evalCase => ({
    id: evalCase.latest_revision!.workspace_id, name: evalCase.title,
    path: `/recordings/case-${evalCase.id}`, created_at: timestamp,
  })),
]
const sessions: Session[] = [
  { id: 101, workspace_id: 1, provider: 'codex', status: 'completed', title: 'Explain this sample project', created_at: timestamp, updated_at: timestamp },
  { id: 102, workspace_id: 1, provider: 'codex', status: 'completed', title: 'Review a synthetic source change', created_at: timestamp, updated_at: '2026-10-09T10:01:00Z' },
]
const map = {
  nodes: [
    { id: 'http', label: 'HTTP routes', summary: 'Synthetic request handlers call validation before processing input.', files: ['src/http.ts'] },
    { id: 'validation', label: 'Input validation', summary: 'Synthetic schemas validate and normalize request data.', files: ['src/validation.ts'] },
    { id: 'services', label: 'Application services', summary: 'Synthetic business operations receive validated data.', files: ['src/services.ts'] },
    { id: 'tests', label: 'Regression tests', summary: 'Synthetic checks cover input and response behavior.', files: ['tests/http.test.ts'] },
  ],
  edges: [
    { source: 'http', target: 'validation', label: 'Validate request input.' },
    { source: 'http', target: 'services', label: 'Invoke business operations.' },
    { source: 'tests', target: 'http', label: 'Exercise request behavior.' },
  ],
}
const architectureReply = 'Synthetic demonstration, not a recorded agent run.\n\nHTTP routes validate incoming data, call application services, and return a response. Regression tests check valid and invalid requests. The map illustrates these relationships; all examples are read-only.'
const histories: Record<number, SessionHistory> = {
  101: {
    session: sessions[0], last_sequence: 3, has_more: false,
    conversation: [
      { id: 1, role: 'user', content: 'Explain this sample project.', run_id: 301, created_at: timestamp },
      { id: 2, role: 'assistant', content: architectureReply, run_id: 301, created_at: timestamp },
    ],
    events: [
      { id: 1, run_id: 301, type: 'session.started', payload: { mode: 'map' }, sequence: 1, created_at: timestamp },
      { id: 2, run_id: 301, type: 'artifact.codebase_map', payload: map, sequence: 2, created_at: timestamp },
      { id: 3, run_id: 301, type: 'session.completed', payload: { return_code: 0 }, sequence: 3, created_at: timestamp },
    ],
  },
  102: {
    session: sessions[1], last_sequence: 6, has_more: false,
    conversation: [
      { id: 3, role: 'user', content: 'Show a sample change for the review interface.', run_id: 302, created_at: timestamp },
      { id: 4, role: 'assistant', content: 'Synthetic demonstration: one comment added to src/http.ts. No real files or model runs were involved.', run_id: 302, created_at: timestamp },
    ],
    events: [
      { id: 4, run_id: 302, type: 'session.started', payload: { mode: 'chat' }, sequence: 4, created_at: timestamp },
      { id: 5, run_id: 302, type: 'artifact.run_diff', payload: { run_id: 302, status: 'ready', final: true, file_count: 1, added: 1, deleted: 0 }, sequence: 5, created_at: timestamp },
      { id: 6, run_id: 302, type: 'session.completed', payload: { return_code: 0 }, sequence: 6, created_at: timestamp },
    ],
  },
}
const diffs: Record<number, RunDiff> = {
  301: { run_id: 301, status: 'ready', final: true, reason: null, files: [], file_count: 0, added: 0, deleted: 0, captured_at: timestamp, stale: false, decision: null, can_revert: false },
  302: { run_id: 302, status: 'ready', final: true, reason: null, file_count: 1, added: 1, deleted: 0, captured_at: timestamp, stale: false, decision: null, can_revert: false,
    files: [{ path: 'src/http.ts', status: 'modified', added: 1, deleted: 0, note: 'Synthetic read-only example', final_hash: null, patch: '--- a/src/http.ts\n+++ b/src/http.ts\n@@ -1 +1,2 @@\n+// validate inputs before invoking services\n export function handleRequest() {}' }] },
}
const gitStatuses: Record<number, GitStatus> = {
  1: { is_repository: true, is_root: true, branch: 'main', detached: false, dirty_count: 1, staged_count: 0, unstaged_count: 1, files: [{ path: 'src/http.ts', original_path: null, status: ' M', staged: false, unstaged: true }], remotes: ['origin'], index_token: null },
}

function copyHistory(history: SessionHistory, afterSequence: number): SessionHistory {
  const copy = structuredClone(history)
  copy.conversation = afterSequence ? [] : copy.conversation
  copy.events = copy.events.filter(event => event.sequence > afterSequence)
  return copy
}
function catalogPage<T extends { id: number }>(records: T[], params: Record<string, unknown>): T[] {
  const page = params.before_id == null ? [...records] : records
    .filter(row => !params.before_id || row.id < Number(params.before_id)).sort((a, b) => b.id - a.id)
  return page.slice(0, Number(params.limit ?? 500)).map(row => ({ ...row }))
}
export class DemoRpcClient {
  private statusHandler: ((status: ConnectionStatus) => void) | null = null
  async connect() { this.statusHandler?.('connected') }
  onEvent(_handler: EventHandler) { /* Synthetic sessions do not emit live events. */ }
  onExperimentEvent(_handler: ((event: EvalExperimentEvent) => void) | null) { /* Static demo. */ }
  onStatus(handler: (status: ConnectionStatus) => void) { this.statusHandler = handler }
  close() { /* No live connection. */ }
  async request<M extends RpcMethod>(method: M, ...args: RpcArgs<M>): Promise<RpcResult<M>> {
    const params: Record<string, unknown> = args[0] ?? {}
    let result: unknown
    if (method.startsWith('eval.')) result = demoEvalRequest(method, params)
    else if (method === 'workspace.list') result = catalogPage(workspaces, params)
    else if (method === 'session.list') result = catalogPage(sessions.filter(session => params.workspace_id == null || session.workspace_id === params.workspace_id), params)
    else if (method === 'session.subscribe' || method === 'session.unsubscribe') result = { session_id: Number(params.session_id), subscribed: method === 'session.subscribe' }
    else if (method === 'session.history') {
      const history = histories[Number(params.session_id)]
      if (!history) throw new Error('Synthetic session not found')
      result = copyHistory(history, Number(params.after_sequence ?? 0))
    } else if (method === 'workspace.git_status') result = structuredClone(gitStatuses[Number(params.workspace_id)])
    else if (method === 'run.diff.get') {
      const diff = diffs[Number(params.run_id)]
      if (!diff) throw new Error('Synthetic diff not found')
      result = structuredClone(diff)
    } else throw new Error('not available in demo version')
    return result as RpcResult<M>
  }
}
