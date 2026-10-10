import type { EvalAttemptDetail, EvalAttemptEvent, EvalCase, EvalConfig, EvalExperiment, EvalScorerOutput, EvalStep, EvalSuite } from './runtime'

export type PortfolioRecording = {
  schema_version: number
  kind: 'recorded_real_comparison'
  experiment: EvalExperiment
  cases: EvalCase[]
  configs: EvalConfig[]
  suites: EvalSuite[]
  attempts: { detail: EvalAttemptDetail; events: EvalAttemptEvent[]; steps: EvalStep[]; outputs: EvalScorerOutput[] }[]
  limitations: string[]
  provenance: { source: string; commit: string; parent: string; title: string; case_revision_id: number; verifier_sha256: string; reference_patch_sha256: string; validation_repetitions: number; production_paths: string[]; test_paths: string[] }[]
}

/** Play back the actual API payloads; do not recompute or fabricate model outcomes. */
export function recordedEvalRequest(recording: PortfolioRecording, method: string, params: Record<string, unknown>): unknown {
  if (!method.startsWith('eval.')) return undefined
  const copy = (value: unknown) => structuredClone(value)
  if (method === 'eval.case.list') return copy(recording.cases)
  if (method === 'eval.suite.list') return copy(recording.suites)
  if (method === 'eval.config.list') return copy(recording.configs)
  if (method === 'eval.experiment.list') return copy([recording.experiment])
  if (method === 'eval.experiment.get') {
    if (Number(params.experiment_id) !== recording.experiment.id) throw new Error('Recorded experiment not found')
    return copy(recording.experiment)
  }
  if (method === 'eval.config.diff') {
    const left = recording.configs.find(config => config.snapshot.id === Number(params.left_snapshot_id))?.snapshot
    const right = recording.configs.find(config => config.snapshot.id === Number(params.right_snapshot_id))?.snapshot
    if (!left || !right) throw new Error('Recorded configuration not found')
    return copy({ differences: ['model', 'reasoning_effort', 'instructions', 'sandbox_policy', 'cli_version'].filter(field => JSON.stringify(left[field as keyof typeof left]) !== JSON.stringify(right[field as keyof typeof right])).map(field => ({ field, left: left[field as keyof typeof left], right: right[field as keyof typeof right] })) })
  }
  if (['eval.attempt.get', 'eval.attempt.events', 'eval.attempt.steps', 'eval.attempt.artifact'].includes(method)) {
    const attempt = recording.attempts.find(row => row.detail.id === Number(params.attempt_id))
    if (!attempt) throw new Error('Recorded attempt not found')
    if (method === 'eval.attempt.get') return copy(attempt.detail)
    if (method === 'eval.attempt.events') return copy(attempt.events)
    if (method === 'eval.attempt.steps') return copy(attempt.steps)
    const output = attempt.outputs.find(row => row.artifact_id === Number(params.artifact_id))
    if (!output) throw new Error('Recorded scorer output not found')
    const offset = Number(params.offset ?? 0), limit = Number(params.limit ?? 65536)
    if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > 262144) throw new Error('Invalid output page')
    const total = output.stdout.length + output.stderr.length
    const end = Math.min(total, offset + limit)
    return copy({ ...output, offset, stdout: output.stdout.slice(offset, end), stderr: output.stderr.slice(Math.max(0, offset - output.stdout.length), Math.max(0, end - output.stdout.length)), total_length: total, next_offset: end, has_more: end < total })
  }
  throw new Error('Recorded Evals demo is read-only')
}
