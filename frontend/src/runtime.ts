export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting'
export type SessionStatus = 'idle' | 'running' | 'stopping' | 'completed' | 'failed' | 'cancelled'
export type RunStatus = 'queued' | Exclude<SessionStatus, 'idle'>
export type MessageRole = 'user' | 'assistant'

export type Workspace = { id: number; path: string; name: string; created_at?: string | null }
export type GitStatus = { is_repository: boolean; is_root: boolean; branch: string | null; dirty_count: number; staged_count: number; unstaged_count: number }
export type Session = { id: number; workspace_id: number; provider: 'codex'; status: SessionStatus; title?: string | null; created_at?: string | null; updated_at?: string | null }
export type Run = { id: number; session_id: number; status: RunStatus; prompt: string; pid: number | null; return_code: number | null; error: string | null; created_at: string; started_at: string | null; completed_at: string | null }
export type Message = { role: MessageRole; content: string; run_id?: number | null }
export type StoredMessage = Message & { id: number; run_id: number | null; created_at: string }
export type ActivityEvent = { id?: number; run_id?: number | null; type: string; payload: { content?: string; [key: string]: unknown }; sequence?: number; created_at?: string }
export type StoredActivityEvent = ActivityEvent & { id: number; run_id: number | null; sequence: number; created_at: string }
export type SessionHistory = { session: Session; conversation: StoredMessage[]; events: StoredActivityEvent[]; last_sequence: number; has_more: boolean }
export type CodebaseMap = { nodes: { id: string; label: string; summary: string; files: string[] }[]; edges: { source: string; target: string; label: string }[] }
export type RunDiffFile = { path: string; status: 'added' | 'modified' | 'deleted'; added: number; deleted: number; patch: string; note: string | null; final_hash: string | null }
export type RunDiff = { run_id: number; status: 'capturing' | 'ready' | 'unavailable'; final: boolean; reason: string | null; files: RunDiffFile[]; file_count: number; added: number; deleted: number; captured_at: string | null; stale: boolean | null; decision?: 'accepted' | 'reverted' | null; can_revert?: boolean }
export type EvalCaseRevision = { id: number; case_id: number; revision: number; status: 'draft' | 'published'; content_hash: string | null; workspace_id: number; source_run_id: number | null; starting_patch_artifact_id: number | null; verifier_artifact_id: number | null; base_sha: string | null; prompt: string; setup_spec: Record<string, unknown>[]; scorer_spec: Record<string, unknown>[]; path_policy: Record<string, unknown>; validation_status: 'not_validated' | 'valid' | 'invalid'; validation_details: Record<string, unknown>; published_at: string | null; created_at: string }
export type EvalCase = { id: number; title: string; description: string; created_at: string; updated_at: string; latest_revision: EvalCaseRevision }
export type EvalSuite = { id: number; name: string; description: string; created_at: string; updated_at: string; latest_version: { id: number; version: number; status: 'draft' | 'frozen'; content_hash: string | null; frozen_at: string | null; cases: { case_id: number; title: string; revision_id: number; revision: number; ordinal: number }[] } }
export type EvalConfig = { id: number; name: string; description: string; created_at: string; snapshot: { id: number; content_hash: string; model: string | null; reasoning_effort: string | null; instructions: Record<string, unknown>[]; codex_config: Record<string, unknown>; sandbox_policy: Record<string, unknown>; cli_version: string | null; uncontrolled_inputs: Record<string, unknown>[]; created_at: string } }
export type EvalAttemptSummary = { id: number; case_revision_id: number; config_snapshot_id: number; sample_index: number; retry_index: number; run_id: number | null; status: string; outcome: string | null; failure_category: string | null; setup_duration_ms: number | null; agent_duration_ms: number | null; scoring_duration_ms: number | null; input_tokens: number | null; cached_input_tokens: number | null; output_tokens: number | null; reasoning_output_tokens: number | null }
export type EvalResults = { configurations: { config_snapshot_id: number; passed: number; failed: number; infrastructure_errors: number; evaluable: number; pass_rate: number | null; confidence_low: number | null; confidence_high: number | null }[]; paired: { a_only_pass: number; b_only_pass: number; both_pass: number; both_fail: number }; verdict: 'inconclusive' | 'configuration_a_better' | 'configuration_b_better' }
export type EvalExperiment = { id: number; name: string; suite_version_id: number; status: 'ready' | 'running' | 'completed' | 'cancelled' | 'failed'; samples_per_case: number; concurrency: number; timeout_seconds: number; config_snapshot_ids: number[]; configurations: { snapshot_id: number; name: string }[]; attempt_count: number; attempt_status_counts: Record<string, number>; attempts: EvalAttemptSummary[]; results: EvalResults; created_at: string; started_at: string | null; completed_at: string | null }
export type EvalStep = { sequence: number; source_event_start_id: number; source_event_end_id: number; source_item_id: string | null; kind: string; title: string; status: string; duration_ms: number | null; signature: string; flags: string[]; summary: string; normalizer_version: number }
export type EvalAttemptEvent = { id: number; type: string; payload: Record<string, unknown>; created_at: string }
export type EvalAttemptDetail = { id: number; experiment_id: number; case: { id: number; title: string } | null; case_revision_id: number; configuration: { snapshot_id: number; name: string; model: string | null; reasoning_effort: string | null } | null; sample_index: number; retry_index: number; run_id: number | null; status: string; outcome: string | null; failure_category: string | null; durations_ms: { setup: number | null; agent: number | null; scoring: number | null }; tokens: { input: number | null; cached_input: number | null; output: number | null; reasoning_output: number | null }; scores: { key: string; required: boolean; passed: boolean | null; value: Record<string, unknown>; summary: string; evidence: Record<string, unknown> }[]; diff: RunDiff | null; artifacts: { id: number; type: string; sha256: string; byte_size: number; metadata: Record<string, unknown> }[] }
export type EvalPreflight = { case_count: number; config_count: number; samples_per_case: number; attempt_count: number; repositories: string[]; invalid_case_revision_ids: number[]; configuration_differences: string[]; warnings: string[]; isolation: string; network_enabled: boolean }
export type RpcResponse<T> = { jsonrpc: '2.0'; id: number | string | null; result?: T; error?: { code: number; message: string; data?: unknown } }

