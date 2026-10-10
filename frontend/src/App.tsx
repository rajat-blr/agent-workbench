import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import './App.css'
import './refinement.css'
import { AppHeader } from './AppHeader'
import { CodebaseMapView } from './CodebaseMapView'
import { ConversationPane } from './ConversationPane'
import { EvalsMode } from './EvalsMode'
import { RunDiffView } from './RunDiffView'
import { SettingsDialog } from './SettingsDialog'
import { WorkPanel } from './WorkPanel'
import { WorkspaceSidebar } from './WorkspaceSidebar'
import { isDemoMode, rpcClient } from './runtime'
import type { ConnectionStatus, GitStatus, RunDiff, Session, Workspace } from './runtime'
import { eventStatus, fetchFullHistory, LatestRequest } from './chatSync'
import { fetchCatalog, sortSessions, sortWorkspaces } from './catalogPagination'
import { useChatSync } from './useChatSync'
import { summarizeWork } from './workSummary'

const emptyWorkspace: Workspace = { id: 0, name: 'No workspace selected', path: 'Add a workspace to begin', created_at: '' }
const emptySession: Session = { id: 0, workspace_id: 0, provider: 'codex', status: 'idle', title: null, created_at: '', updated_at: '' }

const fetchHistory = (sessionId: number, afterSequence = 0) => fetchFullHistory(
  (id, sequence) => rpcClient.request('session.history', { session_id: id, after_sequence: sequence, limit: 2000 }),
  sessionId, afterSequence,
)

