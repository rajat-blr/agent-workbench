import type { EvalAttemptEvent, EvalStep } from './runtime'
import { responseText } from './evalReview'

export function EvalTraceView({ steps, events, responseOnly = false }: { steps: EvalStep[]; events: EvalAttemptEvent[]; responseOnly?: boolean }) {
  const response = responseText(events)
  return <div className="eval-trace-view">
    <h3>Model response</h3><pre className="eval-response">{response || 'No model response was captured for this attempt.'}</pre>
    {!responseOnly && <><h3>Execution trace · {steps.length} steps</h3>
    <ol className="eval-timeline">{steps.map(step => <li key={step.sequence} className={step.status}>
      <details><summary><span className="trace-number">{step.sequence}</span><strong>{step.title}</strong><span>{step.status} · {step.duration_ms == null ? 'duration unavailable' : `${(step.duration_ms / 1000).toFixed(2)}s`}</span></summary>
        <p>{step.kind.replaceAll('_', ' ')} · {step.summary}</p>
        {step.flags.length > 0 && <p>{step.flags.join(' · ')}</p>}
        {events.filter(event => event.id >= step.source_event_start_id && event.id <= step.source_event_end_id).map(event => <pre key={event.id}>{JSON.stringify(event.payload, null, 2)}</pre>)}
      </details>
    </li>)}</ol>
    {!steps.length && <p>No normalized steps are available. Raw captured events may still contain evidence.</p>}
    <details className="attempt-raw-events"><summary>All captured events ({events.length})</summary>{events.map(event => <article key={event.id}><strong>#{event.id} · {event.type}</strong><pre>{JSON.stringify(event.payload, null, 2)}</pre></article>)}</details></>}
  </div>
}
