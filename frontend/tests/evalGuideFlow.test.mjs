import assert from 'node:assert/strict'
import test from 'node:test'
import { EvalGuideFlow } from '../src/evalGuideFlow.ts'

const taskInput = { title: 'Fix parser', prompt: 'Fix the failing parser test.', workspaceId: 7, baseSha: '', command: 'pytest -q tests/test_parser.py', expectation: 'required_scorer_fails' }
const settings = { efforts: ['medium', 'high'], model: 'test-model', preamble: 'Shared instructions', samples: 2 }
function fixture() {
  const calls = []
  const records = { task: { id: 10, title: taskInput.title, latest_revision: { id: 20, status: 'draft', validation_status: 'not_validated', validation_details: {}, workspace_id: 7, base_sha: 'a'.repeat(40) } }, suite: { id: 30, latest_version: { id: 40, status: 'draft' } }, experiment: { id: 50, status: 'ready' } }
  let captures = 0
  let failure = ''
  let invalid = false
  const events = []
  const request = async (method, params) => {
    calls.push({ method, params })
    if (method === failure) { failure = ''; throw new Error('Temporary failure') }
    let result
    if (method === 'eval.case.create' || method === 'eval.case.update_draft') result = records.task
    else if (method === 'eval.case.validate') { records.task.latest_revision.validation_status = invalid ? 'invalid' : 'valid'; records.task.latest_revision.validation_details.problems = invalid ? ['Test command unavailable'] : []; result = records.task }
    else if (method === 'eval.case.publish') { records.task.latest_revision.status = 'published'; result = records.task }
    else if (method === 'eval.suite.create' || method === 'eval.suite.update_draft') result = records.suite
    else if (method === 'eval.suite.freeze') { records.suite.latest_version.status = 'frozen'; result = records.suite }
    else if (method === 'eval.config.capture') result = { id: ++captures, snapshot: { id: captures + 100 } }
    else if (method === 'eval.experiment.preflight') result = { attempt_count: params.config_snapshot_ids.length * params.samples_per_case, invalid_case_revision_ids: [] }
    else if (method === 'eval.experiment.create' || method === 'eval.experiment.get') result = records.experiment
    else if (method === 'eval.experiment.start') { records.experiment.status = 'running'; result = records.experiment }
    else throw new Error(`Unexpected method ${method}`)
    return structuredClone(result)
  }
  const flow = new EvalGuideFlow(request, { onCase: (value) => events.push(value), onSuite() {}, onConfig() {}, onExperiment: (value) => events.push(value), progress() {} })
  return { flow, calls, records, events, fail: (method) => { failure = method }, invalid: (value) => { invalid = value } }
}
const count = (f, method) => f.calls.filter((call) => call.method === method).length

test('guided setup pins only the chosen task and compares explicit reasoning levels', async () => {
  const f = fixture()
  await f.flow.prepareTask(taskInput)
  assert.deepEqual(f.calls.find((c) => c.method === 'eval.suite.update_draft').params.case_revision_ids, [20])
  const draft = f.calls.find((c) => c.method === 'eval.case.update_draft').params
  assert.equal(draft.base_sha, 'a'.repeat(40))
  assert.deepEqual(draft.scorer_spec[0].argv, ['pytest', '-q', 'tests/test_parser.py'])
  const review = await f.flow.review(settings)
  assert.equal(review.attempt_count, 4)
  const configs = f.calls.filter((c) => c.method === 'eval.config.capture').map((c) => c.params)
  assert.deepEqual(configs.map((c) => c.reasoning_effort), ['medium', 'high'])
  const shared = ({ name: _name, reasoning_effort: _effort, ...values }) => values
  assert.deepEqual(shared(configs[0]), shared(configs[1]))
  assert.equal(configs[0].workspace_id, 7)
  assert.equal(configs[0].model, settings.model)
  assert.equal(configs[1].instruction_preamble, settings.preamble)
  assert.equal(count(f, 'eval.experiment.create'), 0)
  await f.flow.start(settings)
  assert.equal(count(f, 'eval.experiment.start'), 1)
  assert.equal(f.events.at(-1).status, 'running')
})

test('invalid task stays editable and retry does not create another draft', async () => {
  const f = fixture()
  f.invalid(true)
  await assert.rejects(f.flow.prepareTask(taskInput), /Test command unavailable/)
  assert.equal(count(f, 'eval.case.publish'), 0)
  assert.equal(count(f, 'eval.suite.create'), 0)
  f.invalid(false)
  await f.flow.prepareTask({ ...taskInput, command: 'pytest -q tests/test_fixed.py' })
  assert.equal(count(f, 'eval.case.create'), 1)
  assert.equal(count(f, 'eval.case.publish'), 1)
})

test('reuse published task and retry suite freeze without duplicating records', async () => {
  const f = fixture()
  const existing = structuredClone(f.records.task)
  existing.latest_revision.status = 'published'
  f.fail('eval.suite.freeze')
  await assert.rejects(f.flow.prepareTask({ ...taskInput, existing }), /Temporary failure/)
  await f.flow.prepareTask({ ...taskInput, existing })
  assert.equal(count(f, 'eval.case.create'), 0)
  assert.equal(count(f, 'eval.case.validate'), 0)
  assert.equal(count(f, 'eval.suite.create'), 1)
})

test('preflight and start retries reuse successful settings and experiment', async () => {
  const f = fixture()
  await f.flow.prepareTask(taskInput)
  f.fail('eval.experiment.preflight')
  await assert.rejects(f.flow.review(settings), /Temporary failure/)
  await f.flow.review(settings)
  assert.equal(count(f, 'eval.config.capture'), 2)
  f.fail('eval.experiment.start')
  await assert.rejects(f.flow.start(settings), /Temporary failure/)
  await f.flow.start(settings)
  assert.equal(count(f, 'eval.experiment.create'), 1)
  // A retry after an already successful start fetches the current status.
  await f.flow.start(settings)
  assert.equal(count(f, 'eval.experiment.start'), 2)
})

test('single reasoning level creates exactly one configuration; changing settings refreshes snapshots', async () => {
  const f = fixture()
  await f.flow.prepareTask(taskInput)
  await f.flow.review({ ...settings, efforts: ['low'] })
  assert.deepEqual(f.calls.at(-1).params.config_snapshot_ids, [101])
  await f.flow.review({ ...settings, efforts: ['low'], samples: 3 })
  assert.equal(count(f, 'eval.config.capture'), 1)
  await f.flow.review({ ...settings, efforts: ['xhigh'], model: 'another-model' })
  assert.deepEqual(f.calls.at(-1).params.config_snapshot_ids, [102])
  await assert.rejects(f.flow.review({ ...settings, efforts: [] }), /Choose one or two/)
  await assert.rejects(f.flow.review({ ...settings, samples: 0 }), /between 1 and 10/)
})
