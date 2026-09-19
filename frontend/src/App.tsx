import { useEffect, useMemo, useRef, useState } from 'react'
import { Activity, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import './App.css'
import './refinement.css'
import { AppHeader } from './AppHeader'
import { CodebaseMapView } from './CodebaseMapView'
import { ConversationPane } from './ConversationPane'
import { RunDiffView } from './RunDiffView'
import { SettingsDialog } from './SettingsDialog'
import { WorkPanel } from './WorkPanel'
import { WorkspaceSidebar } from './WorkspaceSidebar'
import { rpcClient } from './runtime'
import type { ActivityEvent, ConnectionStatus, GitStatus, Message, RunDiff, Session, SessionHistory, SessionStatus, Workspace } from './runtime'
import { summarizeWork } from './workSummary'

const emptyWorkspace: Workspace = { id: 0, name: 'No workspace selected', path: 'Add a workspace to begin' }
const emptySession: Session = { id: 0, workspace_id: 0, provider: 'codex', status: 'idle' }

async function fetchFullHistory(sessionId: number, afterSequence = 0): Promise<SessionHistory> {
  const history = await rpcClient.request<SessionHistory>('session.history', { session_id: sessionId, after_sequence: afterSequence, limit: 2000 })
  while (history.has_more) {
    const page = await rpcClient.request<SessionHistory>('session.history', { session_id: sessionId, after_sequence: history.last_sequence, limit: 2000 })
    if (page.last_sequence <= history.last_sequence) throw new Error('Session history did not advance')
    history.events.push(...page.events)
    history.last_sequence = page.last_sequence
    history.has_more = page.has_more
  }
  return history
}

function App() {
  const [connection, setConnection] = useState<ConnectionStatus>('connecting')
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace>(emptyWorkspace)
  const [activeSession, setActiveSession] = useState<Session>(emptySession)
  const [messages, setMessages] = useState<Message[]>([])
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [runDiff, setRunDiff] = useState<RunDiff | null>(null)
  const [reviewDiff, setReviewDiff] = useState<RunDiff | null>(null)
  const [prompt, setPrompt] = useState('')
  const [showActivity, setShowActivity] = useState(() => localStorage.getItem('showActivity') !== 'false')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('sidebarCollapsed') === 'true')
  const [showSettings, setShowSettings] = useState(false)
  const [showMap, setShowMap] = useState(false)
  const [workspaceMenuId, setWorkspaceMenuId] = useState<number | null>(null)
  const [sessionMenuId, setSessionMenuId] = useState<number | null>(null)
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [checkingBackend, setCheckingBackend] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const activeSessionId = useRef(activeSession.id)
  const lastSequenceRef = useRef(0)
  const conversationScrollRef = useRef<HTMLDivElement>(null)
  const diffRefreshTimer = useRef<number | undefined>(undefined)

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
  const workSummary = useMemo(() => summarizeWork(events, currentSession.status), [events, currentSession.status])
  const latestRunId = Math.max(events.reduce((id, event) => Math.max(id, event.run_id ?? 0), 0), messages.reduce((id, message) => Math.max(id, message.run_id ?? 0), 0)) || undefined
  const earlierRunIds = useMemo(() => [...new Set([...messages, ...events].map((item) => item.run_id).filter((id): id is number => id != null && id !== latestRunId))].sort((a, b) => b - a), [messages, events, latestRunId])

  useEffect(() => {
    rpcClient.onStatus(setConnection)
    rpcClient.onEvent((event) => {
      if (event.session_id !== activeSessionId.current) return
      if (event.sequence && event.sequence <= lastSequenceRef.current) return
      if (event.sequence) lastSequenceRef.current = event.sequence
      setEvents((current) => current.some((item) => item.sequence === event.sequence) ? current : [...current, event])
      if (event.type === 'assistant.text' && event.payload.content) setMessages((current) => [...current, { role: 'assistant', content: event.payload.content as string, run_id: event.run_id }])
      if (event.run_id != null && (event.type === 'artifact.run_diff' || event.type === 'codex.item.completed' || event.type === 'session.completed' || event.type === 'session.failed' || event.type === 'session.cancelled')) {
        const sessionId = event.session_id
        const runId = event.run_id
        if (diffRefreshTimer.current) window.clearTimeout(diffRefreshTimer.current)
        diffRefreshTimer.current = window.setTimeout(() => {
          void rpcClient.request<RunDiff>('run.diff.get', { session_id: sessionId, run_id: runId }).then((diff) => { if (activeSessionId.current === sessionId) setRunDiff(diff) }).catch(() => undefined)
        }, event.type === 'artifact.run_diff' ? 0 : 600)
      }
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
    return () => { if (diffRefreshTimer.current) window.clearTimeout(diffRefreshTimer.current); rpcClient.close() }
  }, [])

  useEffect(() => {
    if (!live || !activeSession.id || latestRunId == null) return
    let cancelled = false
    void rpcClient.request<RunDiff>('run.diff.get', { session_id: activeSession.id, run_id: latestRunId }).then((diff) => { if (!cancelled) setRunDiff(diff) }).catch(() => undefined)
    return () => { cancelled = true }
  }, [activeSession.id, latestRunId, live])

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
        const history = await fetchFullHistory(activeSession.id, afterSequence)
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
    if (!workspaces.some((workspace) => workspace.id === activeWorkspace.id)) return
    void refreshGitStatus(activeWorkspace)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorkspace.id, live, workspaces, currentSession.status])

  const selectSession = (session: Session, selectedWorkspace?: Workspace) => {
    const workspace = selectedWorkspace ?? workspaces.find((item) => item.id === session.workspace_id)
    if (workspace) setActiveWorkspace(workspace)
    lastSequenceRef.current = 0; setMessages([]); setEvents([]); setRunDiff(null); setReviewDiff(null); setShowMap(false); setActiveSession(session); setSessionMenuId(null)
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
    let workspace: Workspace
    try {
      workspace = await rpcClient.request<Workspace>('workspace.create', { path, name: path.split('/').pop() || 'Workspace' })
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not add workspace.'); return }
    setWorkspaces((current) => [...current, workspace])
    try {
      const session = await rpcClient.request<Session>('session.create', { workspace_id: workspace.id, provider: 'codex' })
      setSessions((current) => [session, ...current]); selectSession(session, workspace); setError(null)
    } catch (requestError) {
      selectWorkspace(workspace)
      setError(`Workspace added, but its first session could not be created: ${requestError instanceof Error ? requestError.message : 'Unknown error'}`)
    }
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

  const sendPrompt = async (contentOverride?: string, modeOverride?: 'chat' | 'map') => {
    const content = (contentOverride ?? prompt).trim()
    if (!content || !live) return
    if (!sessions.some((session) => session.id === activeSession.id && session.workspace_id === activeWorkspace.id)) { setError('Create or select a session in this workspace before sending a prompt.'); return }
    const mode = modeOverride ?? (/\b(explain|map|diagram)\b.*\b(codebase|architecture|project)\b/i.test(content) ? 'map' : 'chat')
    try {
      const result = await rpcClient.request<{ run_id: number }>('session.send', { session_id: activeSession.id, content, mode })
      if (!contentOverride) setPrompt('')
      setRunDiff(null); setShowMap(false); setMessages((current) => [...current, { role: 'user', content, run_id: result.run_id }])
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
      const history = await fetchFullHistory(currentSession.id)
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

  const revealMapFile = async (file: string) => {
    try {
      if (window.desktop) await window.desktop.revealWorkspaceFile(activeWorkspace.path, file)
      else await navigator.clipboard.writeText(`${activeWorkspace.path}/${file}`)
    } catch { setError('Could not reveal this file.') }
  }

  const openRunDiff = async (runId: number) => {
    try {
      const diff = await rpcClient.request<RunDiff>('run.diff.get', { session_id: activeSession.id, run_id: runId })
      setReviewDiff(diff)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not load the saved diff.') }
  }

  const decideRunDiff = async (runId: number, action: 'accept' | 'revert') => {
    const diff = await rpcClient.request<RunDiff>(`run.diff.${action}`, { session_id: activeSession.id, run_id: runId })
    setReviewDiff(diff)
    setRunDiff((current) => current?.run_id === runId ? diff : current)
    if (action === 'revert') await refreshGitStatus()
  }

  return (
    <main className="app-shell" onClick={() => { setWorkspaceMenuId(null); setSessionMenuId(null) }}>
      <AppHeader connection={connection} onOpenSettings={() => setShowSettings(true)} />

      <div className={`workspace-grid ${sidebarCollapsed ? 'sidebar-collapsed' : ''} ${showActivity ? '' : 'activity-hidden'}`}>
        {!sidebarCollapsed && <WorkspaceSidebar workspaces={workspaces} sessions={groupedSessions} activeWorkspaceId={activeWorkspace.id} activeSessionId={activeSession.id} live={live} workspaceMenuId={workspaceMenuId} sessionMenuId={sessionMenuId} onWorkspaceMenuChange={setWorkspaceMenuId} onSessionMenuChange={setSessionMenuId} onAddWorkspace={() => void chooseWorkspace()} onSelectWorkspace={selectWorkspace} onRenameWorkspace={(workspace) => void renameWorkspace(workspace)} onRemoveWorkspace={(workspace) => void removeWorkspace(workspace)} onCreateSession={() => void createSession()} onSelectSession={selectSession} onDeleteSession={(session) => void deleteSession(session)} onCollapse={() => setSidebarCollapsed(true)} />}

        <ConversationPane workspace={activeWorkspace} session={currentSession} messages={messages} prompt={prompt} live={live} error={error} conversationScrollRef={conversationScrollRef} onPromptChange={setPrompt} onSend={() => void sendPrompt()} onMapCodebase={() => void sendPrompt('Explain this codebase and map its main components and data flow.', 'map')} onStop={() => void stopSession()} onDismissError={() => setError(null)} onAddWorkspace={() => void chooseWorkspace()} />

        {showActivity && <aside className="activity-panel"><div className="activity-header"><div><span className="eyebrow">Session</span><h2>Work</h2></div><button className="icon-button" aria-label="Hide work panel" onClick={() => setShowActivity(false)}><PanelLeftClose size={16} /></button></div><WorkPanel summary={workSummary} status={currentSession.status} onOpenMap={() => setShowMap(true)} diff={runDiff?.run_id === latestRunId ? runDiff : null} earlierRunIds={earlierRunIds} onReviewDiff={(runId) => void openRunDiff(runId)} workspaceId={activeWorkspace.id} gitStatus={gitStatus} gitDisabled={!live || currentSession.status === 'running' || currentSession.status === 'stopping'} onGitChanged={setGitStatus} /></aside>}
        {sidebarCollapsed && <button className="show-sidebar" onClick={() => setSidebarCollapsed(false)} aria-label="Show sidebar"><PanelLeftOpen size={16} /></button>}
        {!showActivity && <button className="show-activity" onClick={() => setShowActivity(true)} aria-label="Show activity"><Activity size={16} /></button>}
      </div>

      {showSettings && <SettingsDialog connection={connection} workspace={activeWorkspace} showSidebar={!sidebarCollapsed} showActivity={showActivity} checkingBackend={checkingBackend} syncing={syncing} canSync={Boolean(currentSession.id) && live} onToggleSidebar={(show) => setSidebarCollapsed(!show)} onToggleActivity={setShowActivity} onCheckBackend={() => void checkBackend()} onSync={() => void syncSession()} onClose={() => setShowSettings(false)} />}
      {showMap && workSummary.map && <CodebaseMapView map={workSummary.map} onClose={() => setShowMap(false)} onOpenFile={(file) => void revealMapFile(file)} />}
      {reviewDiff && <RunDiffView diff={reviewDiff} onClose={() => setReviewDiff(null)} onDecision={(action) => decideRunDiff(reviewDiff.run_id, action)} />}
    </main>
  )
}

export default App
