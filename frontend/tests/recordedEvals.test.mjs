import assert from 'node:assert/strict'
import test from 'node:test'
import recording from '../src/data/portfolioBenchmark.json' with { type: 'json' }
import { recordedEvalRequest } from '../src/recordedEvals.ts'

test('portfolio recording contains all eight real attempts and both public sources', () => {
  assert.equal(recording.kind, 'recorded_real_comparison')
  assert.equal(recording.experiment.attempt_count, 8)
  assert.equal(recording.attempts.length, 8)
  assert.equal(recording.cases.length, 4)
  assert.equal(recording.provenance.filter(row => row.source === 'Zod').length, 2)
  assert.equal(recording.provenance.filter(row => row.source === 'Hono').length, 2)
  assert.ok(recording.experiment.attempts.every(row => !['running', 'queued'].includes(row.status)))
  assert.equal(recording.experiment.results.verdict, 'inconclusive')
  assert.ok(recording.artifact_audits.length > 0)
  assert.ok(recording.artifact_audits.every(row => row.checksum_verified))
  for (const row of recording.attempts) {
    assert.equal(row.detail.outcome, recording.experiment.attempts.find(attempt => attempt.id === row.detail.id).outcome)
    assert.equal(row.detail.diff?.can_revert ?? false, false)
    const provenance = recording.provenance.find(item => item.case_revision_id === row.detail.case_revision_id)
    const scopeScore = row.detail.scores.find(score => score.key === 'source-only')
    if (scopeScore?.passed) assert.ok(row.detail.diff?.files.every(file => provenance.production_paths.includes(file.path)))
  }
})

test('recorded playback is read-only and returns independent copies', () => {
  const first = recordedEvalRequest(recording, 'eval.experiment.list', {})[0]
  first.name = 'tampered'
  assert.notEqual(recording.experiment.name, 'tampered')
  assert.throws(() => recordedEvalRequest(recording, 'eval.experiment.start', { experiment_id: first.id }), /read-only/)
  assert.throws(() => recordedEvalRequest(recording, 'eval.attempt.get', { attempt_id: -1 }), /not found/)
  const diff = recordedEvalRequest(recording, 'eval.config.diff', { left_snapshot_id: first.config_snapshot_ids[0], right_snapshot_id: first.config_snapshot_ids[1] })
  assert.deepEqual(diff.differences.map(row => row.field), ['reasoning_effort'])
})

test('full scorer evidence pages reconstruct the recorded stdout and stderr', () => {
  // Paging fixture is test-only; short real logs are already complete inline.
  const row = recording.attempts.find(row => row.outputs.length) ?? { detail: { id: 90 }, outputs: [{ artifact_id: 91, stdout: 'verification output\n'.repeat(100), stderr: 'diagnostic\n'.repeat(100) }] }
  const data = { ...recording, attempts: [row] }
  const output = row.outputs[0]
  let offset = 0, stdout = '', stderr = ''
  do {
    const page = recordedEvalRequest(data, 'eval.attempt.artifact', { attempt_id: row.detail.id, artifact_id: output.artifact_id, offset, limit: 1024 })
    stdout += page.stdout
    stderr += page.stderr
    offset = page.next_offset
    if (!page.has_more) break
  } while (offset <= output.stdout.length + output.stderr.length)
  assert.equal(stdout, output.stdout)
  assert.equal(stderr, output.stderr)
  assert.throws(() => recordedEvalRequest(data, 'eval.attempt.artifact', { attempt_id: row.detail.id, artifact_id: output.artifact_id, offset: -1 }), /Invalid/)
})

test('published recording contains no machine-local user paths or retired repository references', () => {
  const serialized = JSON.stringify(recording)
  assert.doesNotMatch(serialized, /\/Users\/rajatvarma|uiagg-benchmark-tools\./i)
  assert.match(recording.source_licenses.Zod, /Colin McDonnell/)
  assert.match(recording.source_licenses.Hono, /Yusuke Wada/)
})
