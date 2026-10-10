const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const fs = require('node:fs/promises')
const os = require('node:os')
const path = require('node:path')
const { test } = require('node:test')
const {
  contentSecurityPolicy, loopbackBackendOrigin, externalUrl,
  isAppDocument, installNavigationGuards, cspHeaders, appResponse,
} = require('../electron/security.cjs')

test('production CSP allows only the exact loopback backend and no inline scripts', () => {
  const policy = contentSecurityPolicy('http://127.0.0.1:49231')
  assert.match(policy, /connect-src http:\/\/127\.0\.0\.1:49231 ws:\/\/127\.0\.0\.1:49231;/)
  assert.match(policy, /script-src 'self';/)
  assert.match(policy, /object-src 'none'/)
  assert.match(policy, /frame-ancestors 'none'/)
  assert.ok(!policy.includes('unsafe-eval'))
  assert.ok(!policy.includes('*'))
  assert.ok(!policy.includes('5173'))
  assert.throws(() => contentSecurityPolicy('https://example.com'))
  assert.throws(() => loopbackBackendOrigin('http://localhost:8000/path'))
  assert.throws(() => loopbackBackendOrigin('http://secret@localhost:8000'))
})

test('development CSP permits Vite HMR but still excludes remote connections', () => {
  const policy = contentSecurityPolicy('http://localhost:8000', true)
  assert.match(policy, /http:\/\/127\.0\.0\.1:5173 ws:\/\/127\.0\.0\.1:5173/)
  assert.match(policy, /script-src 'self' 'unsafe-inline'/)
  assert.ok(!policy.includes('unsafe-eval'))
})

test('header injection replaces existing CSP regardless of case', () => {
  assert.deepEqual(cspHeaders({ 'content-security-policy': ['old'], Other: ['keep'] }, 'new'), {
    Other: ['keep'], 'Content-Security-Policy': ['new'],
  })
})

test('desktop documents and external URLs are validated', () => {
  assert.equal(isAppDocument('workbench://app/index.html', false), true)
  assert.equal(isAppDocument('workbench://app/other.html', false), false)
  assert.equal(isAppDocument('file:///tmp/index.html', false), false)
  assert.equal(isAppDocument('http://127.0.0.1:5173/', true), true)
  assert.equal(isAppDocument('http://127.0.0.1:5173.evil.test/', true), false)
  assert.equal(externalUrl('https://example.com/docs'), 'https://example.com/docs')
  for (const value of ['file:///etc/passwd', 'javascript:alert(1)', 'data:text/html,x', 'https://user:secret@example.com', null]) {
    assert.throws(() => externalUrl(value))
  }
})

test('popups and document navigation are denied, HTTP(S) links open externally', () => {
  const contents = new EventEmitter()
  contents.setWindowOpenHandler = (handler) => { contents.popup = handler }
  const opened = []
  installNavigationGuards(contents, (url) => opened.push(url))
  assert.deepEqual(contents.popup({ url: 'https://example.com/' }), { action: 'deny' })
  assert.deepEqual(contents.popup({ url: 'javascript:alert(1)' }), { action: 'deny' })
  for (const name of ['will-navigate', 'will-redirect', 'will-frame-navigate', 'will-attach-webview']) {
    let prevented = false
    contents.emit(name, { preventDefault: () => { prevented = true } }, 'https://example.com/path')
    assert.equal(prevented, true, name)
  }
  assert.deepEqual(opened, ['https://example.com/', 'https://example.com/path'])
  contents.emit('will-frame-navigate', {
    preventDefault: () => {}, isMainFrame: true, url: 'https://example.com/main-frame',
  })
  assert.equal(opened.at(-1), 'https://example.com/main-frame')
})

test('packaged protocol serves UI with CSP and rejects traversal/symlink escapes', async (t) => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'workbench-security-'))
  t.after(() => fs.rm(temp, { recursive: true, force: true }))
  const root = path.join(temp, 'dist')
  await fs.mkdir(root)
  await fs.writeFile(path.join(root, 'index.html'), '<html>app</html>')
  await fs.writeFile(path.join(temp, 'secret.txt'), 'secret')
  await fs.symlink(path.join(temp, 'secret.txt'), path.join(root, 'escape.txt'))
  const policy = contentSecurityPolicy('http://127.0.0.1:49231')
  const response = await appResponse(new Request('workbench://app/index.html'), root, policy)
  assert.equal(response.status, 200)
  assert.equal(response.headers.get('Content-Security-Policy'), policy)
  assert.equal(response.headers.get('Content-Type'), 'text/html')
  assert.equal(await response.text(), '<html>app</html>')
  for (const url of ['workbench://other/index.html', 'workbench://app/escape.txt', 'workbench://app/%2e%2e%2fsecret.txt', 'workbench://app/%5csecret.txt']) {
    assert.equal((await appResponse(new Request(url), root, policy)).status, 403, url)
  }
  assert.equal((await appResponse(new Request('workbench://app/missing'), root, policy)).status, 404)
  assert.equal((await appResponse(new Request('workbench://app/index.html', { method: 'POST' }), root, policy)).status, 403)
})
