import { RefreshCw, X } from 'lucide-react'
import type { ConnectionStatus, Workspace } from './runtime'

type Props = {
  connection: ConnectionStatus
  workspace: Workspace
  showSidebar: boolean
  showActivity: boolean
  checkingBackend: boolean
  syncing: boolean
  canSync: boolean
  onToggleSidebar: (show: boolean) => void
  onToggleActivity: (show: boolean) => void
  onCheckBackend: () => void
  onSync: () => void
  onClose: () => void
}

export function SettingsDialog({ connection, workspace, showSidebar, showActivity, checkingBackend, syncing, canSync, onToggleSidebar, onToggleActivity, onCheckBackend, onSync, onClose }: Props) {
  return <div className="modal-backdrop" onClick={onClose}><section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title" onClick={(event) => event.stopPropagation()}>
    <div className="modal-header"><div><span className="eyebrow">Application</span><h2 id="settings-title">Settings</h2></div><button className="icon-button" aria-label="Close settings" onClick={onClose}><X size={16} /></button></div>
    <div className="settings-list"><div><span>Backend</span><strong className={connection === 'connected' ? 'healthy' : 'unhealthy'}>{connection}</strong></div><div><span>Agent</span><strong>Codex</strong></div><div><span>Workspace</span><strong title={workspace.path}>{workspace.id ? workspace.name : 'None'}</strong></div></div>
    <label className="setting-toggle"><input type="checkbox" checked={showSidebar} onChange={(event) => onToggleSidebar(event.target.checked)} /> Show workspace sidebar</label>
    <label className="setting-toggle"><input type="checkbox" checked={showActivity} onChange={(event) => onToggleActivity(event.target.checked)} /> Show work panel</label>
    <details className="settings-diagnostics"><summary>Diagnostics</summary><div><button className="secondary-action" disabled={checkingBackend || connection !== 'connected'} onClick={onCheckBackend}><RefreshCw size={14} className={checkingBackend ? 'spin' : ''} /> Check backend</button><button className="secondary-action" disabled={!canSync || syncing} onClick={onSync}><RefreshCw size={14} className={syncing ? 'spin' : ''} /> Sync session</button></div><p>Conversation history is stored locally in SQLite.</p></details>
    <div className="modal-actions"><button className="primary-action" onClick={onClose}>Done</button></div>
  </section></div>
}
