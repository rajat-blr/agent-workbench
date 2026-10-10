import assert from 'node:assert/strict'
import test from 'node:test'
import { latestAttempts, reviewRows, responseText } from '../src/evalReview.ts'
import { demoEvalRequest } from '../src/demoEvals.ts'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { transpileModule, JsxEmit, ModuleKind } from 'typescript'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const experiment = demoEvalRequest('eval.experiment.get', { experiment_id: 1 })

test('case grid pairs configurations only within the same case and sample', () => {
  const rows = reviewRows(experiment.attempts)
  assert.equal(rows.length, experiment.attempt_count / 2)
  for (const row of rows) {
    assert.equal(row.attempts.length, 2)
    assert.ok(row.attempts.every(attempt => attempt.case_revision_id === row.caseId && attempt.sample_index === row.sample))
  }
  const nextSample = { ...experiment.attempts[0], id: 90, sample_index: 1 }
  assert.equal(reviewRows([...experiment.attempts, nextSample]).length, rows.length + 1)
})

test('latest retry wins regardless of input order with deterministic equal-retry ties', () => {
  const first = experiment.attempts[0]
  const retry = { ...first, id: 40, retry_index: 1, outcome: 'pass' }
  const tie = { ...retry, id: 41 }
  assert.deepEqual(latestAttempts([tie, first, retry]), [tie])
  assert.deepEqual(latestAttempts([first, retry, tie]), [tie])
  assert.equal(reviewRows([first, retry])[0].attempts[0].id, 40)
})

test('missing configurations and unavailable outcomes remain absent rather than becoming failures', () => {
  assert.deepEqual(reviewRows([]), [])
  const row = reviewRows([{ ...experiment.attempts[0], outcome: null, status: 'running' }])[0]
  assert.equal(row.attempts.length, 1)
  assert.equal(row.attempts[0].outcome, null)
})

test('response extraction prefers normalized text without duplicate raw messages', () => {
  const raw = { id: 1, type: 'codex.item.completed', payload: { item: { type: 'agent_message', text: 'same response' } } }
  assert.equal(responseText([raw]), 'same response')
  assert.equal(responseText([raw, { id: 2, type: 'assistant.text', payload: { content: 'same response' } }]), 'same response')
  assert.equal(responseText([{ id: 1, type: 'codex.item.started', payload: raw.payload }]), '')
  assert.equal(responseText([{ id: 1, type: 'codex.item.completed', payload: { item: { type: 'command_execution', text: 'not a response' } } }]), '')
  assert.equal(responseText([{ id: 1, type: 'assistant.text', payload: { content: {} } }]), '')
})

test('trace UI renders expandable evidence and escapes captured model content', async () => {
  const require = createRequire(import.meta.url)
  const source = readFileSync(new URL('../src/EvalTraceView.tsx', import.meta.url), 'utf8')
  const compiled = transpileModule(source, { compilerOptions: { jsx: JsxEmit.ReactJSX, module: ModuleKind.ESNext } }).outputText
    .replaceAll('"react/jsx-runtime"', JSON.stringify(pathToFileURL(require.resolve('react/jsx-runtime')).href))
    .replaceAll("'./evalReview'", JSON.stringify(new URL('../src/evalReview.ts', import.meta.url).href))
  const { EvalTraceView } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
  const events = [{ id: 1, type: 'assistant.text', payload: { content: '<script>unsafe()</script>' } }]
  const steps = [{ sequence: 1, source_event_start_id: 1, source_event_end_id: 1, title: 'Verify change', status: 'fail', kind: 'command', summary: 'Assertion failed', flags: [], duration_ms: 800 }]
  const html = renderToStaticMarkup(createElement(EvalTraceView, { steps, events }))
  assert.match(html, /Execution trace/)
  assert.match(html, /<details>/)
  assert.match(html, /Assertion failed/)
  assert.match(html, /&lt;script&gt;/)
  assert.doesNotMatch(html, /<script>/)
  const responseOnly = renderToStaticMarkup(createElement(EvalTraceView, { steps, events, responseOnly: true }))
  assert.doesNotMatch(responseOnly, /Execution trace|All captured events/)
})
