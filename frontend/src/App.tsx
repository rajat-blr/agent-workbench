import { useEffect, useMemo, useRef, useState } from 'react'
import { Activity, AlertCircle, ChevronDown, CircleDot, Folder, FolderPlus, GitBranch, LoaderCircle, MessageSquarePlus, MoreHorizontal, PanelLeftClose, Play, Plus, Send, Settings2, Square, Terminal, Wifi, WifiOff, X } from 'lucide-react'
import './App.css'
import { rpcClient } from './runtime'
import type { ActivityEvent, ConnectionStatus, Message, Session, SessionHistory, SessionStatus, Workspace } from './runtime'

const demoWorkspace: Workspace = { id: 1, name: 'agent-harness', path: '/Users/you/Documents/agent-harness' }
const demoSession: Session = { id: 1, workspace_id: 1, provider: 'codex', status: 'running' }
const demoMessages: Message[] = [
  { role: 'user', content: 'Trace the session lifecycle and show me where reconnect state should live.' },
  { role: 'assistant', content: 'I am mapping the runtime boundary now. The process belongs to the environment server, while this window only holds a resumable client connection.' },
]

function statusLabel(status: ConnectionStatus) { return { connected: 'Connected', connecting: 'Connecting', reconnecting: 'Reconnecting', disconnected: 'Offline' }[status] }
function sessionTone(status: SessionStatus) { return status === 'running' ? 'is-running' : status === 'failed' ? 'is-failed' : status === 'completed' ? 'is-complete' : '' }

