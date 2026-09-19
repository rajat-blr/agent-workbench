import { useState } from 'react'
import { AlertTriangle, FileCode2, X } from 'lucide-react'
import type { RunDiff } from './runtime'

type Props = { diff: RunDiff; onClose: () => void; onDecision: (action: 'accept' | 'revert') => Promise<void> }

function lineKind(line: string) {
  if (line.startsWith('@@')) return 'hunk'
  if (line.startsWith('+++') || line.startsWith('---')) return 'header'
  if (line.startsWith('+')) return 'added'
  if (line.startsWith('-')) return 'deleted'
  return 'context'
}

function parseLines(patch: string) {
  let oldLine = 0
  let newLine = 0
  return patch.split('\n').map((text) => {
    const kind = lineKind(text)
    if (kind === 'hunk') {
      const numbers = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(text)
      if (numbers) { oldLine = Number(numbers[1]); newLine = Number(numbers[2]) }
    }
    const oldNumber = kind === 'context' || kind === 'deleted' ? oldLine++ : null
    const newNumber = kind === 'context' || kind === 'added' ? newLine++ : null
    return { text, kind, oldNumber, newNumber }
  })
}

export function RunDiffView({ diff, onClose, onDecision }: Props) {
  const [selectedPath, setSelectedPath] = useState(diff.files[0]?.path ?? '')
  const [expanded, setExpanded] = useState(true)
  const [showContext, setShowContext] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const selected = diff.files.find((file) => file.path === selectedPath) ?? diff.files[0]
  const lines = selected?.patch ? parseLines(selected.patch) : []
  const decide = async (action: 'accept' | 'revert') => {
    if (action === 'revert' && !window.confirm(`Revert all ${diff.file_count} file changes from run #${diff.run_id}? This restores their exact before-run contents, including edits that existed before the run. This cannot be undone in the app.`)) return
    setBusy(true); setError(null)
    try { await onDecision(action) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not review changes.') }
    finally { setBusy(false) }
  }
  return <div className="modal-backdrop diff-backdrop" onClick={() => { if (!busy) onClose() }}>
    <section className="diff-modal" role="dialog" aria-modal="true" aria-labelledby="diff-title" onClick={(event) => event.stopPropagation()}>
      <header className="diff-modal-header"><div><span className="eyebrow">Run #{diff.run_id} · {diff.final ? 'saved review' : 'live preview'}</span><h2 id="diff-title">Changes during this run</h2><p>{diff.file_count} file{diff.file_count === 1 ? '' : 's'} changed <span className="diff-additions">+{diff.added}</span> <span className="diff-deletions">−{diff.deleted}</span></p></div><button className="icon-button" aria-label="Close change review" disabled={busy} onClick={onClose}><X size={17} /></button></header>
      {diff.stale && diff.decision !== 'reverted' && <div className="diff-stale"><AlertTriangle size={14} /> The workspace has changed since this review was saved. This is the snapshot from the end of the run.</div>}
      {diff.status === 'unavailable' && <div className="diff-stale"><AlertTriangle size={14} /> {diff.reason || 'A diff is unavailable for this run.'}</div>}
      {error && <div className="diff-stale"><AlertTriangle size={14} /> {error}</div>}
      <div className="diff-body"><nav className="diff-file-list" aria-label="Changed files">{diff.files.map((file) => <button key={file.path} className={selected?.path === file.path ? 'selected' : ''} onClick={() => { setSelectedPath(file.path); setExpanded(true) }}><FileCode2 size={13} /><span title={file.path}>{file.path}</span><small>{file.status}</small></button>)}</nav><div className="diff-file-content">{selected ? <><div className="diff-file-heading"><div><strong>{selected.path}</strong><span>{selected.status} · <b className="diff-additions">+{selected.added}</b> <b className="diff-deletions">−{selected.deleted}</b></span></div><div className="diff-file-actions"><button onClick={() => setShowContext((value) => !value)}>{showContext ? 'Hide' : 'Show'} context</button><button onClick={() => setExpanded((value) => !value)}>{expanded ? 'Collapse' : 'Expand'} diff</button></div></div>{selected.note && <div className="diff-file-note">{selected.note}</div>}{expanded && (selected.patch ? <div className="diff-lines" role="region" aria-label={`Diff for ${selected.path}`}>{lines.map((line, index) => !showContext && line.kind === 'context' ? null : <div className={`diff-line ${line.kind}`} key={`${selected.path}-${index}`}><span className="diff-line-number">{line.oldNumber ?? ''}</span><span className="diff-line-number">{line.newNumber ?? ''}</span><code>{line.text || ' '}</code></div>)}</div> : <div className="diff-no-preview">No text preview is available for this file.</div>)}</> : <div className="diff-no-preview">No files changed during this run.</div>}</div></div>
      <footer className="diff-modal-footer"><span>{diff.decision === 'accepted' ? 'Accepted · files kept as they are.' : diff.decision === 'reverted' ? 'Reverted · files restored to their before-run contents.' : 'This compares the workspace before and after the run. Pre-existing edits are excluded; edits by other processes during the run may also appear.'}</span>{diff.final && diff.status === 'ready' && diff.file_count > 0 && !diff.decision && <div className="diff-review-actions"><button disabled={busy || !diff.can_revert || diff.stale === true} title={!diff.can_revert ? 'A before-run snapshot is unavailable for this review' : diff.stale ? 'Files have changed since this review was saved' : undefined} onClick={() => void decide('revert')}>Revert changes</button><button disabled={busy} onClick={() => void decide('accept')}>Accept changes</button></div>}</footer>
    </section>
  </div>
}
