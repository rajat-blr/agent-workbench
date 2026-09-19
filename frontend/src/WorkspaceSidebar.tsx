import { Folder, FolderPlus, MoreHorizontal, PanelLeftClose, Pencil, Plus, Trash2 } from 'lucide-react'
import type { Session, SessionStatus, Workspace } from './runtime'

function sessionTone(status: SessionStatus) {
  return status === 'running' ? 'is-running' : status === 'failed' ? 'is-failed' : status === 'completed' ? 'is-complete' : ''
}

type Props = {
  workspaces: Workspace[]
  sessions: Session[]
  activeWorkspaceId: number
  activeSessionId: number
  live: boolean
  workspaceMenuId: number | null
  sessionMenuId: number | null
  onWorkspaceMenuChange: (id: number | null) => void
  onSessionMenuChange: (id: number | null) => void
  onAddWorkspace: () => void
  onSelectWorkspace: (workspace: Workspace) => void
  onRenameWorkspace: (workspace: Workspace) => void
  onRemoveWorkspace: (workspace: Workspace) => void
  onCreateSession: () => void
  onSelectSession: (session: Session) => void
  onDeleteSession: (session: Session) => void
  onCollapse: () => void
}

export function WorkspaceSidebar({ workspaces, sessions, activeWorkspaceId, activeSessionId, live, workspaceMenuId, sessionMenuId, onWorkspaceMenuChange, onSessionMenuChange, onAddWorkspace, onSelectWorkspace, onRenameWorkspace, onRemoveWorkspace, onCreateSession, onSelectSession, onDeleteSession, onCollapse }: Props) {
  return <aside className="sidebar">
    <div className="sidebar-heading"><span>Workspaces</span><button className="icon-button" aria-label="Add workspace" disabled={!live} onClick={onAddWorkspace}><FolderPlus size={16} /></button></div>
    <div className="workspace-list">
      {workspaces.map((workspace) => <div className="nav-row-wrap" key={workspace.id}>
        <button className={`workspace-row ${workspace.id === activeWorkspaceId ? 'selected' : ''}`} onClick={() => onSelectWorkspace(workspace)}><Folder size={15} /><span>{workspace.name}</span></button>
        <button className="row-menu-button" aria-label={`Actions for ${workspace.name}`} disabled={!live} onClick={(event) => { event.stopPropagation(); onWorkspaceMenuChange(workspaceMenuId === workspace.id ? null : workspace.id) }}><MoreHorizontal size={15} /></button>
        {workspaceMenuId === workspace.id && <div className="row-menu" onClick={(event) => event.stopPropagation()}><button onClick={() => onRenameWorkspace(workspace)}><Pencil size={13} /> Rename</button><button className="danger" onClick={() => onRemoveWorkspace(workspace)}><Trash2 size={13} /> Remove</button></div>}
      </div>)}
      {live && workspaces.length === 0 && <button className="empty-list-action" onClick={onAddWorkspace}>Add your first workspace</button>}
    </div>
    <div className="sidebar-heading sessions-heading"><span>Sessions</span><button className="icon-button" aria-label="New session" disabled={!live || !activeWorkspaceId} onClick={onCreateSession}><Plus size={16} /></button></div>
    <div className="session-list">
      {sessions.map((session) => <div className="nav-row-wrap" key={session.id}>
        <button className={`session-row ${session.id === activeSessionId ? 'selected' : ''}`} onClick={() => onSelectSession(session)}><span className={`session-status ${sessionTone(session.status)}`} /><span className="session-copy"><strong>{session.title || 'New agent session'}</strong><small>#{String(session.id).padStart(3, '0')}</small></span></button>
        <button className="row-menu-button session-menu-button" aria-label={`Actions for session ${session.id}`} disabled={!live} onClick={(event) => { event.stopPropagation(); onSessionMenuChange(sessionMenuId === session.id ? null : session.id) }}><MoreHorizontal size={15} /></button>
        {sessionMenuId === session.id && <div className="row-menu session-menu" onClick={(event) => event.stopPropagation()}><button className="danger" onClick={() => onDeleteSession(session)}><Trash2 size={13} /> Delete session</button></div>}
      </div>)}
    </div>
    <div className="sidebar-footer"><button className="footer-link" onClick={onCollapse}><PanelLeftClose size={15} /> Collapse sidebar</button></div>
  </aside>
}
