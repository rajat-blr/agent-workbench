import { AlertCircle, CheckCircle2, FileCode2, LoaderCircle, Map, Terminal, XCircle } from 'lucide-react'
import type { RunDiff, SessionStatus } from './runtime'
import type { GitStatus } from './runtime'
import type { WorkSummary } from './workSummary'
import { GitActions } from './GitActions'

type Props = {
  summary: WorkSummary
  status: SessionStatus
  onOpenMap: () => void
  diff: RunDiff | null
  earlierRunIds: number[]
  onReviewDiff: (runId: number) => void
  workspaceId: number
  gitStatus: GitStatus | null
  gitDisabled: boolean
  onGitChanged: (status: GitStatus) => void
}

export function WorkPanel({ summary, status, onOpenMap, diff, earlierRunIds, onReviewDiff, workspaceId, gitStatus, gitDisabled, onGitChanged }: Props) {
  return <>
    <div className="work-status-card">
      <span className={`work-status-icon ${status === 'failed' ? 'failed' : ''}`}>{status === 'running' ? <LoaderCircle size={16} className="spin" /> : status === 'failed' ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}</span>
      <div><strong>{summary.title}</strong><p>{summary.detail}</p></div>
    </div>
    <div className="work-content">
      {summary.map && <button className="work-map-card" onClick={onOpenMap}><Map size={18} /><span><strong>Codebase map</strong><small>{summary.map.nodes.length} components · {summary.map.edges.length} relationships</small></span><span aria-hidden="true">↗</span></button>}
      {summary.mode === 'map' && !summary.map && <div className="work-map-pending"><Map size={16} /><span>{summary.mapUnavailable ? 'No valid map was returned. The explanation is still available in chat.' : 'A codebase map will appear here when it is ready.'}</span></div>}
      {(diff?.file_count || summary.changedFiles.length > 0 || earlierRunIds.length > 0) ? <section className="work-section"><h3><FileCode2 size={13} /> Changes during this run</h3>{diff?.status === 'ready' ? <><p>{diff.file_count ? `${diff.file_count} file${diff.file_count === 1 ? '' : 's'} · +${diff.added} −${diff.deleted}` : 'No changes since this run started.'}</p>{diff.file_count > 0 && <button className="review-diff-button" onClick={() => onReviewDiff(diff.run_id)}>View changes for this run <span>↗</span></button>}{!diff.final && <small className="diff-refresh-note">Updates after completed file changes and commands.</small>}</> : diff?.status === 'unavailable' ? <p>{diff.reason || 'Git diff is unavailable for this run.'}</p> : summary.changedFiles.length ? <ul>{summary.changedFiles.map((file) => <li key={file} title={file}>{file}</li>)}</ul> : <p>No file changes recorded for this run.</p>}{earlierRunIds.length > 0 && <details className="earlier-run-diffs"><summary>Earlier runs</summary>{earlierRunIds.map((runId) => <button key={runId} onClick={() => onReviewDiff(runId)}>Run #{runId} · View changes <span>↗</span></button>)}</details>}</section> : null}
      <GitActions key={workspaceId} workspaceId={workspaceId} status={gitStatus} disabled={gitDisabled} onChanged={onGitChanged} />
      {summary.checks.length > 0 && <section className="work-section"><h3><CheckCircle2 size={13} /> Checks</h3><ul>{summary.checks.map((check, index) => <li className={check.passed ? 'check-pass' : 'check-fail'} key={`${check.command}-${index}`}>{check.passed ? <CheckCircle2 size={12} /> : <XCircle size={12} />}<span title={check.command}>{check.label} · {check.passed ? 'passed' : 'failed'}</span></li>)}</ul></section>}
      {summary.error && <section className="work-section work-error"><h3><AlertCircle size={13} /> Needs attention</h3><p>{summary.error}</p></section>}
      {summary.commands > 0 && <div className="work-command-count"><Terminal size={12} /> {summary.commands} completed command{summary.commands === 1 ? '' : 's'}</div>}
    </div>
  </>
}
