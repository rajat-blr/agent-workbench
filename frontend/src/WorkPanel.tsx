import { AlertCircle, CheckCircle2, ChevronDown, FileCode2, GitBranch, LoaderCircle, Map, RefreshCw, Terminal, XCircle } from 'lucide-react'
import type { SessionStatus } from './runtime'
import type { WorkSummary } from './workSummary'

type Props = {
  summary: WorkSummary
  status: SessionStatus
  syncing: boolean
  canSync: boolean
  onSync: () => void
  onOpenMap: () => void
}

export function WorkPanel({ summary, status, syncing, canSync, onSync, onOpenMap }: Props) {
  return <>
    <div className="work-status-card">
      <span className={`work-status-icon ${status === 'failed' ? 'failed' : ''}`}>{status === 'running' ? <LoaderCircle size={16} className="spin" /> : status === 'failed' ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}</span>
      <div><strong>{summary.title}</strong><p>{summary.detail}</p></div>
    </div>
    <div className="work-content">
      {summary.map && <button className="work-map-card" onClick={onOpenMap}><Map size={18} /><span><strong>Codebase map</strong><small>{summary.map.nodes.length} components · {summary.map.edges.length} relationships</small></span><span aria-hidden="true">↗</span></button>}
      {summary.mode === 'map' && !summary.map && <div className="work-map-pending"><Map size={16} /><span>{summary.mapUnavailable ? 'No valid map was returned. The explanation is still available in chat.' : 'A codebase map will appear here when it is ready.'}</span></div>}
      <section className="work-section"><h3><FileCode2 size={13} /> Changes</h3>{summary.changedFiles.length ? <ul>{summary.changedFiles.map((file) => <li key={file} title={file}>{file}</li>)}</ul> : <p>No file changes recorded for this run.</p>}</section>
      <section className="work-section"><h3><CheckCircle2 size={13} /> Checks</h3>{summary.checks.length ? <ul>{summary.checks.map((check, index) => <li className={check.passed ? 'check-pass' : 'check-fail'} key={`${check.command}-${index}`}>{check.passed ? <CheckCircle2 size={12} /> : <XCircle size={12} />}<span title={check.command}>{check.label} · {check.passed ? 'passed' : 'failed'}</span></li>)}</ul> : <p>No completed checks recorded for this run.</p>}</section>
      {summary.error && <section className="work-section work-error"><h3><AlertCircle size={13} /> Needs attention</h3><p>{summary.error}</p></section>}
      {summary.commands > 0 && <div className="work-command-count"><Terminal size={12} /> {summary.commands} completed command{summary.commands === 1 ? '' : 's'}</div>}
      <details className="technical-details"><summary><ChevronDown size={12} /> Technical details</summary><div>{summary.recentEvents.length ? summary.recentEvents.map((event, index) => <div className="technical-event" key={`${event.sequence ?? index}-${event.type}`}><strong>{event.type}</strong><pre>{JSON.stringify(event.payload, null, 2)}</pre></div>) : <p>No events for this run yet.</p>}</div></details>
    </div>
    <div className="panel-bottom"><button className="activity-toggle" disabled={!canSync || syncing} onClick={onSync}><RefreshCw size={13} className={syncing ? 'spin' : ''} /> {syncing ? 'Synchronizing…' : 'Sync work'}</button><span className="work-panel-note"><GitBranch size={11} /> Local session</span></div>
  </>
}
