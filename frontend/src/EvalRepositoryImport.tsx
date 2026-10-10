import { useState } from 'react'
import { rpcClient } from './runtime'
import type { Workspace } from './runtime'

type Props = { live: boolean; onAdded: (workspace: Workspace) => void; onClose: () => void }

export function EvalRepositoryImport({ live, onAdded, onClose }: Props) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const add = async () => {
    if (busy || !live || !url.trim()) return
    setBusy(true); setError('')
    try { onAdded(await rpcClient.request('workspace.clone_github', { url: url.trim() })) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not add the repository.') }
    finally { setBusy(false) }
  }
  return <form className="case-create-card eval-repository-import" aria-busy={busy} onSubmit={(event) => { event.preventDefault(); void add() }}>
    <div><span className="eyebrow">Repository</span><h2>Add a GitHub repository</h2></div>
    <p className="eval-guide-note">Paste a repository link. We’ll clone it locally and select it for your new evaluation task.</p>
    <label>GitHub repository link<input type="url" autoFocus required disabled={busy} value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://github.com/owner/repository" /></label>
    <p className="eval-guide-note">Private repositories use your existing Git credentials. Imports keep the full history so tasks can use a specific commit. Importing does not install dependencies or run repository code.</p>
    {error && <div className="evals-error" role="alert">{error}</div>}
    {busy && <p className="eval-guide-note" role="status">Cloning repository… This can take up to two minutes.</p>}
    <div className="case-create-actions"><button type="button" className="secondary-action" disabled={busy} onClick={onClose}>Cancel</button><button type="submit" className="primary-action" disabled={busy || !live || !url.trim()}>{busy ? 'Cloning…' : 'Add repository'}</button></div>
  </form>
}
