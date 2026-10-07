import type { EvalAttemptDetail, EvalAttemptSummary, EvalCase, EvalConfig, EvalExperiment, EvalStep, EvalSuite, RunDiff } from './runtime'

const timestamp = '2026-10-05T10:00:00Z'
const titles = ['Handle empty input', 'Preserve Unicode', 'Reject invalid JSON', 'Handle nested arrays', 'Recover from timeout', 'Normalize whitespace']
const outcomes = [['fail', 'pass'], ['pass', 'fail'], ['pass', 'pass'], ['fail', 'fail'], ['infra_error', 'pass'], ['fail', 'pass']]
const configs: EvalConfig[] = ['Baseline', 'Focused instructions'].map((name, index) => ({
  id: index + 1, name, description: 'Synthetic demonstration configuration', created_at: timestamp,
  snapshot: { id: index + 1, content_hash: String(index + 1).repeat(64), model: 'demo-model', reasoning_effort: 'medium',
    instructions: index ? [{ kind: 'preamble', content: 'Keep changes focused and check edge cases.' }] : [],
    codex_config: {}, sandbox_policy: { mode: 'workspace-write', network: false }, cli_version: 'synthetic demo',
    uncontrolled_inputs: [], reproducibility_warnings: ['Synthetic fixture, not a real Codex execution.'], created_at: timestamp },
}))
const cases: EvalCase[] = titles.map((title, index) => ({
  id: index + 1, title, description: 'Synthetic parser task', created_at: timestamp, updated_at: timestamp,
  latest_revision: { id: index + 1, case_id: index + 1, revision: 1, status: 'published', content_hash: 'a'.repeat(64),
    workspace_id: 1, source_run_id: null, starting_patch_artifact_id: null, verifier_artifact_id: null,
    base_sha: 'b'.repeat(40), prompt: `Update the parser to ${title.toLowerCase()}.`, setup_spec: [],
    scorer_spec: [{ type: 'command', key: 'parser-tests', argv: ['pytest', '-q'] }], path_policy: {},
    validation_status: 'valid', validation_details: {}, published_at: timestamp, created_at: timestamp },
}))
const suites: EvalSuite[] = [{ id: 1, name: 'Parser edge cases', description: 'Synthetic demonstration suite', created_at: timestamp, updated_at: timestamp,
  latest_version: { id: 1, version: 1, status: 'frozen', content_hash: 'c'.repeat(64), frozen_at: timestamp,
    cases: cases.map((item, index) => ({ case_id: item.id, title: item.title, revision_id: item.latest_revision.id, revision: 1, ordinal: index })) } }]
