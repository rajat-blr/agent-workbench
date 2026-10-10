const assert = require('node:assert/strict')
const { test } = require('node:test')
const { workspaceIsRegistered } = require('../electron/catalog.cjs')

test('file reveal registration finds workspaces beyond the first 500', async () => {
  const rows = Array.from({ length: 601 }, (_, i) => ({ id: i + 1, path: `/workspace/${i + 1}` }))
  const calls = []
  const request = async (params) => {
    calls.push(params)
    return rows.filter(row => !params.before_id || row.id < params.before_id).reverse().slice(0, params.limit)
  }
  assert.equal(await workspaceIsRegistered(request, '/workspace/1'), true)
  assert.equal(calls.length, 4)
  assert.equal(await workspaceIsRegistered(request, '/unregistered'), false)
})

test('file reveal fails closed on malformed pages, stuck cursors or RPC failures', async () => {
  await assert.rejects(workspaceIsRegistered(async () => null, '/workspace'), /page/)
  await assert.rejects(workspaceIsRegistered(async () => [{ id: 1 }, { id: 1 }], '/workspace'), /cursor/)
  await assert.rejects(workspaceIsRegistered(async () => { throw new Error('Unauthorized') }, '/workspace'), /Unauthorized/)
})