function App() {
  const [productMode, setProductMode] = useState<'chat' | 'evals'>(() => isDemoMode || localStorage.getItem('productMode') === 'evals' ? 'evals' : 'chat')
  const [creatingEval, setCreatingEval] = useState(false)
  const [connection, setConnection] = useState<ConnectionStatus>('connecting')
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace>(emptyWorkspace)
  const [activeSession, setActiveSession] = useState<Session>(emptySession)
  const { store, messages, events } = useChatSync()
  const [runDiff, setRunDiff] = useState<RunDiff | null>(null)
  const [reviewDiff, setReviewDiff] = useState<RunDiff | null>(null)
  const [prompt, setPrompt] = useState('')
  const [showActivity, setShowActivity] = useState(() => localStorage.getItem('showActivity') !== 'false')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('sidebarCollapsed') === 'true')
  const [showSettings, setShowSettings] = useState(false)
  const [showMap, setShowMap] = useState(false)
  const [workspaceMenuId, setWorkspaceMenuId] = useState<number | null>(null)
  const [sessionMenuId, setSessionMenuId] = useState<number | null>(null)
  const [gitStatusState, setGitStatusState] = useState<{ workspaceId: number; status: GitStatus } | null>(null)
  const [gitRequests] = useState(() => new LatestRequest())
  const gitStatus = gitStatusState?.workspaceId === activeWorkspace.id ? gitStatusState.status : null
  const setGitStatus = useCallback((status: GitStatus) => {
    gitRequests.invalidate()
    setGitStatusState({ workspaceId: activeWorkspace.id, status })
  }, [activeWorkspace.id, gitRequests])
  const [syncing, setSyncing] = useState(false)
  const [checkingBackend, setCheckingBackend] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showDemoUnavailable, setShowDemoUnavailable] = useState(false)
  const conversationScrollRef = useRef<HTMLDivElement>(null)
  const diffRefreshTimer = useRef<number | undefined>(undefined)
  const unavailableInDemo = () => setShowDemoUnavailable(true)

  useEffect(() => { localStorage.setItem('showActivity', String(showActivity)) }, [showActivity])
  useEffect(() => { localStorage.setItem('sidebarCollapsed', String(sidebarCollapsed)) }, [sidebarCollapsed])
  useEffect(() => { localStorage.setItem('productMode', productMode) }, [productMode])

  useEffect(() => {
    const scrollArea = conversationScrollRef.current
    if (!scrollArea) return
    const frame = window.requestAnimationFrame(() => { scrollArea.scrollTop = scrollArea.scrollHeight })
    return () => window.cancelAnimationFrame(frame)
  }, [activeSession.id, messages.length])

  const live = connection === 'connected'
  const activeSessionExists = sessions.some(session => session.id === activeSession.id)
  const currentSession = sessions.find((session) => session.id === activeSession.id) ?? activeSession
  const groupedSessions = useMemo(() => sessions.filter((session) => session.workspace_id === activeWorkspace.id), [sessions, activeWorkspace.id])
  const workSummary = useMemo(() => summarizeWork(events, currentSession.status), [events, currentSession.status])
  const latestRunId = Math.max(events.reduce((id, event) => Math.max(id, event.run_id ?? 0), 0), messages.reduce((id, message) => Math.max(id, message.run_id ?? 0), 0)) || undefined
  const earlierRunIds = useMemo(() => [...new Set([...messages, ...events].map((item) => item.run_id).filter((id): id is number => id != null && id !== latestRunId))].sort((a, b) => b - a), [messages, events, latestRunId])

  useEffect(() => {
    let cancelled = false
    rpcClient.onStatus(setConnection)
    rpcClient.onEvent((event) => {
      const previousSequence = store.getSnapshot().sequence
      if (!store.receive(event)) return
      if (event.run_id != null && (event.type === 'artifact.run_diff' || event.type === 'codex.item.completed' || event.type === 'session.completed' || event.type === 'session.failed' || event.type === 'session.cancelled')) {
        const sessionId = event.session_id
        const runId = event.run_id
        const ticket = store.capture()
        if (diffRefreshTimer.current) window.clearTimeout(diffRefreshTimer.current)
        diffRefreshTimer.current = window.setTimeout(() => {
          void rpcClient.request('run.diff.get', { session_id: sessionId, run_id: runId }).then((diff) => { if (store.matches(ticket)) setRunDiff(current => current && current.run_id > diff.run_id ? current : diff) }).catch(() => undefined)
        }, event.type === 'artifact.run_diff' ? 0 : 600)
      }
      if (event.type.startsWith('session.')) {
        const status = eventStatus(event)
        if (status && (event.sequence == null || event.sequence >= previousSequence)) {
          setActiveSession((session) => ({ ...session, status }))
          setSessions((current) => current.map((session) => session.id === event.session_id ? { ...session, status } : session))
        }
      }
    })
    const connect = async () => {
      try {
        if (isDemoMode) {
          await rpcClient.connect()
          return
        }
        const backendConnection = window.desktop
          ? await window.desktop.getBackendConnection()
          : { url: 'http://127.0.0.1:8000', token: import.meta.env.VITE_BACKEND_AUTH_TOKEN || '' }
        if (cancelled) return
        await rpcClient.connect(backendConnection)
      } catch { if (!cancelled) setError('Waiting for the backend connection…') }
    }
    void connect()
    return () => { cancelled = true; if (diffRefreshTimer.current) window.clearTimeout(diffRefreshTimer.current); rpcClient.close() }
  }, [store])

  useEffect(() => {
    if (!live || !activeSession.id || latestRunId == null) return
    let cancelled = false
    const ticket = store.capture()
    void rpcClient.request('run.diff.get', { session_id: activeSession.id, run_id: latestRunId }).then((diff) => { if (!cancelled && store.matches(ticket)) setRunDiff(diff) }).catch(() => undefined)
    return () => { cancelled = true }
  }, [activeSession.id, latestRunId, live, store])

  useEffect(() => {
    if (!live) return
    let cancelled = false
    const ticket = store.capture()
    const loadApplicationState = async () => {
      try {
        const [loadedWorkspaces, loadedSessions] = await Promise.all([
          fetchCatalog((params) => rpcClient.request('workspace.list', params), () => !cancelled && store.matches(ticket)).then(sortWorkspaces),
          fetchCatalog((params) => rpcClient.request('session.list', params), () => !cancelled && store.matches(ticket)).then(sortSessions),
        ])
        if (cancelled || !store.matches(ticket)) return
        setWorkspaces(loadedWorkspaces)
        setSessions(loadedSessions)
        setError(null)
        const selectedSession = loadedSessions.find((session) => session.id === store.getSnapshot().sessionId) ?? loadedSessions[0]
        if (selectedSession) {
          if (selectedSession.id !== store.getSnapshot().sessionId) store.select(selectedSession.id)
          setActiveSession(selectedSession)
          const sessionWorkspace = loadedWorkspaces.find((workspace) => workspace.id === selectedSession.workspace_id)
          if (sessionWorkspace) setActiveWorkspace(sessionWorkspace)
        } else {
          const workspace = loadedWorkspaces[0] ?? emptyWorkspace
          setActiveWorkspace(workspace)
          setActiveSession({ ...emptySession, workspace_id: workspace.id })
          store.select(0)
        }
      } catch {
        if (!cancelled && store.matches(ticket)) setError('Connected to the backend, but application data could not be loaded.')
        cancelled = true // Stop the other catalog scan when either request fails.
      }
    }
    void loadApplicationState()
    return () => { cancelled = true }
  }, [live, store])

  useEffect(() => {
    if (!live || !activeSession.id || !activeSessionExists) return
    const ticket = store.beginHistory()
    const reconcile = async () => {
      try {
        await rpcClient.request('session.subscribe', { session_id: activeSession.id })
        if (!store.isCurrentHistory(ticket)) return
        const history = await fetchHistory(activeSession.id, ticket.afterSequence)
        store.applyHistory(ticket, history)
      } catch { if (store.isCurrentHistory(ticket)) setError('The session could not be synchronized.') }
    }
    void reconcile()
    return () => { store.cancelHistory(ticket); void rpcClient.request('session.unsubscribe', { session_id: activeSession.id }).catch(() => undefined) }
  }, [activeSession.id, live, activeSessionExists, store])

  const refreshGitStatus = useCallback(async (workspace: Workspace) => {
    if (!live || !workspace.id) return
    const ticket = store.capture()
    const version = gitRequests.begin()
    try {
      const status = await rpcClient.request('workspace.git_status', { workspace_id: workspace.id })
      if (!store.matches(ticket) || !gitRequests.matches(version)) return
      setGitStatusState({ workspaceId: workspace.id, status })
      setError(null)
    } catch (requestError) { if (store.matches(ticket) && gitRequests.matches(version)) setError(requestError instanceof Error ? requestError.message : 'Could not read Git status.') }
  }, [live, store, gitRequests])

  useEffect(() => {
    if (!workspaces.some((workspace) => workspace.id === activeWorkspace.id)) return
    let cancelled = false
    void Promise.resolve().then(() => { if (!cancelled) void refreshGitStatus(activeWorkspace) })
    return () => { cancelled = true; gitRequests.invalidate() }
  }, [activeWorkspace, live, workspaces, currentSession.status, refreshGitStatus, gitRequests])

  const selectSession = (session: Session, selectedWorkspace?: Workspace) => {
    const workspace = selectedWorkspace ?? workspaces.find((item) => item.id === session.workspace_id)
    if (workspace) setActiveWorkspace(workspace)
    if (store.getSnapshot().sessionId !== session.id) {
      store.select(session.id); setRunDiff(null); setReviewDiff(null); setShowMap(false)
    }
    setActiveSession(session); setSessionMenuId(null)
  }

  const selectWorkspace = (workspace: Workspace) => {
    setActiveWorkspace(workspace)
    const firstSession = sessions.find((session) => session.workspace_id === workspace.id)
    if (firstSession) selectSession(firstSession)
    else { store.select(0); setRunDiff(null); setReviewDiff(null); setShowMap(false); setActiveSession({ ...emptySession, workspace_id: workspace.id }) }
    setWorkspaceMenuId(null)
  }

  const chooseWorkspace = async () => {
    if (isDemoMode) { unavailableInDemo(); return }
    const path = window.desktop ? await window.desktop.selectDirectory() : window.prompt('Workspace path')
    if (!path) return
    let workspace: Workspace
    try {
      workspace = await rpcClient.request('workspace.create', { path, name: path.split('/').pop() || 'Workspace' })
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not add workspace.'); return }
    setWorkspaces((current) => [...current, workspace])
    try {
      const session = await rpcClient.request('session.create', { workspace_id: workspace.id, provider: 'codex' })
      setSessions((current) => [session, ...current]); selectSession(session, workspace); setError(null)
    } catch (requestError) {
      selectWorkspace(workspace)
      setError(`Workspace added, but its first session could not be created: ${requestError instanceof Error ? requestError.message : 'Unknown error'}`)
    }
  }

  const createSession = async () => {
    if (isDemoMode) { unavailableInDemo(); return }
    if (!workspaces.some((workspace) => workspace.id === activeWorkspace.id)) { setError('Add a workspace before creating a session.'); return }
    try {
      const session = await rpcClient.request('session.create', { workspace_id: activeWorkspace.id, provider: 'codex' })
      setSessions((current) => [session, ...current]); selectSession(session); setError(null)
    } catch { setError('Could not create a session.') }
  }

  const renameWorkspace = async (workspace: Workspace) => {
    if (isDemoMode) { unavailableInDemo(); return }
    const name = window.prompt('Workspace name', workspace.name)?.trim()
    if (!name || name === workspace.name) return
    try {
      const renamed = await rpcClient.request('workspace.rename', { workspace_id: workspace.id, name })
      setWorkspaces((current) => current.map((item) => item.id === renamed.id ? renamed : item))
      if (activeWorkspace.id === renamed.id) setActiveWorkspace(renamed)
      setWorkspaceMenuId(null); setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not rename workspace.') }
  }

  const removeWorkspace = async (workspace: Workspace) => {
    if (isDemoMode) { unavailableInDemo(); return }
    if (!window.confirm(`Remove “${workspace.name}” and its saved sessions? Project files will not be deleted.`)) return
    try {
      await rpcClient.request('workspace.delete', { workspace_id: workspace.id })
      const remainingWorkspaces = workspaces.filter((item) => item.id !== workspace.id)
      const remainingSessions = sessions.filter((session) => session.workspace_id !== workspace.id)
      setWorkspaces(remainingWorkspaces); setSessions(remainingSessions); setWorkspaceMenuId(null)
      const nextWorkspace = remainingWorkspaces[0] ?? emptyWorkspace
      const nextSession = remainingSessions.find((session) => session.workspace_id === nextWorkspace.id)
      store.select(nextSession?.id ?? 0); setActiveWorkspace(nextWorkspace); setActiveSession(nextSession ?? { ...emptySession, workspace_id: nextWorkspace.id })
      setRunDiff(null); setReviewDiff(null); setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not remove workspace.') }
  }

  const deleteSession = async (session: Session) => {
    if (isDemoMode) { unavailableInDemo(); return }
    if (!window.confirm(`Delete “${session.title || `Session #${session.id}`}” and its history?`)) return
    try {
      await rpcClient.request('session.delete', { session_id: session.id })
      const remaining = sessions.filter((item) => item.id !== session.id)
      setSessions(remaining); setSessionMenuId(null)
      if (session.id === activeSession.id) {
        const next = remaining.find((item) => item.workspace_id === activeWorkspace.id)
        store.select(next?.id ?? 0); setActiveSession(next ?? { ...emptySession, workspace_id: activeWorkspace.id }); setRunDiff(null); setReviewDiff(null)
      }
      setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not delete session.') }
  }

  const sendPrompt = async (contentOverride?: string, modeOverride?: 'chat' | 'map') => {
    if (isDemoMode) { unavailableInDemo(); return }
    const content = (contentOverride ?? prompt).trim()
    if (!content || !live) return
    if (!sessions.some((session) => session.id === activeSession.id && session.workspace_id === activeWorkspace.id)) { setError('Create or select a session in this workspace before sending a prompt.'); return }
    const mode = modeOverride ?? (/\b(explain|map|diagram)\b.*\b(codebase|architecture|project)\b/i.test(content) ? 'map' : 'chat')
    const ticket = store.capture()
    try {
      const result = await rpcClient.request('session.send', { session_id: activeSession.id, content, mode })
      setSessions((current) => current.map(session => session.id === ticket.sessionId ? { ...session, title: session.title || content.slice(0, 80) } : session))
      if (!store.addUser(ticket, content, result.run_id)) return
      if (!contentOverride) setPrompt(current => current.trim() === content ? '' : current)
      setRunDiff(null); setShowMap(false)
      const status = store.getSnapshot().events.filter(event => event.run_id === result.run_id).map(eventStatus).filter(value => value !== null).at(-1) ?? 'running'
      setActiveSession((session) => ({ ...session, status, title: session.title || content.slice(0, 80) }))
      setSessions((current) => current.map((session) => session.id === ticket.sessionId ? { ...session, status, title: session.title || content.slice(0, 80) } : session))
      setError(null)
    } catch (requestError) { if (store.matches(ticket)) setError(requestError instanceof Error ? requestError.message : 'The prompt could not be sent.') }
  }

  const stopSession = async () => {
    if (isDemoMode) { unavailableInDemo(); return }
    if (!sessions.some((session) => session.id === activeSession.id)) return
    const ticket = store.capture()
    try {
      await rpcClient.request('session.cancel', { session_id: activeSession.id })
      if (!store.matches(ticket)) return
      setActiveSession(session => ['completed', 'failed', 'cancelled'].includes(session.status) ? session : { ...session, status: 'stopping' })
    } catch { if (store.matches(ticket)) setError('Could not stop the agent.') }
  }

  const syncSession = async () => {
    if (isDemoMode) { unavailableInDemo(); return }
    if (!live || !currentSession.id) return
    setSyncing(true)
    const ticket = store.beginHistory(true)
    try {
      const history = await fetchHistory(currentSession.id)
      if (!store.applyHistory(ticket, history)) return
      const status = store.getSnapshot().events.map(eventStatus).filter(value => value !== null).at(-1) ?? history.session.status
      const session = { ...history.session, status }
      setActiveSession(session)
      setSessions((current) => current.map(item => item.id === session.id ? session : item))
      setError(null)
    } catch (requestError) { if (store.isCurrentHistory(ticket)) setError(requestError instanceof Error ? requestError.message : 'Could not synchronize the session.') }
    finally { setSyncing(false) }
  }

  const checkBackend = async () => {
    if (isDemoMode) { unavailableInDemo(); return }
    setCheckingBackend(true)
    try { await rpcClient.request('health.check'); setError(null) }
    catch { setError('The backend health check failed.') }
    finally { setCheckingBackend(false) }
  }

  const revealMapFile = async (file: string) => {
    if (isDemoMode) { unavailableInDemo(); return }
    try {
      if (window.desktop) await window.desktop.revealWorkspaceFile(activeWorkspace.path, file)
      else await navigator.clipboard.writeText(`${activeWorkspace.path}/${file}`)
    } catch { setError('Could not reveal this file.') }
  }

  const openRunDiff = async (runId: number) => {
    const ticket = store.capture()
    try {
      const diff = await rpcClient.request('run.diff.get', { session_id: activeSession.id, run_id: runId })
      if (store.matches(ticket)) setReviewDiff(diff)
    } catch (requestError) { if (store.matches(ticket)) setError(requestError instanceof Error ? requestError.message : 'Could not load the saved diff.') }
  }

  const decideRunDiff = async (runId: number, action: 'accept' | 'revert') => {
    if (isDemoMode) { unavailableInDemo(); return }
    const ticket = store.capture()
    const diff = await rpcClient.request(`run.diff.${action}`, { session_id: activeSession.id, run_id: runId })
    if (!store.matches(ticket)) return
    setReviewDiff(diff)
    setRunDiff((current) => current?.run_id === runId ? diff : current)
    if (action === 'revert') await refreshGitStatus(activeWorkspace)
  }

  const createEvalCaseFromRun = async (runId: number) => {
    if (isDemoMode) { unavailableInDemo(); return }
    setCreatingEval(true)
    try {
      await rpcClient.request('eval.case.create_from_run', { run_id: runId })
      setProductMode('evals')
      setError(null)
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not create an eval case from this run.') }
    finally { setCreatingEval(false) }
  }

  return (
    <main className="app-shell" onClick={() => { setWorkspaceMenuId(null); setSessionMenuId(null) }}>
      <AppHeader connection={connection} demo={isDemoMode} mode={productMode} onModeChange={setProductMode} onOpenSettings={() => setShowSettings(true)} />

      {productMode === 'evals' ? <EvalsMode live={live} demo={isDemoMode} workspaces={workspaces} onWorkspaceAdded={(workspace) => setWorkspaces((current) => [workspace, ...current.filter((item) => item.id !== workspace.id)])} /> : <div className={`workspace-grid ${sidebarCollapsed ? 'sidebar-collapsed' : ''} ${showActivity ? '' : 'activity-hidden'}`}>
        {!sidebarCollapsed && <WorkspaceSidebar workspaces={workspaces} sessions={groupedSessions} activeWorkspaceId={activeWorkspace.id} activeSessionId={activeSession.id} live={live} workspaceMenuId={workspaceMenuId} sessionMenuId={sessionMenuId} onWorkspaceMenuChange={setWorkspaceMenuId} onSessionMenuChange={setSessionMenuId} onAddWorkspace={() => void chooseWorkspace()} onSelectWorkspace={selectWorkspace} onRenameWorkspace={(workspace) => void renameWorkspace(workspace)} onRemoveWorkspace={(workspace) => void removeWorkspace(workspace)} onCreateSession={() => void createSession()} onSelectSession={selectSession} onDeleteSession={(session) => void deleteSession(session)} onCollapse={() => setSidebarCollapsed(true)} />}

        <ConversationPane workspace={activeWorkspace} session={currentSession} messages={messages} prompt={prompt} live={live} error={error} conversationScrollRef={conversationScrollRef} onPromptChange={setPrompt} onSend={() => void sendPrompt()} onMapCodebase={() => void sendPrompt('Explain this codebase and map its main components and data flow.', 'map')} onStop={() => void stopSession()} onDismissError={() => setError(null)} onAddWorkspace={() => void chooseWorkspace()} />

        {showActivity && <aside className="activity-panel"><div className="activity-header"><div><span className="eyebrow">Session</span><h2>Work</h2></div><button className="icon-button" aria-label="Hide work panel" onClick={() => setShowActivity(false)}><PanelLeftClose size={16} /></button></div><WorkPanel summary={workSummary} status={currentSession.status} onOpenMap={() => setShowMap(true)} diff={runDiff?.run_id === latestRunId ? runDiff : null} earlierRunIds={earlierRunIds} onReviewDiff={(runId) => void openRunDiff(runId)} workspaceId={activeWorkspace.id} gitStatus={gitStatus} gitDisabled={!live || currentSession.status === 'running' || currentSession.status === 'stopping'} onGitChanged={setGitStatus} demo={isDemoMode} onDemoUnavailable={unavailableInDemo} latestRunId={latestRunId ?? null} creatingEval={creatingEval} onCreateEvalCase={(runId) => void createEvalCaseFromRun(runId)} /></aside>}
        {sidebarCollapsed && <button className="show-sidebar" onClick={() => setSidebarCollapsed(false)} aria-label="Show sidebar"><PanelLeftOpen size={16} /></button>}
        {!showActivity && <button className="show-activity" onClick={() => setShowActivity(true)} aria-label="Show activity"><Activity size={16} /></button>}
      </div>}

      {showSettings && <SettingsDialog connection={connection} workspace={activeWorkspace} showSidebar={!sidebarCollapsed} showActivity={showActivity} checkingBackend={checkingBackend} syncing={syncing} canSync={Boolean(currentSession.id) && live} demo={isDemoMode} onToggleSidebar={(show) => setSidebarCollapsed(!show)} onToggleActivity={setShowActivity} onCheckBackend={() => void checkBackend()} onSync={() => void syncSession()} onClose={() => setShowSettings(false)} />}
      {showMap && workSummary.map && <CodebaseMapView map={workSummary.map} onClose={() => setShowMap(false)} onOpenFile={(file) => void revealMapFile(file)} />}
      {reviewDiff && <RunDiffView diff={reviewDiff} demo={isDemoMode} onClose={() => setReviewDiff(null)} onDecision={(action) => decideRunDiff(reviewDiff.run_id, action)} />}
      {showDemoUnavailable && <div className="modal-backdrop demo-unavailable-backdrop" onClick={() => setShowDemoUnavailable(false)}><section className="demo-unavailable-modal" role="alertdialog" aria-modal="true" aria-labelledby="demo-unavailable-title" onClick={(event) => event.stopPropagation()}><span className="eyebrow">Recorded demo</span><h2 id="demo-unavailable-title">not available in demo version</h2><p>This action needs the local desktop app and its backend.</p><button className="primary-action" autoFocus onClick={() => setShowDemoUnavailable(false)}>Okay</button></section></div>}
    </main>
  )
}

export default App
