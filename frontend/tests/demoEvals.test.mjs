import assert from 'node:assert/strict'
import test from 'node:test'
import { demoEvalRequest } from '../src/demoEvals.ts'

test('synthetic experiment is self-consistent and opens every attempt', () => {
  const [experiment] = demoEvalRequest('eval.experiment.list', {})
  assert.equal(experiment.attempts.length, experiment.attempt_count)
  assert.equal(experiment.results.verdict, 'inconclusive')
  assert.match(experiment.name, /synthetic/)
  for (const result of experiment.results.configurations) {
    const rows = experiment.attempts.filter((row) => row.config_snapshot_id === result.config_snapshot_id)
    assert.equal(result.passed, rows.filter((row) => row.outcome === 'pass').length)
    assert.equal(result.failed, rows.filter((row) => row.outcome === 'fail').length)
    assert.equal(result.evaluable, result.passed + result.failed)
  }
  assert.deepEqual(new Set(experiment.results.comparisons.map((pair) => pair.category)), new Set(['improved', 'regressed', 'unchanged', 'infrastructure']))
  for (const attempt of experiment.attempts) {
    const params = { attempt_id: attempt.id }
    const detail = demoEvalRequest('eval.attempt.get', params)
    assert.equal(detail.outcome, attempt.outcome)
    assert.ok(Array.isArray(demoEvalRequest('eval.attempt.events', params)))
    assert.ok(Array.isArray(demoEvalRequest('eval.attempt.steps', params)))
    assert.equal(detail.diff?.can_revert ?? false, false)
  }
})

test('demo is read-only and returned data cannot mutate fixtures', () => {
  const first = demoEvalRequest('eval.experiment.get', { experiment_id: 1 })
  first.attempts[0].outcome = 'tampered'
  assert.equal(demoEvalRequest('eval.experiment.get', { experiment_id: 1 }).attempts[0].outcome, 'fail')
  const diff = demoEvalRequest('eval.config.diff', { left_snapshot_id: 1, right_snapshot_id: 2 })
  assert.deepEqual(diff.differences.map((item) => item.field), ['instructions'])
  diff.differences[0].right[0].content = 'tampered'
  assert.notEqual(demoEvalRequest('eval.config.list', {})[1].snapshot.instructions[0].content, 'tampered')
  assert.throws(() => demoEvalRequest('eval.experiment.start', { experiment_id: 1 }), /read-only/)
  assert.throws(() => demoEvalRequest('eval.attempt.get', { attempt_id: 999 }), /not found/)
})
