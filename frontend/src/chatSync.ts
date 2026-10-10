import type { ActivityEvent, Message, SessionHistory, SessionStatus } from './runtime'

export type ChatSnapshot = { sessionId: number; generation: number; sequence: number; messages: Message[]; events: ActivityEvent[] }
export type SessionTicket = { sessionId: number; generation: number }
export type HistoryTicket = SessionTicket & { request: number; afterSequence: number }
type HistoryRequest = (sessionId: number, afterSequence: number) => Promise<SessionHistory>

export class LatestRequest {
  private version = 0
  begin = () => ++this.version
  invalidate = () => { this.version++ }
  matches = (version: number) => this.version === version
}

export async function fetchFullHistory(request: HistoryRequest, sessionId: number, afterSequence = 0): Promise<SessionHistory> {
  const first = await request(sessionId, afterSequence)
  const history = { ...first, events: [...first.events], conversation: [...first.conversation] }
  while (history.has_more) {
    const page = await request(sessionId, history.last_sequence)
    if (page.last_sequence <= history.last_sequence) throw new Error('Session history did not advance')
    history.events.push(...page.events)
    history.last_sequence = page.last_sequence
    history.has_more = page.has_more
    // Every page returns the complete conversation; keep its latest snapshot.
    history.conversation = [...page.conversation]
    history.session = page.session
  }
  return history
}

function eventKey(event: ActivityEvent): string {
  return event.sequence != null ? `sequence:${event.sequence}` : event.id != null ? `id:${event.id}` : JSON.stringify(event)
}

function mergeEvents(...groups: ActivityEvent[][]): ActivityEvent[] {
  const unique = new Map<string, ActivityEvent>()
  for (const event of groups.flat()) unique.set(eventKey(event), event)
  return [...unique.values()].sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0))
}

function messageKey(message: Message): string {
  return JSON.stringify([message.role, message.run_id, message.content])
}

export function eventStatus(event: ActivityEvent): SessionStatus | null {
  if (!event.type.startsWith('session.')) return null
  if (event.type === 'session.started') return 'running'
  const status = event.type.replace(/^session\./, '')
  return ['running', 'stopping', 'completed', 'failed', 'cancelled'].includes(status) ? status as SessionStatus : null
}

// React-independent external store: selection, live events, and history share
// one synchronous snapshot, so a session switch takes effect before any await.
export class ChatSyncStore {
  private snapshot: ChatSnapshot = { sessionId: 0, generation: 0, sequence: 0, messages: [], events: [] }
  private historyRequest = 0
  private listeners = new Set<() => void>()
  getSnapshot = () => this.snapshot
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  private publish(snapshot: ChatSnapshot) { this.snapshot = snapshot; for (const listener of this.listeners) listener() }
  capture = (): SessionTicket => ({ sessionId: this.snapshot.sessionId, generation: this.snapshot.generation })
  matches = (ticket: SessionTicket) => ticket.sessionId === this.snapshot.sessionId && ticket.generation === this.snapshot.generation
  select = (sessionId: number) => {
    this.historyRequest++
    this.publish({ sessionId, generation: this.snapshot.generation + 1, sequence: 0, messages: [], events: [] })
  }
  beginHistory = (full = false): HistoryTicket => ({ ...this.capture(), request: ++this.historyRequest, afterSequence: full ? 0 : this.snapshot.sequence })
  isCurrentHistory = (ticket: HistoryTicket) => this.matches(ticket) && ticket.request === this.historyRequest
  cancelHistory = (ticket: HistoryTicket) => { if (this.isCurrentHistory(ticket)) this.historyRequest++ }
  receive = (event: ActivityEvent & { session_id: number }): boolean => {
    if (event.session_id !== this.snapshot.sessionId || this.snapshot.events.some(item => eventKey(item) === eventKey(event))) return false
    const messages = [...this.snapshot.messages]
    if (event.type === 'assistant.text' && typeof event.payload.content === 'string') {
      messages.push({ role: 'assistant', content: event.payload.content, run_id: event.run_id })
    }
    this.publish({ ...this.snapshot, events: mergeEvents(this.snapshot.events, [event]), messages,
      sequence: Math.max(this.snapshot.sequence, event.sequence ?? 0) })
    return true
  }
  addUser = (ticket: SessionTicket, content: string, runId: number): boolean => {
    if (!this.matches(ticket)) return false
    const message: Message = { role: 'user', content, run_id: runId }
    if (this.snapshot.messages.some(item => messageKey(item) === messageKey(message))) return true
    const messages = [...this.snapshot.messages]
    const first = messages.findIndex(item => item.run_id === runId)
    messages.splice(first < 0 ? messages.length : first, 0, message)
    this.publish({ ...this.snapshot, messages })
    return true
  }
  applyHistory = (ticket: HistoryTicket, history: SessionHistory): boolean => {
    if (!this.isCurrentHistory(ticket) || history.session.id !== ticket.sessionId) return false
    const events = mergeEvents(history.events, this.snapshot.events)
    const messages: Message[] = [...history.conversation]
    const remaining = new Map<string, number>()
    for (const message of messages) remaining.set(messageKey(message), (remaining.get(messageKey(message)) ?? 0) + 1)
    // Preserve assistant events not represented by the conversation snapshot,
    // including events arriving between the backend's message/event queries.
    for (const event of events) {
      if (event.type !== 'assistant.text' || typeof event.payload.content !== 'string') continue
      const message: Message = { role: 'assistant', content: event.payload.content, run_id: event.run_id }
      const key = messageKey(message)
      const count = remaining.get(key) ?? 0
      if (count) remaining.set(key, count - 1)
      else messages.push(message)
    }
    for (const message of this.snapshot.messages.filter(item => item.role === 'user')) {
      if (!messages.some(item => messageKey(item) === messageKey(message))) messages.push(message)
    }
    // User acknowledgements may arrive after an assistant event; group each
    // run's user message before that run's response without altering run order.
    for (let i = 0; i < messages.length; i++) {
      const message = messages[i]
      if (message.role !== 'user' || message.run_id == null) continue
      const first = messages.findIndex(item => item.run_id === message.run_id)
      if (first < i) { messages.splice(i, 1); messages.splice(first, 0, message) }
    }
    this.publish({ ...this.snapshot, events, messages, sequence: Math.max(this.snapshot.sequence, history.last_sequence) })
    return true
  }
}
