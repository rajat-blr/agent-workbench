import type { ActivityEvent, ConnectionStatus, EvalExperimentEvent, RpcResponse } from './runtime'
import type { RpcArgs, RpcMethod, RpcResult } from './generated/rpcContract'

type EventHandler = (event: ActivityEvent & { session_id: number }) => void
type ExperimentEventHandler = (event: EvalExperimentEvent) => void

export class RpcClient {
  private socket: WebSocket | null = null
  private requestId = 0
  private pending = new Map<number, { resolve: (value: unknown) => void; reject: (reason: Error) => void }>()
  private eventHandler: EventHandler | null = null
  private experimentEventHandler: ExperimentEventHandler | null = null
  private statusHandler: ((status: ConnectionStatus) => void) | null = null
  private reconnectTimer: number | undefined
  private endpoint = 'ws://127.0.0.1:8000/ws'
  private token = ''
  private intentionallyClosed = false

  async connect(connection?: { url: string; token: string }) {
    const previousEndpoint = this.endpoint
    const previousToken = this.token
    if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer)
    this.reconnectTimer = undefined
    if (connection) {
      const endpoint = new URL('/ws', connection.url)
      endpoint.protocol = endpoint.protocol === 'https:' ? 'wss:' : 'ws:'
      this.endpoint = endpoint.toString()
      this.token = connection.token
    }
    this.intentionallyClosed = false
    if (this.socket && this.socket.readyState === WebSocket.OPEN && this.endpoint === previousEndpoint && this.token === previousToken) return
    if (this.socket && this.socket.readyState !== WebSocket.CLOSED) {
      const previousSocket = this.socket
      this.socket = null
      this.rejectPending(new Error('Backend connection replaced'))
      previousSocket.close()
    }
    this.statusHandler?.('connecting')
    return new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(this.endpoint, ['agent-workbench', `auth.${this.token}`])
      this.socket = socket
      socket.onopen = () => {
        if (this.socket !== socket || this.intentionallyClosed) { reject(new Error('Backend connection superseded')); return }
        this.statusHandler?.('connected'); resolve()
      }
      socket.onmessage = (message) => {
        if (this.socket !== socket || this.intentionallyClosed) return
        try { this.handleMessage(JSON.parse(message.data)) } catch { /* Ignore malformed backend frames. */ }
      }
      socket.onerror = () => {
        if (this.socket !== socket) return
        this.statusHandler?.('disconnected')
        reject(new Error('Backend connection failed'))
      }
      socket.onclose = () => {
        reject(new Error('Backend connection closed'))
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

  private handleMessage(message: RpcResponse<unknown> | { jsonrpc: '2.0'; method: string; params: (ActivityEvent & { session_id: number }) | EvalExperimentEvent }) {
    if ('method' in message && message.method === 'session.event') {
      this.eventHandler?.(message.params as ActivityEvent & { session_id: number })
      return
    }
    if ('method' in message && message.method === 'eval.experiment.event') {
      this.experimentEventHandler?.(message.params as EvalExperimentEvent)
      return
    }
    if (!('id' in message) || typeof message.id !== 'number') return
    const request = this.pending.get(message.id)
    if (!request) return
    this.pending.delete(message.id)
    if (message.error) request.reject(new Error(message.error.message))
    else request.resolve(message.result)
  }

  request<M extends RpcMethod>(method: M, ...args: RpcArgs<M>): Promise<RpcResult<M>> {
    const params = args[0] ?? {}
    const id = ++this.requestId
    return new Promise<RpcResult<M>>((resolve, reject) => {
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
        this.statusHandler?.('reconnecting')
        this.scheduleReconnect()
        reject(new Error('Backend connection is unavailable'))
        return
      }
      const timeout = window.setTimeout(() => {
        if (!this.pending.delete(id)) return
        reject(new Error(`Backend request timed out: ${method}`))
      }, method === 'workspace.clone_github' ? 150_000 : 15_000)
      this.pending.set(id, {
        resolve: (value) => { window.clearTimeout(timeout); resolve(value as RpcResult<M>) },
        reject: (reason) => { window.clearTimeout(timeout); reject(reason) },
      })
      try { this.socket.send(JSON.stringify({ jsonrpc: '2.0', id, method, params })) }
      catch {
        const pending = this.pending.get(id)
        this.pending.delete(id)
        pending?.reject(new Error('Backend request could not be sent'))
      }
    })
  }

  onEvent(handler: EventHandler) { this.eventHandler = handler }
  onExperimentEvent(handler: ExperimentEventHandler | null) { this.experimentEventHandler = handler }
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
