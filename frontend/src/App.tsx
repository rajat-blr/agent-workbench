import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity, AlertCircle, ChevronDown, CircleDot, Folder, FolderPlus, GitBranch,
  LoaderCircle, MessageSquarePlus, MoreHorizontal, PanelLeftClose, PanelLeftOpen,
  Pencil, Play, Plus, RefreshCw, Send, Settings2, Square, Terminal, Trash2,
  Wifi, WifiOff, X,
} from 'lucide-react'
import './App.css'
import { rpcClient } from './runtime'
import type { ActivityEvent, ConnectionStatus, Message, Session, SessionHistory, SessionStatus, Workspace } from './runtime'

type GitStatus = { is_repository: boolean; branch: string | null; dirty_count: number }

const demoWorkspace: Workspace = { id: 1, name: 'agent-harness', path: '/Users/you/Documents/agent-harness' }
const demoSession: Session = { id: 1, workspace_id: 1, provider: 'codex', status: 'running' }
const emptyWorkspace: Workspace = { id: 0, name: 'No workspace selected', path: 'Add a workspace to begin' }
const emptySession: Session = { id: 0, workspace_id: 0, provider: 'codex', status: 'idle' }
const demoMessages: Message[] = [
  { role: 'user', content: 'Trace the session lifecycle and show me where reconnect state should live.' },
  { role: 'assistant', content: 'I am mapping the runtime boundary now. The process belongs to the environment server, while this window only holds a resumable client connection.' },
]

function statusLabel(status: ConnectionStatus) {
  return { connected: 'Connected', connecting: 'Connecting', reconnecting: 'Reconnecting', disconnected: 'Offline' }[status]
}

function sessionTone(status: SessionStatus) {
  return status === 'running' ? 'is-running' : status === 'failed' ? 'is-failed' : status === 'completed' ? 'is-complete' : ''
}

