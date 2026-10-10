import type { EvalAttemptEvent, EvalAttemptSummary } from './runtime'

export function latestAttempts(attempts: EvalAttemptSummary[]) {
  const latest = new Map<string, EvalAttemptSummary>()
  for (const attempt of attempts) {
    const key = `${attempt.case_revision_id}:${attempt.config_snapshot_id}:${attempt.sample_index}`
    const previous = latest.get(key)
    if (!previous || attempt.retry_index > previous.retry_index || (attempt.retry_index === previous.retry_index && attempt.id > previous.id)) latest.set(key, attempt)
  }
  return [...latest.values()]
}

export function reviewRows(attempts: EvalAttemptSummary[]) {
  const rows = new Map<string, { key: string; caseId: number; title: string; sample: number; attempts: EvalAttemptSummary[] }>()
  for (const attempt of latestAttempts(attempts)) {
    const key = `${attempt.case_revision_id}:${attempt.sample_index}`
    const row = rows.get(key) ?? { key, caseId: attempt.case_revision_id, title: attempt.case_title ?? `Case #${attempt.case_revision_id}`, sample: attempt.sample_index, attempts: [] }
    row.attempts.push(attempt)
    rows.set(key, row)
  }
  return [...rows.values()].sort((a, b) => a.caseId - b.caseId || a.sample - b.sample)
}

export function responseText(events: EvalAttemptEvent[]) {
  // The runtime emits assistant.text instead of the corresponding raw agent item.
  // Prefer that normalized stream to avoid double-counting the same response.
  const normalized = events.filter(event => event.type === 'assistant.text' && typeof event.payload.content === 'string')
  if (normalized.length) return normalized.map(event => String(event.payload.content)).join('\n\n')
  return events.flatMap(event => {
    const item = event.payload.item
    if (!event.type.endsWith('item.completed') || !item || typeof item !== 'object') return []
    const value = item as Record<string, unknown>
    return value.type === 'agent_message' && typeof value.text === 'string' ? [value.text] : []
  }).join('\n\n')
}
