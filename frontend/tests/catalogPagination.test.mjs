import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fetchCatalog, sortSessions, sortWorkspaces } from '../src/catalogPagination.ts'
import { DemoRpcClient } from '../src/demoRuntime.ts'

test('loads beyond 500 records with bounded ID cursors and no duplicates', async () => {
  const records = Array.from({ length: 601 }, (_, i) => ({ id: i + 1 }))
  const calls = []
  const loaded = await fetchCatalog(async (params) => {
    calls.push(params)
    return records.filter(row => !params.before_id || row.id < params.before_id).reverse().slice(0, params.limit)
  })
  assert.equal(loaded.length, 601)
  assert.equal(new Set(loaded.map(row => row.id)).size, 601)
  assert.deepEqual(calls.map(row => row.before_id), [0, 402, 202, 2])
})

test('empty and exact-full catalogs terminate, with a final empty page when needed', async () => {
  assert.deepEqual(await fetchCatalog(async () => []), [])
  let calls = 0
  const loaded = await fetchCatalog(async () => ++calls === 1 ? Array.from({ length: 200 }, (_, i) => ({ id: 200 - i })) : [])
  assert.equal(loaded.length, 200)
  assert.equal(calls, 2)
})

test('selection changes stop pagination and discard partial results', async () => {
  let current = true
  let calls = 0
  assert.deepEqual(await fetchCatalog(async () => {
    calls++
    current = false
    return Array.from({ length: 200 }, (_, i) => ({ id: 200 - i }))
  }, () => current), [])
  assert.equal(calls, 1)
})

test('invalid ordering and stalled cursors fail instead of looping', async () => {
  await assert.rejects(fetchCatalog(async () => [{ id: 2 }, { id: 2 }]), /cursor/)
  await assert.rejects(fetchCatalog(async () => [{ id: 0 }]), /cursor/)
  await assert.rejects(fetchCatalog(async () => [{ id: 1 }, { id: 2 }]), /cursor/)
  await assert.rejects(fetchCatalog(async () => { throw new Error('Disconnected') }), /Disconnected/)
})

test('presentation sorting preserves names and recent activity, with deterministic ties', () => {
  assert.deepEqual(sortWorkspaces([{ id: 3, name: 'Z' }, { id: 2, name: 'A' }, { id: 1, name: 'A' }]).map(row => row.id), [1, 2, 3])
  assert.deepEqual(sortSessions([{ id: 3, updated_at: '2026-01-01' }, { id: 1, updated_at: '2026-02-01' }, { id: 2, updated_at: '2026-02-01' }]).map(row => row.id), [2, 1, 3])
})

test('demo list endpoints support cursor, limit and workspace filtering', async () => {
  const rpc = new DemoRpcClient()
  const all = await fetchCatalog(params => rpc.request('session.list', params))
  assert.equal(all.length, 2)
  const first = await rpc.request('session.list', { before_id: 0, limit: 1 })
  const next = await rpc.request('session.list', { before_id: first[0].id, limit: 1 })
  assert.ok(first[0].id > next[0].id)
  assert.deepEqual(await rpc.request('session.list', { workspace_id: 999 }), [])
})