type EventHandler = (event: ActivityEvent & { session_id: number }) => void

export class RpcClient {
  private socket: WebSocket | null = null
  private requestId = 0
  private pending = new Map<number, { resolve: (value: unknown) => void; reject: (reason: Error) => void }>()
  private eventHandler: EventHandler | null = null
  private statusHandler: ((status: ConnectionStatus) => void) | null = null
  private reconnectTimer: number | undefined
  private endpoint = 'ws://127.0.0.1:8000/ws'
  private token = ''
  private intentionallyClosed = false

  async connect(connection?: { url: string; token: string }) {
    if (connection) {
      const endpoint = new URL('/ws', connection.url)
      endpoint.protocol = endpoint.protocol === 'https:' ? 'wss:' : 'ws:'
      this.endpoint = endpoint.toString()
      this.token = connection.token
    }
    this.intentionallyClosed = false
    if (this.socket && this.socket.readyState === WebSocket.OPEN) return
    if (this.socket && this.socket.readyState !== WebSocket.CLOSED) this.socket.close()
    this.statusHandler?.('connecting')
    return new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(this.endpoint, ['agent-workbench', `auth.${this.token}`])
      this.socket = socket
      socket.onopen = () => { this.statusHandler?.('connected'); resolve() }
      socket.onmessage = (message) => this.handleMessage(JSON.parse(message.data))
      socket.onerror = () => {
        if (this.socket !== socket) return
        this.statusHandler?.('disconnected')
        reject(new Error('Backend connection failed'))
      }
      socket.onclose = () => {
        if (this.socket !== socket || this.intentionallyClosed) return
        this.socket = null
        this.rejectPending(new Error('Backend connection closed'))
        this.statusHandler?.('reconnecting')
        this.scheduleReconnect()
      }
    })
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = undefined
      this.connect().catch(() => undefined)
    }, 1800)
  }

  private handleMessage(message: RpcResponse<unknown> | { jsonrpc: '2.0'; method: string; params: ActivityEvent & { session_id: number } }) {
    if ('method' in message && message.method === 'session.event') {
      this.eventHandler?.(message.params)
      return
    }
    if (!('id' in message) || typeof message.id !== 'number') return
    const request = this.pending.get(message.id)
    if (!request) return
    this.pending.delete(message.id)
    if (message.error) request.reject(new Error(message.error.message))
    else request.resolve(message.result)
  }

  request<T>(method: string, params: Record<string, unknown> = {}) {
    const id = ++this.requestId
    return new Promise<T>((resolve, reject) => {
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
        this.statusHandler?.('reconnecting')
        this.scheduleReconnect()
        reject(new Error('Backend connection is unavailable'))
        return
      }
      const timeout = window.setTimeout(() => {
        if (!this.pending.delete(id)) return
        reject(new Error(`Backend request timed out: ${method}`))
      }, 15_000)
      this.pending.set(id, {
        resolve: (value) => { window.clearTimeout(timeout); resolve(value as T) },
        reject: (reason) => { window.clearTimeout(timeout); reject(reason) },
      })
      this.socket.send(JSON.stringify({ jsonrpc: '2.0', id, method, params }))
    })
  }

  onEvent(handler: EventHandler) { this.eventHandler = handler }
  onStatus(handler: (status: ConnectionStatus) => void) { this.statusHandler = handler }
  private rejectPending(error: Error) {
    for (const request of this.pending.values()) request.reject(error)
    this.pending.clear()
  }
  close() {
    this.intentionallyClosed = true
    if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer)
    this.reconnectTimer = undefined
    this.rejectPending(new Error('Backend connection closed'))
    this.socket?.close()
    this.socket = null
  }
}

export const isDemoMode = import.meta.env.VITE_APP_MODE === 'demo'
export const rpcClient = isDemoMode ? new DemoRpcClient() : new RpcClient()
import { DemoRpcClient } from './demoRuntime'
