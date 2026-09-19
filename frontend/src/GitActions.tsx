import { useState, type FormEvent } from 'react'
import { GitBranch, X } from 'lucide-react'
import { rpcClient } from './runtime'
import type { GitStatus } from './runtime'

type Action = 'stage' | 'commit' | 'push_main'
type Props = {
  workspaceId: number
  status: GitStatus | null
  disabled: boolean
  onChanged: (status: GitStatus) => void
}
type ActionResult = { action: string; output: string; status: GitStatus }

export function GitActions({ workspaceId, status, disabled, onChanged }: Props) {
  const [busy, setBusy] = useState<Action | null>(null)
  const [commitOpen, setCommitOpen] = useState(false)
  const [message, setMessage] = useState('')
  const [feedback, setFeedback] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const ready = Boolean(workspaceId && status?.is_repository && status.is_root && status.branch === 'main' && !disabled)

  const run = async (action: Action, commitMessage?: string) => {
    setBusy(action); setFeedback(null); setError(null)
    try {
      const result = await rpcClient.request<ActionResult>(`workspace.git_${action}`, {
        workspace_id: workspaceId,
        ...(action === 'commit' ? { message: commitMessage?.trim() } : {}),
      })
      onChanged(result.status)
      setFeedback(result.output || `${result.action[0].toUpperCase()}${result.action.slice(1)} successfully.`)
      if (action === 'commit') { setCommitOpen(false); setMessage('') }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Git action failed.')
    } finally { setBusy(null) }
  }

  const submitCommit = (event: FormEvent) => {
    event.preventDefault()
    if (message.trim()) void run('commit', message)
  }

  return <section className="work-section git-actions-section">
    <h3><GitBranch size={13} /> Repository</h3>
    {!status ? <p>Checking Git status…</p> : !status.is_repository ? <p>This workspace is not a Git repository.</p> : !status.is_root ? <p>Select the repository root as the workspace to stage, commit, or push.</p> : status.branch !== 'main' ? <p>Switch to main before using these Git actions. Current branch: {status.branch}.</p> : <>
      <p>{status.unstaged_count} to stage · {status.staged_count} staged · main</p>
      <div className="git-action-buttons">
        <button disabled={!ready || !!busy || status.unstaged_count === 0} title="git add ." onClick={() => void run('stage')}>{busy === 'stage' ? 'Staging…' : 'Stage'}</button>
        <button disabled={!ready || !!busy || status.staged_count === 0} title="git commit -m [message]" onClick={() => { setError(null); setCommitOpen(true) }}>Commit</button>
        <button disabled={!ready || !!busy} title="git push -u origin main" onClick={() => void run('push_main')}>{busy === 'push_main' ? 'Pushing…' : 'Push to main'}</button>
      </div>
    </>}
    {feedback && <pre className="git-action-feedback" role="status">{feedback}</pre>}
    {error && <p className="git-action-error" role="alert">{error}</p>}
    {commitOpen && <div className="modal-backdrop" onClick={() => { if (!busy) setCommitOpen(false) }}>
      <form className="git-commit-modal" role="dialog" aria-modal="true" aria-labelledby="git-commit-title" onClick={(event) => event.stopPropagation()} onSubmit={submitCommit}>
        <div className="git-commit-header"><div><span className="eyebrow">Git · main</span><h2 id="git-commit-title">Commit staged changes</h2></div><button type="button" className="icon-button" aria-label="Close commit dialog" disabled={!!busy} onClick={() => setCommitOpen(false)}><X size={16} /></button></div>
        <label htmlFor="git-commit-message">Commit message</label>
        <input id="git-commit-message" autoFocus required maxLength={500} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Describe what changed" />
        {error && <p className="git-action-error" role="alert">{error}</p>}
        <div className="git-commit-footer"><button type="button" disabled={!!busy} onClick={() => setCommitOpen(false)}>Cancel</button><button type="submit" disabled={!!busy || !message.trim()}>{busy === 'commit' ? 'Committing…' : 'Commit'}</button></div>
      </form>
    </div>}
  </section>
}