function App() {
  const [connection, setConnection] = useState<ConnectionStatus>('connecting')
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace>(demoWorkspace)
  const [activeSession, setActiveSession] = useState<Session>(demoSession)
  const [messages, setMessages] = useState<Message[]>(demoMessages)
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [prompt, setPrompt] = useState('')
  const [showActivity, setShowActivity] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const activeSessionId = useRef(activeSession.id)
  const lastSequenceRef = useRef(0)

  useEffect(() => { activeSessionId.current = activeSession.id }, [activeSession.id])

  const live = connection === 'connected'
  const currentSession = { ...(sessions.find((session) => session.id === activeSession.id) ?? activeSession), ...activeSession }
  const groupedSessions = useMemo(() => sessions.filter((session) => session.workspace_id === activeWorkspace.id), [sessions, activeWorkspace.id])

  useEffect(() => {
    rpcClient.onStatus(setConnection)
    rpcClient.onEvent((event) => {
      if (event.session_id !== activeSessionId.current) return
      if (event.sequence && event.sequence <= lastSequenceRef.current) return
      if (event.sequence) lastSequenceRef.current = event.sequence
      setEvents((current) => current.some((item) => item.sequence === event.sequence) ? current : [...current, event])
      if (event.type === 'assistant.text' && event.payload.content) setMessages((current) => [...current, { role: 'assistant', content: event.payload.content as string }])
      if (event.type.startsWith('session.')) {
        const status = event.type.replace('session.', '') as SessionStatus
        if (['running', 'stopping', 'completed', 'failed', 'cancelled'].includes(status)) setActiveSession((session) => ({ ...session, status }))
      }
    })
    const boot = async () => {
      try {
        const backendUrl = window.desktop ? await window.desktop.getBackendUrl() : 'http://127.0.0.1:8000'
        await rpcClient.connect(backendUrl)
        const loadedWorkspaces = await rpcClient.request<Workspace[]>('workspace.list')
        const loadedSessions = await rpcClient.request<Session[]>('session.list')
        setWorkspaces(loadedWorkspaces)
        setSessions(loadedSessions)
        setError(null)
        if (loadedWorkspaces[0]) setActiveWorkspace(loadedWorkspaces[0])
        if (loadedSessions[0]) {
          setActiveSession(loadedSessions[0])
          const history = await rpcClient.request<SessionHistory>('session.history', { session_id: loadedSessions[0].id })
          setMessages(history.conversation)
          setEvents(history.events)
          lastSequenceRef.current = history.last_sequence
        }
      } catch { setConnection('disconnected'); setError('Backend is not running. The interface is in preview mode.') }
    }
    void boot()
    return () => rpcClient.close()
  }, [])

  useEffect(() => {
    if (!live || !sessions.length) return
    const reconcile = async () => {
      try {
        await rpcClient.request('session.subscribe', { session_id: activeSession.id })
        const history = await rpcClient.request<SessionHistory>('session.history', { session_id: activeSession.id, after_sequence: lastSequenceRef.current })
        setMessages(history.conversation)
        setEvents((current) => [...current, ...history.events.filter((event) => !current.some((item) => item.sequence === event.sequence))])
        lastSequenceRef.current = Math.max(lastSequenceRef.current, history.last_sequence)
      } catch { setError('The session could not be synchronized.') }
    }
    void reconcile()
  }, [connection, activeSession.id, sessions.length, live])

  const chooseWorkspace = async () => {
    const path = window.desktop ? await window.desktop.selectDirectory() : window.prompt('Workspace path')
    if (!path) return
    try {
      const workspace = await rpcClient.request<Workspace>('workspace.create', { path, name: path.split('/').pop() || 'Workspace' })
      setWorkspaces((current) => [...current, workspace])
      setActiveWorkspace(workspace)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not add workspace') }
  }
  const createSession = async () => {
    try {
      const session = await rpcClient.request<Session>('session.create', { workspace_id: activeWorkspace.id, provider: 'command' })
      setSessions((current) => [session, ...current]); setActiveSession(session); setMessages([]); setEvents([]); lastSequenceRef.current = 0; setError(null)
    } catch { setError('Could not create a session.') }
  }
  const sendPrompt = async () => {
    const content = prompt.trim()
    if (!content || !live) return
    try {
      await rpcClient.request('session.send', { session_id: activeSession.id, content })
      setPrompt(''); setMessages((current) => [...current, { role: 'user', content }]); setActiveSession((session) => ({ ...session, status: 'running' })); setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'The prompt could not be sent.') }
  }
  const stopSession = async () => { try { await rpcClient.request('session.cancel', { session_id: activeSession.id }) } catch { setError('Could not stop the agent.') } }

  return (
    <main className="app-shell">
      <header className="topbar"><div className="brand-lockup"><div className="brand-mark">A</div><span>agent workbench</span></div><div className="environment-select"><span className="environment-dot" /> local environment <ChevronDown size={14} /></div><div className="topbar-actions"><button className="icon-button" aria-label="Settings"><Settings2 size={16} /></button><div className={`connection-pill ${connection}`}><span className="connection-dot" /> {statusLabel(connection)}</div></div></header>
      <div className="workspace-grid">
        <aside className="sidebar"><div className="sidebar-heading"><span>Workspaces</span><button className="icon-button" aria-label="Add workspace" onClick={chooseWorkspace}><FolderPlus size={16} /></button></div><div className="workspace-list">{(workspaces.length ? workspaces : [demoWorkspace]).map((workspace) => <button className={`workspace-row ${workspace.id === activeWorkspace.id ? 'selected' : ''}`} key={workspace.id} onClick={() => setActiveWorkspace(workspace)}><Folder size={15} /><span>{workspace.name}</span><MoreHorizontal size={15} className="muted-icon" /></button>)}</div><div className="sidebar-heading sessions-heading"><span>Sessions</span><button className="icon-button" aria-label="New session" onClick={createSession}><Plus size={16} /></button></div><div className="session-list">{(groupedSessions.length ? groupedSessions : [demoSession]).map((session) => <button className={`session-row ${session.id === activeSession.id ? 'selected' : ''}`} key={session.id} onClick={() => setActiveSession(session)}><span className={`session-status ${sessionTone(session.status)}`} /><span className="session-copy"><strong>{session.status === 'running' ? 'Tracing runtime state' : 'New agent session'}</strong><small>{session.provider} · #{String(session.id).padStart(3, '0')}</small></span></button>)}</div><div className="sidebar-footer"><button className="footer-link"><GitBranch size={15} /> main <ChevronDown size={13} /></button><button className="footer-link"><PanelLeftClose size={15} /> Collapse</button></div></aside>
        <section className="main-panel"><div className="session-header"><div><div className="eyebrow"><span className="live-marker" /> Session #{String(currentSession.id).padStart(3, '0')}</div><h1>{activeWorkspace.name}</h1><p className="path-line"><Folder size={13} /> {activeWorkspace.path}</p></div><div className="session-controls"><span className={`status-label ${currentSession.status}`}><span className="status-dot" /> {currentSession.status}</span>{currentSession.status === 'running' && <button className="stop-button" onClick={stopSession}><Square size={13} fill="currentColor" /> Stop</button>}</div></div>{error && <div className="notice"><AlertCircle size={15} /><span>{error}</span><button onClick={() => setError(null)} aria-label="Dismiss"><X size={14} /></button></div>}<div className="conversation-scroll"><div className="conversation-inner">{messages.length === 0 ? <div className="empty-conversation"><div className="empty-icon"><MessageSquarePlus size={22} /></div><h2>Start a work session</h2><p>Ask the agent to inspect code, make a change, or explain what it finds.</p></div> : messages.map((message, index) => <article className={`message ${message.role}`} key={`${message.role}-${index}`}><div className="message-avatar">{message.role === 'user' ? 'YOU' : 'AI'}</div><div className="message-body"><div className="message-meta">{message.role === 'user' ? 'You' : 'Agent'} <span>{message.role === 'assistant' && '· live output'}</span></div><p>{message.content}</p></div></article>)}{showActivity && events.map((event, index) => <div className="activity-row" key={`${event.type}-${index}`}><Activity size={14} /><span>{event.type.replaceAll('.', ' ')}</span><code>{event.payload.content || JSON.stringify(event.payload)}</code></div>)}{currentSession.status === 'running' && <div className="thinking"><LoaderCircle size={15} className="spin" /> Agent is working <span className="thinking-dots">...</span></div>}</div></div><div className="composer-wrap"><div className="composer"><textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendPrompt() } }} placeholder="Ask the agent to work on your code..." rows={2} /><div className="composer-toolbar"><div className="composer-hints"><span><Terminal size={13} /> {activeWorkspace.name}</span><span>⌘ ↵ to send</span></div><button className="send-button" disabled={!prompt.trim() || !live} onClick={() => void sendPrompt()}>{live ? <Send size={15} /> : <WifiOff size={15} />} {live ? 'Send' : 'Offline'}</button></div></div><div className="composer-note">Agent access is scoped to the selected workspace. Output is saved to session history.</div></div></section>
        <aside className={`activity-panel ${showActivity ? '' : 'hidden'}`}><div className="activity-header"><div><span className="eyebrow">Runtime</span><h2>Activity</h2></div><button className="icon-button" aria-label="Hide activity" onClick={() => setShowActivity(false)}><PanelLeftClose size={16} /></button></div><div className="runtime-card"><div className="runtime-card-top"><span className="runtime-icon"><Play size={14} fill="currentColor" /></span><div><strong>{currentSession.provider}</strong><span>background process</span></div><CircleDot size={15} className={currentSession.status === 'running' ? 'pulse-icon' : 'muted-icon'} /></div><div className="runtime-stats"><span><small>STATUS</small>{currentSession.status}</span><span><small>EVENTS</small>{events.length || '—'}</span></div></div><div className="activity-feed"><div className="feed-label">LIVE FEED</div>{events.length === 0 ? <div className="feed-empty"><Wifi size={17} /><p>Waiting for runtime events.</p><small>Agent output will appear here.</small></div> : events.map((event, index) => <div className="feed-item" key={`${event.type}-${index}`}><span className="feed-line" /><div><strong>{event.type}</strong><p>{event.payload.content || 'Event received'}</p></div></div>)}</div><div className="panel-bottom"><button className="activity-toggle"><span className="tiny-check">✓</span> Activity synced</button></div></aside>{!showActivity && <button className="show-activity" onClick={() => setShowActivity(true)} aria-label="Show activity"><Activity size={16} /></button>}
      </div>
    </main>
  )
}

export default App
