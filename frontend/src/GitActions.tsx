import { useState, type FormEvent } from 'react'
import { GitBranch, X } from 'lucide-react'
import { rpcClient } from './runtime'
import type { GitStatus } from './runtime'
import { fileCaution, stageSelection } from './gitReview'

type Action = 'stage' | 'commit' | 'push'
type Props = {
  workspaceId: number; status: GitStatus | null; disabled: boolean
  onChanged: (status: GitStatus) => void; demo?: boolean; onDemoUnavailable?: () => void
}

export function GitActions({ workspaceId, status, disabled, onChanged, demo = false, onDemoUnavailable }: Props) {
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState<Action | null>(null)
  const [review, setReview] = useState<GitStatus | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [message, setMessage] = useState('')
  const [remote, setRemote] = useState('origin')
  const [branch, setBranch] = useState('')
  const [feedback, setFeedback] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const ready = Boolean(workspaceId && status?.is_repository && status.is_root && status.branch && !disabled)

  const openReview = async (action: Action) => {
    if (demo) { onDemoUnavailable?.(); return }
    setBusy(true); setError(null); setFeedback(null)
    try {
      const fresh = await rpcClient.request('workspace.git_status', { workspace_id: workspaceId })
      onChanged(fresh); setReview(fresh); setMode(action); setSelected([])
      setRemote(fresh.remotes.includes('origin') ? 'origin' : fresh.remotes[0] || '')
      setBranch(fresh.branch || '')
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not review Git changes.') }
    finally { setBusy(false) }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!mode || !review || !review.branch || !ready || busy) return
    setBusy(true); setError(null)
    try {
      const params = { workspace_id: workspaceId, expected_branch: review.branch }
      if (mode === 'commit' && !review.index_token) throw new Error('Reload the staged-file review before committing.')
      const result = mode === 'stage'
        ? await rpcClient.request('workspace.git_stage', { ...params, paths: stageSelection(review, selected) })
        : mode === 'commit'
          ? await rpcClient.request('workspace.git_commit', { ...params, message: message.trim(), index_token: review.index_token! })
          : await rpcClient.request('workspace.git_push', { ...params, remote, branch: branch.trim() })
      onChanged(result.status); setMode(null); setReview(null); setSelected([])
      if (mode === 'commit') setMessage('')
      setFeedback(result.output || `${result.action[0].toUpperCase()}${result.action.slice(1)} successfully.`)
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Git action failed.') }
    finally { setBusy(false) }
  }

  const files = review?.files.filter(file => mode === 'stage' ? file.unstaged : file.staged) || []
  const title = mode === 'stage' ? 'Select files to stage' : mode === 'commit' ? 'Review staged changes' : 'Confirm push destination'
  const canSubmit = ready && !busy && (mode === 'stage' ? selected.length > 0 : mode === 'commit' ? files.length > 0 && !!message.trim() : !!remote && !!branch.trim())

  return <section className="work-section git-actions-section">
    <h3><GitBranch size={13} /> Repository</h3>
    {!status ? <p>Checking Git status…</p> : !status.is_repository ? <p>This workspace is not a Git repository.</p> : !status.is_root ? <p>Select the repository root as the workspace to stage, commit, or push.</p> : !status.branch ? <p>Detached HEAD: check out a branch before using Git actions.</p> : <>
      <p>{status.unstaged_count} to stage · {status.staged_count} staged · {status.branch}</p>
      <div className="git-action-buttons">
        <button disabled={!demo && (!ready || busy || status.unstaged_count === 0)} onClick={() => void openReview('stage')}>Select files…</button>
        <button disabled={!demo && (!ready || busy || status.staged_count === 0)} onClick={() => void openReview('commit')}>Review & commit…</button>
        <button disabled={!demo && (!ready || busy || status.remotes.length === 0)} onClick={() => void openReview('push')}>Push…</button>
      </div>
      {!status.remotes.length && <p>No Git remote configured.</p>}
    </>}
    {feedback && <pre className="git-action-feedback" role="status">{feedback}</pre>}
    {error && !mode && <p className="git-action-error" role="alert">{error}</p>}
    {mode && review && <div className="modal-backdrop" onClick={() => { if (!busy) setMode(null) }}>
      <form className="git-commit-modal git-review-modal" role="dialog" aria-modal="true" aria-labelledby="git-review-title" onClick={event => event.stopPropagation()} onSubmit={event => void submit(event)}>
        <div className="git-commit-header"><div><span className="eyebrow">Git · {review.branch || 'detached'}</span><h2 id="git-review-title">{title}</h2></div><button type="button" className="icon-button" aria-label="Close Git review" disabled={busy} onClick={() => setMode(null)}><X size={16} /></button></div>
        {mode !== 'push' && <>
          <p>{mode === 'stage' ? 'Nothing is selected by default. Only checked files will be staged, using their current full contents.' : 'The commit includes all files currently staged, including files staged outside this app.'}</p>
          <div className="git-review-files">{files.map(file => <label className="git-review-file" key={file.path}>
            {mode === 'stage' && <input type="checkbox" checked={selected.includes(file.path)} disabled={busy} onChange={event => setSelected(current => event.target.checked ? [...current, file.path] : current.filter(path => path !== file.path))} />}
            <span><code>{file.original_path ? `${file.original_path} → ` : ''}{file.path}</code><small>{file.status}{fileCaution(file.path) ? ` · ${fileCaution(file.path)}` : ''}</small></span>
          </label>)}{!files.length && <p>No files available. Reload the review.</p>}</div>
        </>}
        {mode === 'commit' && <><label htmlFor="git-commit-message">Commit message</label><input id="git-commit-message" autoFocus disabled={busy} required maxLength={500} value={message} onChange={event => setMessage(event.target.value)} placeholder="Describe what changed" /></>}
        {mode === 'push' && <>
          <p>Push local <strong>{review.branch}</strong> to the destination below. This does not switch branches or force-push.</p>
          <label htmlFor="git-push-remote">Configured remote</label><select id="git-push-remote" disabled={busy} value={remote} onChange={event => setRemote(event.target.value)}>{review.remotes.map(name => <option key={name}>{name}</option>)}</select>
          <label htmlFor="git-push-branch">Destination branch</label><input id="git-push-branch" disabled={busy} required maxLength={255} value={branch} onChange={event => setBranch(event.target.value)} />
          <p>Confirm: {review.branch} → {remote}/{branch}</p>
        </>}
        {error && <p className="git-action-error" role="alert">{error}</p>}
        {!ready && <p className="git-action-error">Git actions are unavailable while a run is active or this workspace has no branch.</p>}
        <div className="git-commit-footer"><button type="button" disabled={busy} onClick={() => void openReview(mode)}>Reload review</button><button type="button" disabled={busy} onClick={() => setMode(null)}>Cancel</button><button type="submit" disabled={!canSubmit}>{busy ? 'Working…' : mode === 'stage' ? `Stage ${selected.length} selected` : mode === 'commit' ? 'Commit reviewed files' : 'Push to destination'}</button></div>
      </form>
    </div>}
  </section>
}
