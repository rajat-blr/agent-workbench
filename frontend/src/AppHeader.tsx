import { Settings2 } from 'lucide-react'
import type { ConnectionStatus } from './runtime'

const labels: Record<ConnectionStatus, string> = {
  connected: 'Connected',
  connecting: 'Connecting',
  reconnecting: 'Reconnecting',
  disconnected: 'Offline',
}

type Props = {
  connection: ConnectionStatus
  onOpenSettings: () => void
}

export function AppHeader({ connection, onOpenSettings }: Props) {
  return <header className="topbar">
    <div className="brand-lockup">Agent Workbench</div>
    <div className="topbar-actions">
      <span className={`connection-pill ${connection}`}><span className="connection-dot" /> {labels[connection]}</span>
      <button className="icon-button" aria-label="Settings" onClick={onOpenSettings}><Settings2 size={17} /></button>
    </div>
  </header>
}
