const fs = require('node:fs/promises')
const path = require('node:path')

const APP_ORIGIN = 'workbench://app'
const DEV_ORIGIN = 'http://127.0.0.1:5173'

function loopbackBackendOrigin(value) {
  const url = new URL(value)
  if (!['http:', 'https:'].includes(url.protocol)
    || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
    || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('BACKEND_URL must be an HTTP(S) loopback origin')
  }
  return url.origin
}

function contentSecurityPolicy(backendUrl, isDev = false) {
  const backend = loopbackBackendOrigin(backendUrl)
  const websocket = backend.replace(/^http/, 'ws')
  const connections = [backend, websocket]
  if (isDev) connections.push(DEV_ORIGIN, DEV_ORIGIN.replace(/^http/, 'ws'))
  return [
    "default-src 'none'",
    `script-src 'self'${isDev ? " 'unsafe-inline'" : ''}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src ${connections.join(' ')}`,
    "object-src 'none'",
    "base-uri 'none'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'none'",
  ].join('; ')
}

function externalUrl(value) {
  if (typeof value !== 'string') throw new Error('Invalid external URL')
  const url = new URL(value)
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('Unsupported external URL')
  }
  return url.href
}

function isAppDocument(value, isDev) {
  try {
    const url = new URL(value)
    if (url.username || url.password) return false
    return isDev
      ? url.origin === DEV_ORIGIN && url.pathname === '/'
      : url.protocol === 'workbench:' && url.host === 'app' && url.pathname === '/index.html'
  } catch {
    return false
  }
}

function installNavigationGuards(contents, openExternal) {
  const openLink = (value) => {
    try {
      const url = externalUrl(value)
      Promise.resolve(openExternal(url)).catch(() => {})
    } catch { /* Block file:, javascript:, data:, and malformed links. */ }
  }
  contents.setWindowOpenHandler(({ url }) => {
    openLink(url)
    return { action: 'deny' }
  })
  contents.on('will-navigate', (event, url) => {
    event.preventDefault()
    openLink(url)
  })
  contents.on('will-redirect', (event) => event.preventDefault())
  contents.on('will-frame-navigate', (event) => {
    event.preventDefault()
    if (event.isMainFrame) openLink(event.url)
  })
  contents.on('will-attach-webview', (event) => event.preventDefault())
}

function cspHeaders(headers, policy) {
  return {
    ...Object.fromEntries(Object.entries(headers || {}).filter(
      ([key]) => key.toLowerCase() !== 'content-security-policy',
    )),
    'Content-Security-Policy': [policy],
  }
}

// Only packaged UI files are accessible; no arbitrary file:// access.
async function appResponse(request, root, policy) {
  try {
    const url = new URL(request.url)
    if (url.protocol !== 'workbench:' || url.host !== 'app' || request.method !== 'GET') {
      return new Response('Forbidden', { status: 403 })
    }
    const pathname = decodeURIComponent(url.pathname)
    if (pathname.includes('\\') || pathname.includes('\0')
      || pathname.split('/').some((segment) => segment === '..')) {
      return new Response('Forbidden', { status: 403 })
    }
    const realRoot = await fs.realpath(root)
    const target = await fs.realpath(path.join(realRoot, pathname))
    if (!target.startsWith(`${realRoot}${path.sep}`)) return new Response('Forbidden', { status: 403 })
    const mime = {
      '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
      '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon',
      '.woff2': 'font/woff2', '.json': 'application/json',
    }[path.extname(target)] || 'application/octet-stream'
    return new Response(await fs.readFile(target), {
      headers: { 'Content-Type': mime, 'Content-Security-Policy': policy },
    })
  } catch {
    return new Response('Not found', { status: 404 })
  }
}

module.exports = {
  APP_ORIGIN, DEV_ORIGIN, loopbackBackendOrigin, contentSecurityPolicy,
  externalUrl, isAppDocument, installNavigationGuards, cspHeaders, appResponse,
}
