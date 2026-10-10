import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ChatSyncStore, LatestRequest, eventStatus, fetchFullHistory } from '../src/chatSync.ts'

const event = (sequence, content = `answer ${sequence}`, sessionId = 1) => ({
  session_id: sessionId, sequence, id: sequence, run_id: 7, type: 'assistant.text', payload: { content },
})
const history = (events = [], conversation = [], lastSequence = 0, sessionId = 1) => ({
  session: { id: sessionId, workspace_id: 1, provider: 'codex', status: 'completed' },
  events, conversation, last_sequence: lastSequence, has_more: false,
})

test('session selection immediately resets data and invalidates away/back responses', () => {
  const store = new ChatSyncStore()
  store.select(1)
  const ticket = store.beginHistory()
  store.receive(event(1))
  store.select(2)
  assert.equal(store.getSnapshot().sequence, 0)
  assert.deepEqual(store.getSnapshot().messages, [])
  assert.equal(store.receive(event(2)), false)
  store.select(1)
  assert.equal(store.applyHistory(ticket, history([event(1)], [], 1)), false)
})

test('history merges live events arriving during snapshot fetch without duplicates', () => {
  const store = new ChatSyncStore()
  store.select(1)
  const ticket = store.beginHistory()
  store.receive(event(12, 'new live answer'))
  assert.equal(store.applyHistory(ticket, history([event(10, 'old answer')], [
    { role: 'assistant', content: 'old answer', run_id: 7 },
  ], 10)), true)
  assert.deepEqual(store.getSnapshot().events.map(item => item.sequence), [10, 12])
  assert.deepEqual(store.getSnapshot().messages.map(item => item.content), ['old answer', 'new live answer'])
  assert.equal(store.getSnapshot().sequence, 12)
  assert.equal(store.receive(event(12)), false)
})

test('newer sync supersedes older requests and cancelled requests cannot apply', () => {
  const store = new ChatSyncStore()
  store.select(1)
  const old = store.beginHistory()
  const current = store.beginHistory(true)
  assert.equal(store.applyHistory(old, history()), false)
  store.cancelHistory(old)
  assert.equal(store.isCurrentHistory(current), true)
  store.cancelHistory(current)
  assert.equal(store.applyHistory(current, history()), false)
})

test('incremental reconciliation preserves prior events and never decreases cursor', () => {
  const store = new ChatSyncStore()
  store.select(1)
  store.receive(event(20))
  const ticket = store.beginHistory()
  assert.equal(ticket.afterSequence, 20)
  store.receive(event(22))
  store.applyHistory(ticket, history([event(21)], [], 21))
  assert.deepEqual(store.getSnapshot().events.map(item => item.sequence), [20, 21, 22])
  assert.equal(store.getSnapshot().sequence, 22)
})

test('conversation/event query races preserve missing assistant messages', () => {
  const store = new ChatSyncStore()
  store.select(1)
  store.applyHistory(store.beginHistory(), history([event(1, 'late answer')], [], 1))
  assert.equal(store.getSnapshot().messages[0].content, 'late answer')
})

test('identical distinct assistant events remain distinct while snapshot copies deduplicate', () => {
  const store = new ChatSyncStore()
  store.select(1)
  const events = [event(1, 'same'), event(2, 'same')]
  const messages = events.map(() => ({ role: 'assistant', content: 'same', run_id: 7 }))
  store.receive(events[1])
  store.applyHistory(store.beginHistory(true), history(events, messages, 2))
  assert.equal(store.getSnapshot().messages.length, 2)
  assert.equal(store.getSnapshot().events.length, 2)
})

test('late send acknowledgements do not append to another session, and user precedes answer', () => {
  const store = new ChatSyncStore()
  store.select(1)
  const ticket = store.capture()
  store.receive(event(1, 'fast answer'))
  assert.equal(store.addUser(ticket, 'question', 7), true)
  assert.deepEqual(store.getSnapshot().messages.map(item => item.role), ['user', 'assistant'])
  store.addUser(ticket, 'question', 7)
  assert.equal(store.getSnapshot().messages.length, 2)
  store.applyHistory(store.beginHistory(), history([event(1, 'fast answer')], [], 1))
  assert.deepEqual(store.getSnapshot().messages.map(item => item.role), ['user', 'assistant'])
  store.select(2)
  assert.equal(store.addUser(ticket, 'question', 7), false)
})

test('sequenced duplicates and unsequenced identities do not suppress unrelated events', () => {
  const store = new ChatSyncStore()
  store.select(1)
  const first = { session_id: 1, type: 'notice', payload: { content: 'a' } }
  const second = { ...first, payload: { content: 'b' } }
  assert.equal(store.receive(first), true)
  assert.equal(store.receive(second), true)
  assert.equal(store.receive(first), false)
})

test('pagination advances, uses latest full conversation, and does not mutate RPC responses', async () => {
  const first = { ...history([event(1)], [], 1), has_more: true }
  const next = history([event(2)], [{ role: 'user', content: 'question', run_id: 7 }], 2)
  const calls = []
  const result = await fetchFullHistory(async (id, after) => { calls.push([id, after]); return after ? next : first }, 1)
  assert.deepEqual(calls, [[1, 0], [1, 1]])
  assert.equal(result.events.length, 2)
  assert.equal(result.conversation.length, 1)
  assert.equal(first.events.length, 1)
  await assert.rejects(fetchFullHistory(async () => first, 1), /did not advance/)
})

test('deferred history resolution after selection is ignored', async () => {
  const store = new ChatSyncStore()
  store.select(1)
  const ticket = store.beginHistory()
  let resolve
  const pending = fetchFullHistory(() => new Promise(done => { resolve = done }), 1)
    .then(result => store.applyHistory(ticket, result))
  store.select(2)
  resolve(history([event(1)], [], 1))
  assert.equal(await pending, false)
  assert.equal(store.getSnapshot().sessionId, 2)
})

test('store subscription cleanup and latest-request invalidation', () => {
  const store = new ChatSyncStore()
  let calls = 0
  const unsubscribe = store.subscribe(() => calls++)
  store.select(1)
  unsubscribe()
  store.select(2)
  assert.equal(calls, 1)
  const requests = new LatestRequest()
  const old = requests.begin()
  const current = requests.begin()
  assert.equal(requests.matches(old), false)
  assert.equal(requests.matches(current), true)
  requests.invalidate()
  assert.equal(requests.matches(current), false)
})

test('started events map to running and non-status events are ignored', () => {
  assert.equal(eventStatus({ type: 'session.started' }), 'running')
  assert.equal(eventStatus({ type: 'session.completed' }), 'completed')
  assert.equal(eventStatus({ type: 'assistant.text' }), null)
})
