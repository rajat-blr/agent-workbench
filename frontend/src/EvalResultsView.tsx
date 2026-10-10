import { useState } from 'react'
import type { EvalExperiment } from './runtime'
import { latestAttempts, reviewRows } from './evalReview'
import { EvalOutputComparison } from './EvalOutputComparison'

export function EvalResultsView({ experiment, onClose, onAttempt }: { experiment: EvalExperiment; onClose: () => void; onAttempt: (id: number) => void }) {
  const [filter, setFilter] = useState('all')
  const [history, setHistory] = useState(false)
  const [reviewFilter, setReviewFilter] = useState<'all' | 'failures'>('all')
  const [comparisonIds, setComparisonIds] = useState<number[] | null>(null)
  const latestIds = new Set(latestAttempts(experiment.attempts).map(attempt => attempt.id))
  const rows = reviewRows(experiment.attempts).filter(row => reviewFilter === 'all' || row.attempts.some(attempt => ['fail', 'infra_error', 'timeout', 'invalid_case'].includes(attempt.outcome ?? '')))
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
    <div className="results-heading"><div><span className="eyebrow">Experiment results</span><h2>{experiment.name}</h2><p>{experiment.attempt_count} attempts · {experiment.configurations.length} configurations · {experiment.samples_per_case} sample{experiment.samples_per_case === 1 ? '' : 's'} per task · {experiment.status}</p><p>{experiment.results.verdict.replaceAll('_', ' ')}</p></div><button className="secondary-action" onClick={onClose}>Close</button></div>
    <p className="verdict-context">{experiment.results.verdict_summary}</p>
    {!!experiment.results.warnings.length && <details className="eval-result-caveats"><summary>Interpretation & limitations</summary>{experiment.results.warnings.map(warning => <p className="verdict-context" key={warning}>{warning}</p>)}</details>}
    <section className="eval-score-charts" aria-label="Configuration score visualization"><h3>Scores at a glance</h3><p>Case-weighted pass rate · missing results are not zero scores.</p>
      {experiment.results.configurations.map(result => <div className="eval-chart-row" key={result.config_snapshot_id}>
        <strong>{experiment.configurations.find(config => config.snapshot_id === result.config_snapshot_id)?.name ?? 'Configuration'}</strong>
        <div className="eval-bar-track" role="img" aria-label={result.pass_rate == null ? 'Pass rate unavailable' : `${(result.pass_rate * 100).toFixed(1)} percent case-weighted pass rate`}><span style={{ width: `${100 * (result.pass_rate ?? 0)}%` }} /></div>
        <b>{result.pass_rate == null ? 'N/A' : `${(result.pass_rate * 100).toFixed(1)}%`}</b>
        <small>{result.case_count} evaluable cases · {result.failed} failed attempts · {result.infrastructure_errors} infrastructure errors · {result.pending} pending</small>
      </div>)}
    </section>
    <section className="eval-score-charts" aria-label="Execution time visualization"><h3>Execution time</h3><p>Median agent execution time · excludes setup and scoring. Compare speed alongside correctness.</p>
      {experiment.results.configurations.map(result => {
        const median = result.durations_ms.agent?.median ?? null
        const max = Math.max(1, ...experiment.results.configurations.map(config => config.durations_ms.agent?.median ?? 0))
        return <div className="eval-chart-row" key={result.config_snapshot_id}>
          <strong>{experiment.configurations.find(config => config.snapshot_id === result.config_snapshot_id)?.name ?? 'Configuration'}</strong>
          <div className="eval-bar-track eval-duration-bar" role="img" aria-label={median == null ? 'Agent duration unavailable' : `${(median / 1000).toFixed(1)} seconds median agent duration`}><span style={{ width: `${100 * (median ?? 0) / max}%` }} /></div><b>{duration(median)}</b>
          <small>{result.durations_ms.agent?.observed ?? 0} timed attempts · output tokens {result.tokens.output_tokens?.total?.toLocaleString() ?? 'unavailable'} · cached input tokens {result.tokens.cached_input_tokens?.total?.toLocaleString() ?? 'unavailable'}</small>
        </div>
      })}
    </section>
    <section className="eval-case-review"><div className="results-heading"><div><h3>Case comparison & failure review</h3><p>Select an outcome to inspect its trace, or compare the same sample across configurations.</p></div><label>Review <select value={reviewFilter} onChange={event => setReviewFilter(event.target.value as 'all' | 'failures')}><option value="all">All cases</option><option value="failures">Failures & infrastructure errors</option></select></label></div>
      <div className="eval-review-table-scroll"><table className="eval-review-table"><thead><tr><th scope="col">Case / sample</th>{experiment.configurations.map(config => <th scope="col" key={config.snapshot_id}>{config.name}</th>)}<th scope="col">Evidence</th></tr></thead><tbody>{rows.map(row => <tr key={row.key}>
        <th scope="row">{row.title}<small>Sample {row.sample + 1}</small></th>
        {experiment.configurations.map(config => { const attempt = row.attempts.find(item => item.config_snapshot_id === config.snapshot_id); return <td key={config.snapshot_id}>{attempt ? <button className={`eval-outcome-button ${attempt.outcome ?? attempt.status}`} onClick={() => onAttempt(attempt.id)}>{attempt.outcome ?? attempt.status}<small>{duration(attempt.agent_duration_ms)} · retry {attempt.retry_index}{attempt.failure_category ? ` · ${attempt.failure_category}` : ''}</small></button> : <span>Not scheduled</span>}</td> })}
        <td><button className="secondary-action" disabled={row.attempts.length < 2} onClick={() => setComparisonIds(experiment.configurations.flatMap(config => row.attempts.filter(attempt => attempt.config_snapshot_id === config.snapshot_id).map(attempt => attempt.id)))}>Compare outputs</button></td>
      </tr>)}</tbody></table></div>{!rows.length && <p>No attempts match this review filter.</p>}
    </section>
    {comparisonIds && <EvalOutputComparison key={comparisonIds.join(':')} ids={comparisonIds} onAttempt={onAttempt} onClose={() => setComparisonIds(null)} />}
    <details className="eval-detailed-statistics"><summary>Detailed statistics · timing, tokens & uncertainty</summary><div className="result-metrics">
      {experiment.results.configurations.map((result, index) => <article key={result.config_snapshot_id}>
        <span>{index === 0 ? 'A' : 'B'} · {experiment.configurations.find((config) => config.snapshot_id === result.config_snapshot_id)?.name ?? 'Config'}</span>
        <strong>{result.pass_rate == null ? '—' : `${Math.round(result.pass_rate * 100)}%`}</strong>
        <small>{result.passed} passed · {result.failed} failed · {result.infrastructure_errors} infra · {result.pending} pending</small>
        <small>{result.outcome_counts.timeout} timeout · {result.outcome_counts.cancelled} cancelled · {result.outcome_counts.invalid_case} invalid</small>
        <small>Equal-weight mean over {result.case_count} evaluable cases · pooled attempt rate {result.attempt_pass_rate == null ? '—' : `${Math.round(result.attempt_pass_rate * 100)}%`} (descriptive)</small>
        {result.confidence_low != null && <small>95% case-bootstrap interval {Math.round(result.confidence_low * 100)}–{Math.round((result.confidence_high ?? 0) * 100)}% · n={result.case_count} cases</small>}
        <details><summary>Per-case pass rates</summary>{result.case_pass_rates.map(row => <small key={row.case_revision_id}>Case #{row.case_revision_id}: {row.pass_rate == null ? '—' : `${Math.round(row.pass_rate * 100)}%`} · {row.evaluable} evaluable · {row.excluded} excluded samples</small>)}</details>
        {Object.entries(result.durations_ms).map(([stage, metric]) => <small key={stage}>{stage}: median {duration(metric.median)} · range {duration(metric.min)}–{duration(metric.max)} · n={metric.observed}</small>)}
        {Object.entries(result.tokens).map(([kind, metric]) => <small key={kind}>{kind.replaceAll('_', ' ')}: {metric.total?.toLocaleString() ?? 'unavailable'} · n={metric.observed}</small>)}
      </article>)}
      {experiment.configurations.length === 2 && <article><span>Case-level changes · B versus A</span><strong>+{experiment.results.paired.improved_cases} / −{experiment.results.paired.regressed_cases}</strong><small>{experiment.results.paired.case_count} evaluable cases · {experiment.results.paired.sample_count} matched sample pairs</small><small>Exact case sign-test p: {experiment.results.paired.p_value?.toFixed(4) ?? 'unavailable'}</small><small>Mean case difference: {experiment.results.paired.mean_difference == null ? '—' : `${(100 * experiment.results.paired.mean_difference).toFixed(1)} pp`}</small>{experiment.results.paired.confidence_low != null && <small>95% paired case-bootstrap interval: {(100 * experiment.results.paired.confidence_low).toFixed(1)} to {(100 * (experiment.results.paired.confidence_high ?? 0)).toFixed(1)} pp</small>}</article>}
    </div></details>
    <div className="matrix-filters"><label>Show <select value={filter} onChange={(event) => setFilter(event.target.value)}>{['all', ...(experiment.configurations.length === 2 ? ['improved', 'regressed', 'unchanged'] : []), 'failed', 'infrastructure', 'pending'].map((value) => <option key={value} value={value}>{value}</option>)}</select></label><label><input type="checkbox" checked={history} onChange={(event) => setHistory(event.target.checked)} /> Include retry history</label><span>{attempts.length} attempts</span></div>
    <div className="attempt-matrix">{attempts.map((attempt) => <button className={`attempt-cell ${attempt.outcome ?? attempt.status}`} key={attempt.id} onClick={() => onAttempt(attempt.id)}><span>{attempt.case_title ?? `Case #${attempt.case_revision_id}`} · sample {attempt.sample_index + 1} · retry {attempt.retry_index}</span><b>{experiment.configurations.find((item) => item.snapshot_id === attempt.config_snapshot_id)?.name ?? 'Config'}</b><small>{attempt.outcome ?? attempt.status} · {duration(attempt.agent_duration_ms)}</small></button>)}</div>
    {!attempts.length && <p className="verdict-context">No attempts match this filter.</p>}
  </section>
}
