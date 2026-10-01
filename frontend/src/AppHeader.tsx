import { FlaskConical, MessageSquareText, Settings2 } from 'lucide-react'
import type { ConnectionStatus } from './runtime'

const labels: Record<ConnectionStatus, string> = {
  connected: 'Connected',
  connecting: 'Connecting',
  reconnecting: 'Reconnecting',
  disconnected: 'Offline',
}

type Props = {
  connection: ConnectionStatus
  demo?: boolean
  mode: 'chat' | 'evals'
  onModeChange: (mode: 'chat' | 'evals') => void
  onOpenSettings: () => void
}

export function AppHeader({ connection, demo = false, mode, onModeChange, onOpenSettings }: Props) {
  return <header className="topbar">
    <div className="brand-lockup">Agent Workbench</div>
    <nav className="product-navigation" aria-label="Product areas"><button className={mode === 'chat' ? 'selected' : ''} aria-current={mode === 'chat' ? 'page' : undefined} onClick={() => onModeChange('chat')}><MessageSquareText size={15} /><span>Chat workspace</span></button><button className={mode === 'evals' ? 'selected' : ''} aria-current={mode === 'evals' ? 'page' : undefined} onClick={() => onModeChange('evals')}><FlaskConical size={15} /><span>Evals lab</span></button></nav>
    <div className="topbar-actions">
      {demo && <span className="demo-pill">Recorded demo</span>}
      <span className={`connection-pill ${connection}`}><span className="connection-dot" /> {labels[connection]}</span>
      <button className="icon-button" aria-label="Settings" onClick={onOpenSettings}><Settings2 size={17} /></button>
    </div>
  </header>
}
