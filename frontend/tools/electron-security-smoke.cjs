// Hidden, disposable Electron renderer test. No real backend, Codex, or profile.
const assert = require('node:assert/strict')
const { app, BrowserWindow, protocol, ipcMain } = require('electron')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const http = require('node:http')
const crypto = require('node:crypto')
const { contentSecurityPolicy, appResponse, installNavigationGuards, isAppDocument } = require('../electron/security.cjs')

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'workbench-electron-smoke-'))
app.setPath('userData', profile)
protocol.registerSchemesAsPrivileged([{
  scheme: 'workbench', privileges: { standard: true, secure: true, supportFetchAPI: true },
}])
const server = http.createServer((_request, response) => {
  response.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': 'workbench://app' })
  response.end('{"ok":true}')
})
let websocketOrigin
server.on('upgrade', (request, socket) => {
  websocketOrigin = request.headers.origin
  const accept = crypto.createHash('sha1').update(`${request.headers['sec-websocket-key']}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`).digest('base64')
  socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\nSec-WebSocket-Protocol: agent-workbench\r\n\r\n`)
  socket.on('data', () => socket.destroy())
  socket.on('error', () => {})
})
let window
let exitCode = 1
const timeout = setTimeout(() => { console.error('Electron smoke timed out'); app.exit(1) }, 20000)

app.whenReady().then(async () => {
  try {
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
    const backend = `http://127.0.0.1:${server.address().port}`
    const policy = contentSecurityPolicy(backend)
    protocol.handle('workbench', (request) => appResponse(request, path.resolve(__dirname, '../dist'), policy))
    ipcMain.handle('desktop:backend-connection', (event) => {
      assert.ok(event.senderFrame === event.sender.mainFrame && isAppDocument(event.senderFrame.url, false))
      return { url: backend, token: 'fixture-only-token' }
    })
    window = new BrowserWindow({ show: false, webPreferences: {
      preload: path.resolve(__dirname, '../electron/preload.cjs'),
      contextIsolation: true, sandbox: true, nodeIntegration: false,
    } })
    const opened = []
    installNavigationGuards(window.webContents, (url) => opened.push(url))
    await window.loadURL('workbench://app/index.html')
    const result = await window.webContents.executeJavaScript(`(async () => {
      const violations = [];
      document.addEventListener('securitypolicyviolation', event => violations.push(event.effectiveDirective));
      const response = await fetch(${JSON.stringify(`${backend}/health`)});
      const websocketWorks = await new Promise(resolve => {
        const socket = new WebSocket(${JSON.stringify(backend.replace('http:', 'ws:') + '/ws')}, ['agent-workbench']);
        socket.onopen = () => { socket.close(); resolve(true); };
        socket.onerror = () => resolve(false);
      });
      let remoteBlocked = false;
      try { await fetch('https://example.invalid/'); } catch { remoteBlocked = true; }
      let otherPortBlocked = false;
      try { await fetch('http://127.0.0.1:1/'); } catch { otherPortBlocked = true; }
      const script = document.createElement('script');
      script.textContent = 'window.inlineScriptExecuted = true';
      document.head.append(script);
      window.open('https://example.com/docs');
      const link = document.createElement('a');
      link.href = 'https://example.com/navigation'; document.body.append(link); link.click();
      await new Promise(resolve => setTimeout(resolve, 150));
      return { ok: response.ok, websocketWorks, remoteBlocked, otherPortBlocked,
        inlineBlocked: !window.inlineScriptExecuted, violations,
        rendered: document.getElementById('root').childElementCount > 0,
        ipcWorks: (await window.desktop.getBackendConnection()).token === 'fixture-only-token' };
    })()`)
    assert.ok(result.ok && result.websocketWorks && result.remoteBlocked && result.otherPortBlocked && result.inlineBlocked && result.rendered && result.ipcWorks, JSON.stringify(result))
    assert.equal(websocketOrigin, 'workbench://app')
    assert.ok(result.violations.includes('connect-src'))
    assert.ok(result.violations.includes('script-src-elem'))
    assert.deepEqual(opened.sort(), ['https://example.com/docs', 'https://example.com/navigation'])
    assert.equal(window.webContents.getURL(), 'workbench://app/index.html')
    console.log('Electron smoke passed: UI, IPC, loopback fetch, CSP, popup/navigation guards')
    exitCode = 0
  } catch (error) {
    console.error(error)
  } finally {
    clearTimeout(timeout)
    window?.destroy()
    server.close()
    app.exit(exitCode)
  }
})

process.on('exit', () => fs.rmSync(profile, { recursive: true, force: true }))