function App() {
  const [connection, setConnection] = useState<ConnectionStatus>('connecting')
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace>(demoWorkspace)
  const [activeSession, setActiveSession] = useState<Session>(demoSession)
  const [messages, setMessages] = useState<Message[]>(demoMessages)
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [prompt, setPrompt] = useState('')
  const [showActivity, setShowActivity] = useState(() => localStorage.getItem('showActivity') !== 'false')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('sidebarCollapsed') === 'true')
  const [showSettings, setShowSettings] = useState(false)
  const [showEnvironment, setShowEnvironment] = useState(false)
  const [workspaceMenuId, setWorkspaceMenuId] = useState<number | null>(null)
  const [sessionMenuId, setSessionMenuId] = useState<number | null>(null)
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [checkingBackend, setCheckingBackend] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const activeSessionId = useRef(activeSession.id)
  const lastSequenceRef = useRef(0)
  const conversationScrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => { activeSessionId.current = activeSession.id }, [activeSession.id])
  useEffect(() => { localStorage.setItem('showActivity', String(showActivity)) }, [showActivity])
  useEffect(() => { localStorage.setItem('sidebarCollapsed', String(sidebarCollapsed)) }, [sidebarCollapsed])

  useEffect(() => {
    const scrollArea = conversationScrollRef.current
    if (!scrollArea) return
    const frame = window.requestAnimationFrame(() => { scrollArea.scrollTop = scrollArea.scrollHeight })
    return () => window.cancelAnimationFrame(frame)
  }, [activeSession.id, messages.length])

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
      } catch { setError('Waiting for the backend connection…') }
    }
    void connect()
    return () => rpcClient.close()
  }, [])

  useEffect(() => {
    if (!live) return
    const loadApplicationState = async () => {
      try {
        const [loadedWorkspaces, loadedSessions] = await Promise.all([
          rpcClient.request<Workspace[]>('workspace.list'),
          rpcClient.request<Session[]>('session.list'),
        ])
        setWorkspaces(loadedWorkspaces)
        setSessions(loadedSessions)
        setError(null)
        const selectedSession = loadedSessions.find((session) => session.id === activeSessionId.current) ?? loadedSessions[0]
        if (selectedSession) {
          if (selectedSession.id !== activeSessionId.current) { lastSequenceRef.current = 0; setMessages([]); setEvents([]) }
          setActiveSession(selectedSession)
          const sessionWorkspace = loadedWorkspaces.find((workspace) => workspace.id === selectedSession.workspace_id)
          if (sessionWorkspace) setActiveWorkspace(sessionWorkspace)
        } else {
          const workspace = loadedWorkspaces[0] ?? emptyWorkspace
          setActiveWorkspace(workspace)
          setActiveSession({ ...emptySession, workspace_id: workspace.id })
          setMessages([]); setEvents([]); lastSequenceRef.current = 0
        }
      } catch { setError('Connected to the backend, but application data could not be loaded.') }
    }
    void loadApplicationState()
  }, [live])

  useEffect(() => {
    if (!live || !activeSession.id || !sessions.some((session) => session.id === activeSession.id)) return
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
  }, [activeSession.id, live, sessions])

  const refreshGitStatus = async (workspace = activeWorkspace) => {
    if (!live || !workspace.id) return
    try {
      setGitStatus(await rpcClient.request<GitStatus>('workspace.git_status', { workspace_id: workspace.id }))
      setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not read Git status.') }
  }

  useEffect(() => {
    setGitStatus(null)
    void refreshGitStatus(activeWorkspace)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorkspace.id, live])

  const selectSession = (session: Session) => {
    const workspace = workspaces.find((item) => item.id === session.workspace_id)
    if (workspace) setActiveWorkspace(workspace)
    lastSequenceRef.current = 0; setMessages([]); setEvents([]); setActiveSession(session); setSessionMenuId(null)
  }

  const selectWorkspace = (workspace: Workspace) => {
    setActiveWorkspace(workspace)
    const firstSession = sessions.find((session) => session.workspace_id === workspace.id)
    if (firstSession) selectSession(firstSession)
    else { setActiveSession({ ...emptySession, workspace_id: workspace.id }); setMessages([]); setEvents([]); lastSequenceRef.current = 0 }
    setWorkspaceMenuId(null)
  }

  const chooseWorkspace = async () => {
    const path = window.desktop ? await window.desktop.selectDirectory() : window.prompt('Workspace path')
    if (!path) return
    try {
      const workspace = await rpcClient.request<Workspace>('workspace.create', { path, name: path.split('/').pop() || 'Workspace' })
      setWorkspaces((current) => [...current, workspace]); selectWorkspace(workspace); setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not add workspace.') }
  }

  const createSession = async () => {
    if (!workspaces.some((workspace) => workspace.id === activeWorkspace.id)) { setError('Add a workspace before creating a session.'); return }
    try {
      const session = await rpcClient.request<Session>('session.create', { workspace_id: activeWorkspace.id, provider: 'codex' })
      setSessions((current) => [session, ...current]); selectSession(session); setError(null)
    } catch { setError('Could not create a session.') }
  }

  const renameWorkspace = async (workspace: Workspace) => {
    const name = window.prompt('Workspace name', workspace.name)?.trim()
    if (!name || name === workspace.name) return
    try {
      const renamed = await rpcClient.request<Workspace>('workspace.rename', { workspace_id: workspace.id, name })
      setWorkspaces((current) => current.map((item) => item.id === renamed.id ? renamed : item))
      if (activeWorkspace.id === renamed.id) setActiveWorkspace(renamed)
      setWorkspaceMenuId(null); setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not rename workspace.') }
  }

  const removeWorkspace = async (workspace: Workspace) => {
    if (!window.confirm(`Remove “${workspace.name}” and its saved sessions? Project files will not be deleted.`)) return
    try {
      await rpcClient.request('workspace.delete', { workspace_id: workspace.id })
      const remainingWorkspaces = workspaces.filter((item) => item.id !== workspace.id)
      const remainingSessions = sessions.filter((session) => session.workspace_id !== workspace.id)
      setWorkspaces(remainingWorkspaces); setSessions(remainingSessions); setWorkspaceMenuId(null)
      const nextWorkspace = remainingWorkspaces[0] ?? emptyWorkspace
      const nextSession = remainingSessions.find((session) => session.workspace_id === nextWorkspace.id)
      setActiveWorkspace(nextWorkspace); setActiveSession(nextSession ?? { ...emptySession, workspace_id: nextWorkspace.id })
      setMessages([]); setEvents([]); lastSequenceRef.current = 0; setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not remove workspace.') }
  }

  const deleteSession = async (session: Session) => {
    if (!window.confirm(`Delete “${session.title || `Session #${session.id}`}” and its history?`)) return
    try {
      await rpcClient.request('session.delete', { session_id: session.id })
      const remaining = sessions.filter((item) => item.id !== session.id)
      setSessions(remaining); setSessionMenuId(null)
      if (session.id === activeSession.id) {
        const next = remaining.find((item) => item.workspace_id === activeWorkspace.id)
        setActiveSession(next ?? { ...emptySession, workspace_id: activeWorkspace.id }); setMessages([]); setEvents([]); lastSequenceRef.current = 0
      }
      setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not delete session.') }
  }

  const sendPrompt = async () => {
    const content = prompt.trim()
    if (!content || !live) return
    if (!sessions.some((session) => session.id === activeSession.id && session.workspace_id === activeWorkspace.id)) { setError('Create or select a session in this workspace before sending a prompt.'); return }
    try {
      await rpcClient.request('session.send', { session_id: activeSession.id, content })
      setPrompt(''); setMessages((current) => [...current, { role: 'user', content }])
      setActiveSession((session) => ({ ...session, status: 'running', title: session.title || content.slice(0, 80) }))
      setSessions((current) => current.map((session) => session.id === activeSession.id ? { ...session, status: 'running', title: session.title || content.slice(0, 80) } : session))
      setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'The prompt could not be sent.') }
  }

  const stopSession = async () => {
    if (!sessions.some((session) => session.id === activeSession.id)) return
    try { await rpcClient.request('session.cancel', { session_id: activeSession.id }); setActiveSession((session) => ({ ...session, status: 'stopping' })) }
    catch { setError('Could not stop the agent.') }
  }

  const syncSession = async () => {
    if (!live || !currentSession.id) return
    setSyncing(true)
    try {
      const history = await rpcClient.request<SessionHistory>('session.history', { session_id: currentSession.id, after_sequence: 0 })
      setMessages(history.conversation); setEvents(history.events); setActiveSession(history.session)
      setSessions((current) => current.map((session) => session.id === history.session.id ? history.session : session))
      lastSequenceRef.current = history.last_sequence; setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not synchronize the session.') }
    finally { setSyncing(false) }
  }

  const checkBackend = async () => {
    setCheckingBackend(true)
    try { await rpcClient.request('health.check'); setError(null) }
    catch { setError('The backend health check failed.') }
    finally { setCheckingBackend(false) }
  }

  const displayedWorkspaces = workspaces.length ? workspaces : live ? [] : [demoWorkspace]
  const displayedSessions = groupedSessions.length ? groupedSessions : live ? [] : [demoSession]
  const gitLabel = !gitStatus ? 'Checking Git…' : !gitStatus.is_repository ? 'Not a Git repository' : `${gitStatus.branch}${gitStatus.dirty_count ? ` · ${gitStatus.dirty_count} changed` : ''}`

  return (
    <main className="app-shell" onClick={() => { setWorkspaceMenuId(null); setSessionMenuId(null) }}>
      <header className="topbar">
        <div className="brand-lockup"><div className="brand-mark">A</div><span>agent workbench</span></div>
        <div className="environment-wrap">
          <button className="environment-select" onClick={(event) => { event.stopPropagation(); setShowEnvironment((value) => !value) }}><span className="environment-dot" /> local environment <ChevronDown size={14} /></button>
          {showEnvironment && <div className="environment-popover" onClick={(event) => event.stopPropagation()}><strong>Local runtime</strong><span><span className={`mini-status ${live ? 'online' : ''}`} /> {statusLabel(connection)}</span><span>{workspaces.length} workspace{workspaces.length === 1 ? '' : 's'} registered</span><button onClick={() => void checkBackend()} disabled={!live || checkingBackend}><RefreshCw size={13} className={checkingBackend ? 'spin' : ''} /> Check connection</button></div>}
        </div>
        <div className="topbar-actions"><button className="icon-button" aria-label="Settings" onClick={(event) => { event.stopPropagation(); setShowSettings(true) }}><Settings2 size={16} /></button><div className={`connection-pill ${connection}`}><span className="connection-dot" /> {statusLabel(connection)}</div></div>
      </header>

      <div className={`workspace-grid ${sidebarCollapsed ? 'sidebar-collapsed' : ''} ${showActivity ? '' : 'activity-hidden'}`}>
        {!sidebarCollapsed && <aside className="sidebar">
          <div className="sidebar-heading"><span>Workspaces</span><button className="icon-button" aria-label="Add workspace" onClick={() => void chooseWorkspace()}><FolderPlus size={16} /></button></div>
          <div className="workspace-list">
            {displayedWorkspaces.map((workspace) => <div className="nav-row-wrap" key={workspace.id}>
              <button className={`workspace-row ${workspace.id === activeWorkspace.id ? 'selected' : ''}`} onClick={() => selectWorkspace(workspace)}><Folder size={15} /><span>{workspace.name}</span></button>
              <button className="row-menu-button" aria-label={`Actions for ${workspace.name}`} disabled={!live} onClick={(event) => { event.stopPropagation(); setWorkspaceMenuId((value) => value === workspace.id ? null : workspace.id) }}><MoreHorizontal size={15} /></button>
              {workspaceMenuId === workspace.id && <div className="row-menu" onClick={(event) => event.stopPropagation()}><button onClick={() => void renameWorkspace(workspace)}><Pencil size={13} /> Rename</button><button className="danger" onClick={() => void removeWorkspace(workspace)}><Trash2 size={13} /> Remove</button></div>}
            </div>)}
            {live && workspaces.length === 0 && <button className="empty-list-action" onClick={() => void chooseWorkspace()}>Add your first workspace</button>}
          </div>
          <div className="sidebar-heading sessions-heading"><span>Sessions</span><button className="icon-button" aria-label="New session" disabled={!activeWorkspace.id} onClick={() => void createSession()}><Plus size={16} /></button></div>
          <div className="session-list">
            {displayedSessions.map((session) => <div className="nav-row-wrap" key={session.id}>
              <button className={`session-row ${session.id === activeSession.id ? 'selected' : ''}`} onClick={() => selectSession(session)}><span className={`session-status ${sessionTone(session.status)}`} /><span className="session-copy"><strong>{session.title || 'New agent session'}</strong><small>{session.provider} · #{String(session.id).padStart(3, '0')}</small></span></button>
              <button className="row-menu-button session-menu-button" aria-label={`Actions for session ${session.id}`} disabled={!live} onClick={(event) => { event.stopPropagation(); setSessionMenuId((value) => value === session.id ? null : session.id) }}><MoreHorizontal size={15} /></button>
              {sessionMenuId === session.id && <div className="row-menu session-menu" onClick={(event) => event.stopPropagation()}><button className="danger" onClick={() => void deleteSession(session)}><Trash2 size={13} /> Delete session</button></div>}
            </div>)}
          </div>
          <div className="sidebar-footer"><button className="footer-link" onClick={() => void refreshGitStatus()} disabled={!activeWorkspace.id}><GitBranch size={15} /><span>{gitLabel}</span><RefreshCw size={13} /></button><button className="footer-link" onClick={() => setSidebarCollapsed(true)}><PanelLeftClose size={15} /> Collapse</button></div>
        </aside>}

        <section className="main-panel">
          <div className="session-header"><div><div className="eyebrow"><span className="live-marker" /> {currentSession.id ? `Session #${String(currentSession.id).padStart(3, '0')}` : 'No active session'}</div><h1>{activeWorkspace.name}</h1><p className="path-line"><Folder size={13} /> {activeWorkspace.path}</p></div><div className="session-controls"><span className={`status-label ${currentSession.status}`}><span className="status-dot" /> {currentSession.status}</span>{currentSession.status === 'running' && <button className="stop-button" onClick={() => void stopSession()}><Square size={13} fill="currentColor" /> Stop</button>}</div></div>
          {error && <div className="notice"><AlertCircle size={15} /><span>{error}</span><button onClick={() => setError(null)} aria-label="Dismiss"><X size={14} /></button></div>}
          <div className="conversation-scroll" ref={conversationScrollRef}><div className="conversation-inner">
            {messages.length === 0 ? <div className="empty-conversation"><div className="empty-icon"><MessageSquarePlus size={22} /></div><h2>{activeWorkspace.id ? 'Start a work session' : 'Add a workspace'}</h2><p>{activeWorkspace.id ? 'Ask Codex to inspect code, make a change, or explain what it finds.' : 'Choose a project folder to begin.'}</p>{!activeWorkspace.id && <button className="primary-action" onClick={() => void chooseWorkspace()}><FolderPlus size={14} /> Add workspace</button>}</div> : messages.map((message, index) => <article className={`message ${message.role}`} key={`${message.role}-${index}`}><div className="message-avatar">{message.role === 'user' ? 'YOU' : 'AI'}</div><div className="message-body"><div className="message-meta">{message.role === 'user' ? 'You' : 'Agent'} <span>{message.role === 'assistant' && '· live output'}</span></div><p>{message.content}</p></div></article>)}
            {showActivity && events.map((event, index) => <div className="activity-row" key={`${event.type}-${event.sequence ?? index}`}><Activity size={14} /><span>{event.type.replaceAll('.', ' ')}</span><code>{event.payload.content || JSON.stringify(event.payload)}</code></div>)}
            {currentSession.status === 'running' && <div className="thinking"><LoaderCircle size={15} className="spin" /> Agent is working <span className="thinking-dots">...</span></div>}
          </div></div>
          <div className="composer-wrap"><div className="composer"><textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendPrompt() } }} placeholder="Ask Codex to work on your code..." rows={2} /><div className="composer-toolbar"><div className="composer-hints"><span><Terminal size={13} /> {activeWorkspace.name}</span><span>Enter to send · Shift+Enter for newline</span></div><button className="send-button" disabled={!prompt.trim() || !live || !currentSession.id || currentSession.status === 'running' || currentSession.status === 'stopping'} onClick={() => void sendPrompt()}>{live ? <Send size={15} /> : <WifiOff size={15} />} {live ? 'Send' : 'Offline'}</button></div></div><div className="composer-note">Codex runs with the workspace-write sandbox. Output is saved to session history.</div></div>
        </section>

        {showActivity && <aside className="activity-panel"><div className="activity-header"><div><span className="eyebrow">Runtime</span><h2>Activity</h2></div><button className="icon-button" aria-label="Hide activity" onClick={() => setShowActivity(false)}><PanelLeftClose size={16} /></button></div><div className="runtime-card"><div className="runtime-card-top"><span className="runtime-icon"><Play size={14} fill="currentColor" /></span><div><strong>{currentSession.provider}</strong><span>background process</span></div><CircleDot size={15} className={currentSession.status === 'running' ? 'pulse-icon' : 'muted-icon'} /></div><div className="runtime-stats"><span><small>STATUS</small>{currentSession.status}</span><span><small>EVENTS</small>{events.length || '—'}</span></div></div><div className="activity-feed"><div className="feed-label">LIVE FEED</div>{events.length === 0 ? <div className="feed-empty"><Wifi size={17} /><p>Waiting for runtime events.</p><small>Agent output will appear here.</small></div> : events.map((event, index) => <div className="feed-item" key={`${event.type}-${event.sequence ?? index}`}><span className="feed-line" /><div><strong>{event.type}</strong><p>{event.payload.content || 'Event received'}</p></div></div>)}</div><div className="panel-bottom"><button className="activity-toggle" disabled={!currentSession.id || syncing} onClick={() => void syncSession()}><RefreshCw size={13} className={syncing ? 'spin' : ''} /> {syncing ? 'Synchronizing…' : 'Sync activity'}</button></div></aside>}
        {sidebarCollapsed && <button className="show-sidebar" onClick={() => setSidebarCollapsed(false)} aria-label="Show sidebar"><PanelLeftOpen size={16} /></button>}
        {!showActivity && <button className="show-activity" onClick={() => setShowActivity(true)} aria-label="Show activity"><Activity size={16} /></button>}
      </div>

      {showSettings && <div className="modal-backdrop" onClick={() => setShowSettings(false)}><section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title" onClick={(event) => event.stopPropagation()}><div className="modal-header"><div><span className="eyebrow">Application</span><h2 id="settings-title">Settings & status</h2></div><button className="icon-button" aria-label="Close settings" onClick={() => setShowSettings(false)}><X size={16} /></button></div><div className="settings-list"><div><span>Backend</span><strong className={live ? 'healthy' : 'unhealthy'}>{statusLabel(connection)}</strong></div><div><span>Agent provider</span><strong>Codex</strong></div><div><span>Database</span><strong>SQLite · local</strong></div><div><span>Sandbox</span><strong>Workspace write</strong></div><div><span>Workspace</span><strong title={activeWorkspace.path}>{activeWorkspace.id ? activeWorkspace.name : 'None'}</strong></div></div><label className="setting-toggle"><input type="checkbox" checked={!sidebarCollapsed} onChange={(event) => setSidebarCollapsed(!event.target.checked)} /> Show workspace sidebar</label><label className="setting-toggle"><input type="checkbox" checked={showActivity} onChange={(event) => setShowActivity(event.target.checked)} /> Show activity panel</label><div className="modal-actions"><button className="secondary-action" disabled={!live || checkingBackend} onClick={() => void checkBackend()}><RefreshCw size={14} className={checkingBackend ? 'spin' : ''} /> Check backend</button><button className="primary-action" onClick={() => setShowSettings(false)}>Done</button></div></section></div>}
    </main>
  )
}

export default App
