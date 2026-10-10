const assert = require('node:assert/strict')
const { EventEmitter, once } = require('node:events')
const { spawn } = require('node:child_process')
const { test } = require('node:test')
const { observeBackend, stopBackend } = require('../electron/backend-lifecycle.cjs')

function child() {
  return Object.assign(new EventEmitter(), { pid: 12345, exitCode: null, signalCode: null })
}

test('unexpected backend failure is reported once after startup, not on quit', () => {
  const process = child()
  let ready = false
  let quitting = false
  const errors = []
  observeBackend(process, { isReady: () => ready, isQuitting: () => quitting, onFailure: (message) => errors.push(message) })
  process.emit('exit', 1, null)
  assert.equal(errors.length, 0)
  ready = true
  quitting = true
  process.emit('exit', 0, null)
  assert.equal(errors.length, 0)
  quitting = false
  process.emit('exit', null, 'SIGKILL')
  process.emit('error', new Error('duplicate'))
  assert.equal(errors.length, 1)
  assert.match(errors[0], /SIGKILL/)
})

test('graceful shutdown signals only its owned process group and waits for exit', async () => {
  const process = child()
  const signals = []
  await stopBackend(process, { processGroup: true, kill: (pid, signal) => {
    signals.push([pid, signal])
    setImmediate(() => { process.exitCode = 0; process.emit('exit', 0, null) })
  } })
  assert.deepEqual(signals, [[-12345, 'SIGTERM']])
  assert.equal(process.listenerCount('exit'), 0)
})

test('shutdown escalates after grace period without signaling an exited child', async () => {
  const process = child()
  const signals = []
  // Exercise the Windows/direct-child branch with a child.kill stub.
  process.kill = (signal) => {
    signals.push(signal)
    if (signal === 'SIGKILL') setImmediate(() => { process.signalCode = signal; process.emit('exit', null, signal) })
  }
  await stopBackend(process, { processGroup: false, graceMs: 5, forceMs: 50 })
  assert.deepEqual(signals, ['SIGTERM', 'SIGKILL'])
  await stopBackend(process, { kill: () => assert.fail('already exited') })
})

test('POSIX shutdown reaps a real backend fixture that ignores SIGTERM', { skip: process.platform === 'win32' }, async (t) => {
  const fixture = spawn(process.execPath, ['-e', "process.on('SIGTERM', () => {}); console.log('ready'); setInterval(() => {}, 1000)"], {
    detached: true, stdio: ['ignore', 'pipe', 'pipe'],
  })
  t.after(() => { if (fixture.exitCode === null && fixture.signalCode === null) process.kill(-fixture.pid, 'SIGKILL') })
  await once(fixture.stdout, 'data')
  await stopBackend(fixture, { processGroup: true, graceMs: 20, forceMs: 1000 })
  assert.equal(fixture.signalCode, 'SIGKILL')
})
