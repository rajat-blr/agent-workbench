import { useEffect, useRef, useState } from 'react'
import { rpcClient } from './runtime'
import type { EvalAttemptDetail, EvalAttemptEvent, EvalStep } from './runtime'
import { EvalTraceView } from './EvalTraceView'

type Evidence = { detail: EvalAttemptDetail; steps: EvalStep[]; events: EvalAttemptEvent[] }

export function EvalOutputComparison({ ids, onAttempt, onClose }: { ids: number[]; onAttempt: (id: number) => void; onClose: () => void }) {
  const [columns, setColumns] = useState<{ id: number; evidence?: Evidence; error?: string }[]>(() => ids.map(id => ({ id })))
  const [tab, setTab] = useState<'response' | 'diff' | 'scores' | 'trace'>('response')
  const sectionRef = useRef<HTMLElement>(null)
  useEffect(() => {
    let active = true
    sectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    for (const id of ids) void Promise.all([
      rpcClient.request('eval.attempt.get', { attempt_id: id }),
      rpcClient.request('eval.attempt.steps', { attempt_id: id }),
      rpcClient.request('eval.attempt.events', { attempt_id: id }),
    ]).then(([detail, steps, events]) => {
      if (active) setColumns(current => current.map(column => column.id === id ? { id, evidence: { detail, steps, events } } : column))
    }).catch(error => {
      if (active) setColumns(current => current.map(column => column.id === id ? { id, error: error instanceof Error ? error.message : 'Evidence unavailable' } : column))
    })
    return () => { active = false }
  }, [ids])
  return <section ref={sectionRef} className="eval-comparison" aria-label="Side-by-side attempt comparison">
    <div className="results-heading"><div><span className="eyebrow">Same case · same sample</span><h3>Compare model outputs</h3></div><button className="secondary-action" onClick={onClose}>Close comparison</button></div>
    <div className="eval-review-tabs" aria-label="Evidence view">{(['response', 'diff', 'scores', 'trace'] as const).map(value => <button key={value} aria-pressed={tab === value} onClick={() => setTab(value)}>{value === 'response' ? 'Responses' : value === 'diff' ? 'Code changes' : value === 'scores' ? 'Scorer results' : 'Execution traces'}</button>)}</div>
    <div className="eval-comparison-columns">{columns.map(column => <article key={column.id}>
      {!column.evidence ? <p role="status">{column.error ?? `Loading attempt #${column.id}…`}</p> : <>
        <header><h3>{column.evidence.detail.configuration?.name ?? `Attempt #${column.id}`}</h3><span className={`attempt-outcome ${column.evidence.detail.outcome}`}>{column.evidence.detail.outcome ?? column.evidence.detail.status}</span><p>{column.evidence.detail.configuration?.model ?? 'Default model'} · {column.evidence.detail.configuration?.reasoning_effort ?? 'Default reasoning'} · retry {column.evidence.detail.retry_index}</p></header>
        {tab === 'response' && <EvalTraceView responseOnly steps={[]} events={column.evidence.events} />}
        {tab === 'trace' && <EvalTraceView steps={column.evidence.steps} events={column.evidence.events} />}
        {tab === 'diff' && <>{column.evidence.detail.diff?.files.map(file => <details open key={file.path}><summary>{file.path} · +{file.added} / −{file.deleted}</summary><pre className="eval-patch">{file.patch || file.note || 'Patch unavailable'}</pre></details>)}{!column.evidence.detail.diff?.files.length && <p>No code changes were captured.</p>}</>}
        {tab === 'scores' && <>{column.evidence.detail.failure_category && <p>Failure category: {column.evidence.detail.failure_category}</p>}{column.evidence.detail.scores.map(score => <div className={`eval-score-row ${score.passed === false ? 'fail' : ''}`} key={score.key}><strong>{score.key} · {score.passed === null ? 'unavailable' : score.passed ? 'pass' : 'fail'}{score.required ? ' · required' : ''}</strong><p>{score.summary}</p><pre>{JSON.stringify({ value: score.value, evidence: score.evidence }, null, 2)}</pre></div>)}{!column.evidence.detail.scores.length && <p>No scorer evidence was produced.</p>}</>}
        <button className="secondary-action" onClick={() => onAttempt(column.id)}>Inspect attempt & full scorer output</button>
      </>}
    </article>)}</div>
  </section>
}
