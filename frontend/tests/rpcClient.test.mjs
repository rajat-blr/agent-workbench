import assert from 'node:assert/strict'
import { test } from 'node:test'
import { RpcClient } from '../src/rpcClient.ts'

function fixture(t) {
  const previous = { window: globalThis.window, WebSocket: globalThis.WebSocket }
  let nextTimer = 0
  const timers = new Map()
  class Socket {
    static OPEN = 1; static CLOSED = 3
    static all = []
    readyState = 0; sent = []
    constructor(url, protocols) { this.url = url; this.protocols = protocols; Socket.all.push(this) }
    open() { this.readyState = 1; this.onopen?.() }
    close() { this.readyState = 3; this.onclose?.() }
    send(value) { this.sent.push(JSON.parse(value)) }
    message(value) { this.onmessage?.({ data: JSON.stringify(value) }) }
  }
  globalThis.WebSocket = Socket
  globalThis.window = {
    setTimeout: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id },
    clearTimeout: id => timers.delete(id),
  }
  const client = new RpcClient()
  t.after(() => { client.close(); globalThis.window = previous.window; globalThis.WebSocket = previous.WebSocket })
  return { client, Socket, timers }
}

test('connect uses authenticated subprotocol and matches RPC responses by id', async t => {
  const { client, Socket, timers } = fixture(t)
  const connected = client.connect({ url: 'http://127.0.0.1:49231', token: 'fixture' })
  const socket = Socket.all.at(-1)
  assert.equal(socket.url, 'ws://127.0.0.1:49231/ws')
  assert.deepEqual(socket.protocols, ['agent-workbench', 'auth.fixture'])
  socket.open(); await connected
  const result = client.request('health.check')
  socket.message({ jsonrpc: '2.0', id: socket.sent[0].id, result: { ok: true } })
  assert.deepEqual(await result, { ok: true })
  assert.equal(timers.size, 0)
})

test('obsolete socket events and responses cannot affect the replacement connection', async t => {
  const { client, Socket } = fixture(t)
  const first = client.connect(); Socket.all[0].open(); await first
  const old = Socket.all[0]
  let events = 0
  client.onEvent(() => events++)
  const pending = client.request('slow')
  const rejected = assert.rejects(pending, /replaced/)
  const second = client.connect({ url: 'http://127.0.0.1:8001', token: 'new' })
  const current = Socket.all.at(-1); current.open(); await second; await rejected
  old.message({ method: 'session.event', params: { session_id: 1 } })
  current.message({ method: 'session.event', params: { session_id: 1 } })
  assert.equal(events, 1)
})

test('close rejects pending calls, clears timers, and does not reconnect', async t => {
  const { client, Socket, timers } = fixture(t)
  const connected = client.connect(); Socket.all[0].open(); await connected
  const rejected = assert.rejects(client.request('pending'), /closed/)
  client.close(); await rejected
  assert.equal(timers.size, 0)
})

test('socket close before opening settles connect and schedules only one reconnect', async t => {
  const { client, Socket, timers } = fixture(t)
  const rejected = assert.rejects(client.connect(), /closed/)
  Socket.all[0].close(); await rejected
  assert.equal(timers.size, 1)
  const unavailable = assert.rejects(client.request('offline'), /unavailable/)
  await unavailable
  assert.equal(timers.size, 1)
})

test('request timeout and synchronous send failures release pending timers', async t => {
  const { client, Socket, timers } = fixture(t)
  const connected = client.connect(); const socket = Socket.all[0]; socket.open(); await connected
  const rejected = assert.rejects(client.request('slow'), /timed out/)
  const [id, timer] = [...timers.entries()][0]; timers.delete(id); timer.callback(); await rejected
  socket.send = () => { throw new Error('transport lost') }
  await assert.rejects(client.request('broken'), /could not be sent/)
  assert.equal(timers.size, 0)
})

test('malformed frames and unknown response ids leave valid pending requests intact', async t => {
  const { client, Socket } = fixture(t)
  const connected = client.connect(); const socket = Socket.all[0]; socket.open(); await connected
  const result = client.request('health.check')
  socket.onmessage({ data: '{invalid' })
  socket.message({ id: 999, result: false })
  socket.message({ id: socket.sent[0].id, result: true })
  assert.equal(await result, true)
})

test('repository imports allow clone time without extending ordinary request timeouts', async t => {
  const { client, Socket, timers } = fixture(t)
  const connected = client.connect(); const socket = Socket.all[0]; socket.open(); await connected
  const clone = client.request('workspace.clone_github', { url: 'https://github.com/owner/repo' })
  assert.equal([...timers.values()][0].delay, 150_000)
  socket.message({ id: socket.sent.at(-1).id, result: { id: 1 } })
  await clone
  const health = client.request('health.check')
  assert.equal([...timers.values()][0].delay, 15_000)
  socket.message({ id: socket.sent.at(-1).id, result: { ok: true } })
  await health
  assert.equal(timers.size, 0)
})
