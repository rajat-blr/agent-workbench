import { useEffect, useMemo, useRef, useState } from 'react'
import { Activity, AlertCircle, ChevronDown, CircleDot, Folder, FolderPlus, GitBranch, LoaderCircle, MessageSquarePlus, MoreHorizontal, PanelLeftClose, Play, Plus, Send, Settings2, Square, Terminal, Wifi, WifiOff, X } from 'lucide-react'
import './App.css'
import { rpcClient } from './runtime'
import type { ActivityEvent, ConnectionStatus, Message, Session, SessionHistory, SessionStatus, Workspace } from './runtime'

const demoWorkspace: Workspace = { id: 1, name: 'agent-harness', path: '/Users/you/Documents/agent-harness' }
const demoSession: Session = { id: 1, workspace_id: 1, provider: 'codex', status: 'running' }
const emptyWorkspace: Workspace = { id: 0, name: 'No workspace selected', path: 'Add a workspace to begin' }
const emptySession: Session = { id: 0, workspace_id: 0, provider: 'codex', status: 'idle' }
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
  const currentSession = sessions.find((session) => session.id === activeSession.id) ?? activeSession
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
        if (['running', 'stopping', 'completed', 'failed', 'cancelled'].includes(status)) {
          setActiveSession((session) => ({ ...session, status }))
          setSessions((current) => current.map((session) => session.id === event.session_id ? { ...session, status } : session))
        }
      }
    })
    const connect = async () => {
      try {
        const backendConnection = window.desktop
          ? await window.desktop.getBackendConnection()
          : { url: 'http://127.0.0.1:8000', token: import.meta.env.VITE_BACKEND_AUTH_TOKEN || '' }
        await rpcClient.connect(backendConnection)
      } catch {
        setError('Waiting for the backend connection…')
      }
    }
    void connect()
    return () => rpcClient.close()
  }, [])

  useEffect(() => {
    if (!live) return
    const loadApplicationState = async () => {
      try {
        const loadedWorkspaces = await rpcClient.request<Workspace[]>('workspace.list')
        const loadedSessions = await rpcClient.request<Session[]>('session.list')
        setWorkspaces(loadedWorkspaces)
        setSessions(loadedSessions)
        setError(null)
        const selectedSession = loadedSessions.find((session) => session.id === activeSessionId.current) ?? loadedSessions[0]
        if (selectedSession) {
          if (selectedSession.id !== activeSessionId.current) {
            lastSequenceRef.current = 0
            setMessages([])
            setEvents([])
          }
          setActiveSession(selectedSession)
          const sessionWorkspace = loadedWorkspaces.find((workspace) => workspace.id === selectedSession.workspace_id)
          if (sessionWorkspace) setActiveWorkspace(sessionWorkspace)
        } else {
          const workspace = loadedWorkspaces[0] ?? emptyWorkspace
          setActiveWorkspace(workspace)
          setActiveSession({ ...emptySession, workspace_id: workspace.id })
          setMessages([])
          setEvents([])
          lastSequenceRef.current = 0
        }
      } catch { setError('Connected to the backend, but application data could not be loaded.') }
    }
    void loadApplicationState()
  }, [live])

  useEffect(() => {
    if (!live || !sessions.length) return
    const reconcile = async () => {
      const afterSequence = lastSequenceRef.current
      try {
        await rpcClient.request('session.subscribe', { session_id: activeSession.id })
        const history = await rpcClient.request<SessionHistory>('session.history', { session_id: activeSession.id, after_sequence: afterSequence })
        setMessages(history.conversation)
        setEvents((current) => afterSequence === 0 ? history.events : [...current, ...history.events.filter((event) => !current.some((item) => item.sequence === event.sequence))])
        lastSequenceRef.current = Math.max(lastSequenceRef.current, history.last_sequence)
      } catch { setError('The session could not be synchronized.') }
    }
    void reconcile()
    return () => { void rpcClient.request('session.unsubscribe', { session_id: activeSession.id }).catch(() => undefined) }
  }, [connection, activeSession.id, sessions.length, live])

  const selectSession = (session: Session) => {
    const workspace = workspaces.find((item) => item.id === session.workspace_id)
    if (workspace) setActiveWorkspace(workspace)
    lastSequenceRef.current = 0
    setMessages([])
    setEvents([])
    setActiveSession(session)
  }

  const selectWorkspace = (workspace: Workspace) => {
    setActiveWorkspace(workspace)
    const firstSession = sessions.find((session) => session.workspace_id === workspace.id)
    if (firstSession) selectSession(firstSession)
    else {
      setActiveSession({ ...emptySession, workspace_id: workspace.id })
      setMessages([])
      setEvents([])
      lastSequenceRef.current = 0
    }
  }

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
    if (!workspaces.some((workspace) => workspace.id === activeWorkspace.id)) {
      setError('Add a workspace before creating a session.')
      return
    }
    try {
      const session = await rpcClient.request<Session>('session.create', { workspace_id: activeWorkspace.id, provider: 'codex' })
      setSessions((current) => [session, ...current]); selectSession(session); setError(null)
    } catch { setError('Could not create a session.') }
  }
  const sendPrompt = async () => {
    const content = prompt.trim()
    if (!content || !live) return
    if (!sessions.some((session) => session.id === activeSession.id && session.workspace_id === activeWorkspace.id)) {
      setError('Create or select a session in this workspace before sending a prompt.')
      return
    }
    try {
      await rpcClient.request('session.send', { session_id: activeSession.id, content })
      setPrompt(''); setMessages((current) => [...current, { role: 'user', content }]); setActiveSession((session) => ({ ...session, status: 'running' })); setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'The prompt could not be sent.') }
  }
  const stopSession = async () => {
    if (!sessions.some((session) => session.id === activeSession.id)) return
    try { await rpcClient.request('session.cancel', { session_id: activeSession.id }) } catch { setError('Could not stop the agent.') }
  }

  return (
    <main className="app-shell">
      <header className="topbar"><div className="brand-lockup"><div className="brand-mark">A</div><span>agent workbench</span></div><div className="environment-select"><span className="environment-dot" /> local environment <ChevronDown size={14} /></div><div className="topbar-actions"><button className="icon-button" aria-label="Settings"><Settings2 size={16} /></button><div className={`connection-pill ${connection}`}><span className="connection-dot" /> {statusLabel(connection)}</div></div></header>
      <div className="workspace-grid">
        <aside className="sidebar"><div className="sidebar-heading"><span>Workspaces</span><button className="icon-button" aria-label="Add workspace" onClick={chooseWorkspace}><FolderPlus size={16} /></button></div><div className="workspace-list">{(workspaces.length ? workspaces : connection === 'connected' ? [] : [demoWorkspace]).map((workspace) => <button className={`workspace-row ${workspace.id === activeWorkspace.id ? 'selected' : ''}`} key={workspace.id} onClick={() => selectWorkspace(workspace)}><Folder size={15} /><span>{workspace.name}</span><MoreHorizontal size={15} className="muted-icon" /></button>)}</div><div className="sidebar-heading sessions-heading"><span>Sessions</span><button className="icon-button" aria-label="New session" onClick={createSession}><Plus size={16} /></button></div><div className="session-list">{(groupedSessions.length ? groupedSessions : connection === 'connected' ? [] : [demoSession]).map((session) => <button className={`session-row ${session.id === activeSession.id ? 'selected' : ''}`} key={session.id} onClick={() => selectSession(session)}><span className={`session-status ${sessionTone(session.status)}`} /><span className="session-copy"><strong>{session.status === 'running' ? 'Tracing runtime state' : session.title || 'New agent session'}</strong><small>{session.provider} · #{String(session.id).padStart(3, '0')}</small></span></button>)}</div><div className="sidebar-footer"><button className="footer-link"><GitBranch size={15} /> main <ChevronDown size={13} /></button><button className="footer-link"><PanelLeftClose size={15} /> Collapse</button></div></aside>
        <section className="main-panel"><div className="session-header"><div><div className="eyebrow"><span className="live-marker" /> {currentSession.id ? `Session #${String(currentSession.id).padStart(3, '0')}` : 'No active session'}</div><h1>{activeWorkspace.name}</h1><p className="path-line"><Folder size={13} /> {activeWorkspace.path}</p></div><div className="session-controls"><span className={`status-label ${currentSession.status}`}><span className="status-dot" /> {currentSession.status}</span>{currentSession.status === 'running' && <button className="stop-button" onClick={stopSession}><Square size={13} fill="currentColor" /> Stop</button>}</div></div>{error && <div className="notice"><AlertCircle size={15} /><span>{error}</span><button onClick={() => setError(null)} aria-label="Dismiss"><X size={14} /></button></div>}<div className="conversation-scroll"><div className="conversation-inner">{messages.length === 0 ? <div className="empty-conversation"><div className="empty-icon"><MessageSquarePlus size={22} /></div><h2>Start a work session</h2><p>Ask the agent to inspect code, make a change, or explain what it finds.</p></div> : messages.map((message, index) => <article className={`message ${message.role}`} key={`${message.role}-${index}`}><div className="message-avatar">{message.role === 'user' ? 'YOU' : 'AI'}</div><div className="message-body"><div className="message-meta">{message.role === 'user' ? 'You' : 'Agent'} <span>{message.role === 'assistant' && '· live output'}</span></div><p>{message.content}</p></div></article>)}{showActivity && events.map((event, index) => <div className="activity-row" key={`${event.type}-${index}`}><Activity size={14} /><span>{event.type.replaceAll('.', ' ')}</span><code>{event.payload.content || JSON.stringify(event.payload)}</code></div>)}{currentSession.status === 'running' && <div className="thinking"><LoaderCircle size={15} className="spin" /> Agent is working <span className="thinking-dots">...</span></div>}</div></div><div className="composer-wrap"><div className="composer"><textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendPrompt() } }} placeholder="Ask the agent to work on your code..." rows={2} /><div className="composer-toolbar"><div className="composer-hints"><span><Terminal size={13} /> {activeWorkspace.name}</span><span>Enter to send · Shift+Enter for newline</span></div><button className="send-button" disabled={!prompt.trim() || !live} onClick={() => void sendPrompt()}>{live ? <Send size={15} /> : <WifiOff size={15} />} {live ? 'Send' : 'Offline'}</button></div></div><div className="composer-note">Codex runs with the workspace-write sandbox. Output is saved to session history.</div></div></section>
        <aside className={`activity-panel ${showActivity ? '' : 'hidden'}`}><div className="activity-header"><div><span className="eyebrow">Runtime</span><h2>Activity</h2></div><button className="icon-button" aria-label="Hide activity" onClick={() => setShowActivity(false)}><PanelLeftClose size={16} /></button></div><div className="runtime-card"><div className="runtime-card-top"><span className="runtime-icon"><Play size={14} fill="currentColor" /></span><div><strong>{currentSession.provider}</strong><span>background process</span></div><CircleDot size={15} className={currentSession.status === 'running' ? 'pulse-icon' : 'muted-icon'} /></div><div className="runtime-stats"><span><small>STATUS</small>{currentSession.status}</span><span><small>EVENTS</small>{events.length || '—'}</span></div></div><div className="activity-feed"><div className="feed-label">LIVE FEED</div>{events.length === 0 ? <div className="feed-empty"><Wifi size={17} /><p>Waiting for runtime events.</p><small>Agent output will appear here.</small></div> : events.map((event, index) => <div className="feed-item" key={`${event.type}-${index}`}><span className="feed-line" /><div><strong>{event.type}</strong><p>{event.payload.content || 'Event received'}</p></div></div>)}</div><div className="panel-bottom"><button className="activity-toggle"><span className="tiny-check">✓</span> Activity synced</button></div></aside>{!showActivity && <button className="show-activity" onClick={() => setShowActivity(true)} aria-label="Show activity"><Activity size={16} /></button>}
      </div>
    </main>
  )
}

export default App
