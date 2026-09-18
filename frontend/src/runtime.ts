export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting'
export type SessionStatus = 'idle' | 'running' | 'stopping' | 'completed' | 'failed' | 'cancelled'

export type Workspace = { id: number; path: string; name: string; created_at?: string | null }
export type Session = { id: number; workspace_id: number; provider: string; status: SessionStatus; created_at?: string | null; updated_at?: string | null }
export type Message = { role: 'user' | 'assistant'; content: string }
export type ActivityEvent = { id?: number; type: string; payload: { content?: string; [key: string]: unknown }; sequence?: number; created_at?: string }
export type SessionHistory = { session: Session; conversation: Message[]; events: ActivityEvent[]; last_sequence: number }
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
  private intentionallyClosed = false

  async connect(httpUrl?: string) {
    if (httpUrl) this.endpoint = httpUrl.replace(/^http/, 'ws') + '/ws'
    this.intentionallyClosed = false
    if (this.socket && this.socket.readyState === WebSocket.OPEN) return
    if (this.socket && this.socket.readyState !== WebSocket.CLOSED) this.socket.close()
    this.statusHandler?.('connecting')
    return new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(this.endpoint)
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
      this.pending.set(id, { resolve: resolve as (value: unknown) => void, reject })
      this.socket.send(JSON.stringify({ jsonrpc: '2.0', id, method, params }))
    })
  }

  onEvent(handler: EventHandler) { this.eventHandler = handler }
  onStatus(handler: (status: ConnectionStatus) => void) { this.statusHandler = handler }
  close() {
    this.intentionallyClosed = true
    this.socket?.close()
    this.socket = null
  }
}

export const rpcClient = new RpcClient()