const attempts: EvalAttemptSummary[] = outcomes.flatMap((pair, index) => pair.map((outcome, config) => ({
  id: index * 2 + config + 1, case_revision_id: index + 1, case_title: titles[index], config_snapshot_id: config + 1,
  sample_index: 0, retry_index: 0, run_id: 1000 + index * 2 + config, status: 'completed', outcome,
  failure_category: outcome === 'infra_error' ? 'agent_execution' : null,
  setup_duration_ms: 500, agent_duration_ms: 20000 + index * 1000, scoring_duration_ms: outcome === 'infra_error' ? null : 800,
  input_tokens: 1200, cached_input_tokens: 300, output_tokens: 250 + index * 10, reasoning_output_tokens: null,
})))
function interval(passed: number, total: number) {
  const p = passed / total, z = 1.959963984540054, denominator = 1 + z * z / total
  const centre = p + z * z / (2 * total), margin = z * Math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
  return [(centre - margin) / denominator, (centre + margin) / denominator]
}
const experiment: EvalExperiment = {
  id: 1, name: 'Parser comparison · synthetic demo', suite_version_id: 1, status: 'completed', samples_per_case: 1,
  concurrency: 1, timeout_seconds: 1800, config_snapshot_ids: [1, 2], configurations: configs.map((config) => ({ snapshot_id: config.snapshot.id, name: config.name })),
  attempt_count: attempts.length, attempt_status_counts: { completed: attempts.length }, attempts,
  created_at: timestamp, started_at: timestamp, completed_at: timestamp,
  results: {
    configurations: configs.map((config) => {
      const rows = attempts.filter((item) => item.config_snapshot_id === config.snapshot.id)
      const passed = rows.filter((item) => item.outcome === 'pass').length, failed = rows.filter((item) => item.outcome === 'fail').length
      const [low, high] = interval(passed, passed + failed)
      return { config_snapshot_id: config.snapshot.id, passed, failed, evaluable: passed + failed,
        infrastructure_errors: rows.filter((item) => item.outcome === 'infra_error').length, pending: 0,
        outcome_counts: Object.fromEntries(['pass', 'fail', 'infra_error', 'timeout', 'cancelled', 'invalid_case'].map((outcome) => [outcome, rows.filter((row) => row.outcome === outcome).length])),
        pass_rate: passed / (passed + failed), confidence_low: low, confidence_high: high,
        durations_ms: Object.fromEntries(['setup', 'agent', 'scoring'].map((stage) => {
          const values = rows.map((row) => row[`${stage}_duration_ms` as 'agent_duration_ms']).filter((value): value is number => value != null).sort((a, b) => a - b)
          return [stage, { median: (values[Math.floor((values.length - 1) / 2)] + values[Math.floor(values.length / 2)]) / 2, min: values[0], max: values.at(-1)!, observed: values.length }]
        })),
        tokens: Object.fromEntries(['input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens'].map((kind) => {
          const values = rows.map((row) => row[kind as 'input_tokens']).filter((value): value is number => value != null)
          return [kind, { total: values.length ? values.reduce((a, b) => a + b, 0) : null, observed: values.length }]
        })),
      }
    }),
    paired: { a_only_pass: 1, b_only_pass: 2, both_pass: 1, both_fail: 1, sample_count: 5, discordant: 3, p_value: 1, inference_available: true },
    comparisons: ['improved', 'regressed', 'unchanged', 'unchanged', 'infrastructure', 'improved'].map((category, index) => ({ case_revision_id: index + 1, sample_index: 0, category, attempt_ids: [index * 2 + 1, index * 2 + 2] })),
    verdict: 'inconclusive', verdict_summary: 'Synthetic example: 5 evaluable pairs, 2 improvements and 1 regression for B versus A (+20 percentage points). This small comparison cannot distinguish the configurations.', is_final: true,
  },
}
function detail(attempt: EvalAttemptSummary): EvalAttemptDetail {
  const passed = attempt.outcome === 'pass'
  const diff: RunDiff = { run_id: attempt.run_id!, status: 'ready', final: true, reason: null, file_count: 1, added: 1, deleted: 1,
    captured_at: timestamp, stale: false, can_revert: false, files: [{ path: 'src/parser.py', status: 'modified', added: 1, deleted: 1,
      patch: '--- a/src/parser.py\n+++ b/src/parser.py\n@@ -1 +1 @@\n-return parse(value)\n+return parse(value.strip())', note: 'Synthetic patch for demonstration', final_hash: null }] }
  return { id: attempt.id, experiment_id: 1, case: { id: attempt.case_revision_id, title: attempt.case_title! }, case_revision_id: attempt.case_revision_id,
    configuration: { snapshot_id: attempt.config_snapshot_id, name: configs[attempt.config_snapshot_id - 1].name, model: 'demo-model', reasoning_effort: 'medium' },
    sample_index: 0, retry_index: 0, run_id: attempt.run_id, status: attempt.status, outcome: attempt.outcome, failure_category: attempt.failure_category,
    durations_ms: { setup: attempt.setup_duration_ms, agent: attempt.agent_duration_ms, scoring: attempt.scoring_duration_ms },
    tokens: { input: attempt.input_tokens, cached_input: attempt.cached_input_tokens, output: attempt.output_tokens, reasoning_output: null },
    scores: attempt.outcome === 'infra_error' ? [] : [{ key: 'parser-tests', required: true, passed, value: { exit_code: passed ? 0 : 1 }, summary: passed ? 'Parser checks passed' : 'Parser edge-case assertion failed', evidence: { stdout: passed ? '6 passed' : 'AssertionError: unexpected parser output', argv: ['pytest', '-q'] }, artifact_id: null }],
    diff: attempt.outcome === 'infra_error' ? null : diff, artifacts: [],
  }
}
export function demoEvalRequest(method: string, params: Record<string, unknown>): unknown {
  if (!method.startsWith('eval.')) return undefined
  if (method === 'eval.case.list') return structuredClone(cases)
  if (method === 'eval.suite.list') return structuredClone(suites)
  if (method === 'eval.config.list') return structuredClone(configs)
  if (method === 'eval.config.diff') {
    const left = configs.find((item) => item.snapshot.id === Number(params.left_snapshot_id))?.snapshot
    const right = configs.find((item) => item.snapshot.id === Number(params.right_snapshot_id))?.snapshot
    if (!left || !right) throw new Error('Demo configuration not found')
    return structuredClone({ differences: ['model', 'reasoning_effort', 'instructions', 'sandbox_policy', 'cli_version'].filter((field) => JSON.stringify(left[field as 'instructions']) !== JSON.stringify(right[field as 'instructions'])).map((field) => ({ field, left: left[field as 'instructions'], right: right[field as 'instructions'] })) })
  }
  if (method === 'eval.experiment.list') return structuredClone([experiment])
  if (method === 'eval.experiment.get' && Number(params.experiment_id) === 1) return structuredClone(experiment)
  const attempt = attempts.find((item) => item.id === Number(params.attempt_id))
  if (method.startsWith('eval.attempt.') && !attempt) throw new Error('Demo attempt not found')
  if (method === 'eval.attempt.get') return structuredClone(detail(attempt!))
  if (attempt?.outcome === 'infra_error' && method === 'eval.attempt.events') return [{ id: 1, type: 'session.failed', payload: { synthetic: true, error: 'Executor unavailable' }, created_at: timestamp }]
  if (attempt?.outcome === 'infra_error' && method === 'eval.attempt.steps') return []
  if (method === 'eval.attempt.events') return [{ id: 1, type: 'codex.item.completed', payload: { synthetic: true, item: { type: 'command_execution', command: 'pytest -q', exit_code: attempt!.outcome === 'pass' ? 0 : 1 } }, created_at: timestamp }]
  if (method === 'eval.attempt.steps') return [{ sequence: 1, source_event_start_id: 1, source_event_end_id: 1, source_item_id: null, kind: 'command', title: 'Run parser checks', status: attempt!.outcome === 'pass' ? 'pass' : 'fail', duration_ms: 800, signature: 'synthetic-demo', flags: ['synthetic'], summary: 'Synthetic verification step', normalizer_version: 1 }] satisfies EvalStep[]
  throw new Error('Synthetic Evals demo is read-only')
}
