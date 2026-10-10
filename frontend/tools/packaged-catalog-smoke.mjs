// Exercise the actual packaged shell and bundled backend with a fresh fixture.
// CDP is enabled only for this disposable run; normal application startup is unchanged.
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { once } from 'node:events'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const root = path.dirname(frontend)
const bundle = path.resolve(process.argv[2] ?? path.join(frontend, 'out/Agent Workbench-darwin-arm64/Agent Workbench.app'))
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'workbench-packaged-catalog-'))
const database = path.join(fixture, 'catalog.db')
const token = 'disposable-catalog-smoke-token'
let backend, application, socket
let logs = ''
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))

async function freePort() {
  const server = net.createServer()
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve) })
  const port = server.address().port
  await new Promise(resolve => server.close(resolve))
  return port
}

async function until(check, description) {
  const deadline = Date.now() + 30000
  while (Date.now() < deadline) {
    if (backend?.exitCode != null || application?.exitCode != null) throw new Error(`Process exited: ${logs}`)
    const result = await check()
    if (result) return result
    await delay(100)
  }
  throw new Error(`Timed out: ${description}\n${logs}`)
}

async function stop(child) {
  if (!child?.pid || child.exitCode != null || child.signalCode != null) return
  const exited = once(child, 'exit')
  child.kill('SIGTERM')
  const timer = setTimeout(() => child.kill('SIGKILL'), 10000)
  try { await exited } finally { clearTimeout(timer) }
}

try {
  assert.ok(fs.existsSync(bundle), 'Build the macOS package first')
  const seeded = spawnSync(path.join(root, 'backend/.venv/bin/python'), [path.join(root, 'backend/tools/seed_catalog_smoke.py'), database], { encoding: 'utf8' })
  assert.equal(seeded.status, 0, seeded.stderr)
  const port = await freePort()
  const debugPort = await freePort()
  const backendUrl = `http://127.0.0.1:${port}`
  backend = spawn(path.join(bundle, 'Contents/Resources/agent-workbench-backend/agent-workbench-backend'), [], {
    cwd: fixture,
    env: { ...process.env, DATABASE_URL: `sqlite+aiosqlite:///${database}`, LOCAL_AUTH_TOKEN: token, PORT: String(port), CODEX_COMMAND: '/usr/bin/false' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  backend.on('error', error => { logs += error.message })
  backend.stderr.on('data', chunk => { logs += chunk })
  await until(async () => { try { return (await fetch(`${backendUrl}/health`)).ok } catch { return false } }, 'bundled backend health')
  application = spawn(path.join(bundle, 'Contents/MacOS/Agent Workbench'), [`--remote-debugging-port=${debugPort}`, '--remote-debugging-address=127.0.0.1'], {
    env: { ...process.env, AGENT_WORKBENCH_USER_DATA_DIR: path.join(fixture, 'profile'), START_BACKEND: 'false', BACKEND_URL: backendUrl, BACKEND_AUTH_TOKEN: token, CODEX_COMMAND: '/usr/bin/false' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  application.on('error', error => { logs += error.message })
  application.stderr.on('data', chunk => { logs += chunk })
  const target = await until(async () => {
    try { return (await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json()).find(item => item.url.startsWith('workbench://app')) } catch { return false }
  }, 'packaged renderer')
  socket = new WebSocket(target.webSocketDebuggerUrl)
  await once(socket, 'open')
  let sequence = 0
  const pending = new Map()
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data)
    const handler = pending.get(message.id)
    if (!handler) return
    pending.delete(message.id)
    clearTimeout(handler.timer)
    if (message.error) handler.reject(new Error(JSON.stringify(message.error)))
    else handler.resolve(message.result)
  })
  const command = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timed out: ${method}`)) }, 10000)
    pending.set(id, { resolve, reject, timer })
    socket.send(JSON.stringify({ id, method, params }))
  })
  const evaluate = async expression => {
    const response = await command('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    assert.equal(response.exceptionDetails, undefined, JSON.stringify(response.exceptionDetails))
    return response.result.value
  }
  await until(() => evaluate(`document.querySelectorAll('.workspace-row').length === 601 && document.querySelectorAll('.session-row').length === 601`), 'complete 601-record catalogs')
  const counts = await evaluate(`({ workspaces: document.querySelectorAll('.workspace-row').length, sessions: document.querySelectorAll('.session-row').length, selected: document.querySelector('.session-row.selected small')?.textContent })`)
  assert.equal(counts.selected, '#601')
  const oldest = await evaluate(`(() => {
    const list = document.querySelector('.session-list'); list.scrollTop = list.scrollHeight;
    const row = document.querySelectorAll('.session-row')[600].getBoundingClientRect();
    const viewport = list.getBoundingClientRect();
    return { x: row.x + row.width / 2, y: row.y + row.height / 2, visible: row.top >= viewport.top && row.bottom <= viewport.bottom + 1 };
  })()`)
  assert.ok(oldest.visible, 'Oldest chat must be reachable by scrolling')
  await command('Input.dispatchMouseEvent', { type: 'mousePressed', x: oldest.x, y: oldest.y, button: 'left', clickCount: 1 })
  await command('Input.dispatchMouseEvent', { type: 'mouseReleased', x: oldest.x, y: oldest.y, button: 'left', clickCount: 1 })
  await until(() => evaluate(`document.querySelector('.session-row.selected small')?.textContent === '#001'`), 'oldest chat selection')
  const scrolling = await evaluate(`(() => {
    return ['.workspace-list', '.session-list'].map(selector => {
      const element = document.querySelector(selector);
      element.scrollTop = element.scrollHeight;
      const result = { selector, height: element.clientHeight, total: element.scrollHeight, top: element.scrollTop };
      return result;
    });
  })()`)
  await evaluate(`new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))`)
  const screenshot = await command('Page.captureScreenshot', { format: 'png' })
  fs.writeFileSync(path.join(fixture, 'catalog.png'), Buffer.from(screenshot.data, 'base64'))
  assert.ok(scrolling.every(row => row.height > 0 && row.top > 0), JSON.stringify(scrolling))
  fs.writeFileSync(path.join(fixture, 'report.json'), JSON.stringify({ counts, scrolling, bundle, agents: 0 }, null, 2))
  console.log(`Packaged catalog smoke passed: 601 workspaces/chats, oldest selection, scrolling. Evidence: ${fixture}`)
} finally {
  socket?.close()
  await stop(application)
  await stop(backend)
  console.log(`Disposable fixture retained for inspection: ${fixture}`)
}
