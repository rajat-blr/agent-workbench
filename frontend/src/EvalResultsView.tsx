import { useState } from 'react'
import type { EvalExperiment } from './runtime'

export function EvalResultsView({ experiment, onClose, onAttempt }: { experiment: EvalExperiment; onClose: () => void; onAttempt: (id: number) => void }) {
  const [filter, setFilter] = useState('all')
  const [history, setHistory] = useState(false)
  const latest = new Map<string, EvalExperiment['attempts'][number]>()
  for (const attempt of experiment.attempts) {
    const key = `${attempt.case_revision_id}:${attempt.config_snapshot_id}:${attempt.sample_index}`
    const previous = latest.get(key)
    if (!previous || attempt.retry_index >= previous.retry_index) latest.set(key, attempt)
  }
  const latestIds = new Set(Array.from(latest.values(), (attempt) => attempt.id))
  const attempts = experiment.attempts.filter((attempt) => {
    if (!history && !latestIds.has(attempt.id)) return false
    if (filter === 'all') return true
    if (filter === 'failed') return attempt.outcome === 'fail'
    if (filter === 'infrastructure') return ['infra_error', 'timeout', 'invalid_case'].includes(attempt.outcome ?? '')
    if (filter === 'pending') return ['queued', 'running'].includes(attempt.status)
    return experiment.results.comparisons.some((pair) => pair.category === filter && pair.case_revision_id === attempt.case_revision_id && pair.sample_index === attempt.sample_index)
  })
  const duration = (value: number | null | undefined) => value == null ? '—' : `${(value / 1000).toFixed(1)}s`
  return <section className="experiment-results">
    <div className="results-heading"><div><span className="eyebrow">Experiment results</span><h2>{experiment.name}</h2><p>{experiment.results.verdict.replaceAll('_', ' ')}</p></div><button className="secondary-action" onClick={onClose}>Close</button></div>
    <p className="verdict-context">{experiment.results.verdict_summary}</p>
    <div className="result-metrics">
      {experiment.results.configurations.map((result, index) => <article key={result.config_snapshot_id}>
        <span>{index === 0 ? 'A' : 'B'} · {experiment.configurations.find((config) => config.snapshot_id === result.config_snapshot_id)?.name ?? 'Config'}</span>
        <strong>{result.pass_rate == null ? '—' : `${Math.round(result.pass_rate * 100)}%`}</strong>
        <small>{result.passed} passed · {result.failed} failed · {result.infrastructure_errors} infra · {result.pending} pending</small>
        <small>{result.outcome_counts.timeout} timeout · {result.outcome_counts.cancelled} cancelled · {result.outcome_counts.invalid_case} invalid</small>
        {result.confidence_low != null && <small>95% CI {Math.round(result.confidence_low * 100)}–{Math.round((result.confidence_high ?? 0) * 100)}% · n={result.evaluable}</small>}
        {Object.entries(result.durations_ms).map(([stage, metric]) => <small key={stage}>{stage}: median {duration(metric.median)} · range {duration(metric.min)}–{duration(metric.max)} · n={metric.observed}</small>)}
        {Object.entries(result.tokens).map(([kind, metric]) => <small key={kind}>{kind.replaceAll('_', ' ')}: {metric.total?.toLocaleString() ?? 'unavailable'} · n={metric.observed}</small>)}
      </article>)}
      {experiment.configurations.length === 2 && <article><span>Paired changes · B versus A</span><strong>+{experiment.results.paired.b_only_pass} / −{experiment.results.paired.a_only_pass}</strong><small>{experiment.results.paired.sample_count} evaluable pairs</small><small>Exact McNemar p: {experiment.results.paired.p_value?.toFixed(4) ?? 'unavailable'}</small></article>}
    </div>
    <div className="matrix-filters"><label>Show <select value={filter} onChange={(event) => setFilter(event.target.value)}>{['all', ...(experiment.configurations.length === 2 ? ['improved', 'regressed', 'unchanged'] : []), 'failed', 'infrastructure', 'pending'].map((value) => <option key={value} value={value}>{value}</option>)}</select></label><label><input type="checkbox" checked={history} onChange={(event) => setHistory(event.target.checked)} /> Include retry history</label><span>{attempts.length} attempts</span></div>
    <div className="attempt-matrix">{attempts.map((attempt) => <button className={`attempt-cell ${attempt.outcome ?? attempt.status}`} key={attempt.id} onClick={() => onAttempt(attempt.id)}><span>{attempt.case_title ?? `Case #${attempt.case_revision_id}`} · sample {attempt.sample_index + 1} · retry {attempt.retry_index}</span><b>{experiment.configurations.find((item) => item.snapshot_id === attempt.config_snapshot_id)?.name ?? 'Config'}</b><small>{attempt.outcome ?? attempt.status} · {duration(attempt.agent_duration_ms)}</small></button>)}</div>
    {!attempts.length && <p className="verdict-context">No attempts match this filter.</p>}
  </section>
}
