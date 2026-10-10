const { app, BrowserWindow, dialog, ipcMain, shell, protocol, session } = require('electron')
const { spawn } = require('node:child_process')
const crypto = require('node:crypto')
const fs = require('node:fs')
const net = require('node:net')
const path = require('node:path')
const {
  APP_ORIGIN, DEV_ORIGIN, loopbackBackendOrigin, contentSecurityPolicy,
  externalUrl, isAppDocument, installNavigationGuards, cspHeaders, appResponse,
} = require('./security.cjs')
const { observeBackend, stopBackend } = require('./backend-lifecycle.cjs')
const { workspaceIsRegistered } = require('./catalog.cjs')

protocol.registerSchemesAsPrivileged([{
  scheme: 'workbench', privileges: { standard: true, secure: true, supportFetchAPI: true },
}])

// Allow release checks to use a disposable profile without touching real chats.
const profileDirectory = process.env.AGENT_WORKBENCH_USER_DATA_DIR
if (profileDirectory) {
  if (!path.isAbsolute(profileDirectory)) throw new Error('AGENT_WORKBENCH_USER_DATA_DIR must be absolute')
  fs.mkdirSync(profileDirectory, { recursive: true })
  app.setPath('userData', profileDirectory)
}

const isDev = !app.isPackaged
const startsBackend = process.env.START_BACKEND !== 'false'
const backendAuthToken = process.env.BACKEND_AUTH_TOKEN || (startsBackend ? crypto.randomBytes(32).toString('hex') : '')
let backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000'
let backendProcess
let backendReady = false
let quitting = false
let quitComplete = false
let shutdownStarted = false

function executableExists(candidate) {
  if (!candidate) return false
  try {
    fs.accessSync(candidate, fs.constants.X_OK)
    return true
  } catch {
    return false
  }
}

function runtimePath() {
  const home = app.getPath('home')
  const additions = process.platform === 'win32'
    ? [
        path.join(process.env.LOCALAPPDATA || '', 'Programs', 'OpenAI', 'Codex', 'bin'),
        path.join(process.env.APPDATA || '', 'npm'),
      ]
    : [
        path.join(home, '.local', 'bin'),
        '/opt/homebrew/bin',
        '/usr/local/bin',
      ]
  return [...additions.filter(Boolean), process.env.PATH || ''].join(path.delimiter)
}

function resolveCodexCommand(searchPath) {
  if (process.env.CODEX_COMMAND) return process.env.CODEX_COMMAND
  const executableName = process.platform === 'win32' ? 'codex.exe' : 'codex'
  for (const directory of searchPath.split(path.delimiter)) {
    const candidate = path.join(directory, executableName)
    if (executableExists(candidate)) return candidate
  }
  return executableName
}

function availablePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : null
      server.close(() => port ? resolve(port) : reject(new Error('Could not allocate a backend port')))
    })
  })
}

async function waitForBackend(timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  while (Date.now() < deadline) {
    if (backendProcess && (backendProcess.exitCode !== null || backendProcess.signalCode !== null)) {
      throw new Error(`Backend exited with code ${backendProcess.exitCode}`)
    }
    try {
      const response = await fetch(`${backendUrl}/health`)
      if (response.ok) return
    } catch (error) {
      lastError = error
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error(`Backend did not become ready: ${lastError?.message || 'timed out'}`)
}

async function startBackend() {
  backendUrl = loopbackBackendOrigin(backendUrl)
  if (!startsBackend) {
    if (!backendAuthToken) throw new Error('BACKEND_AUTH_TOKEN is required when START_BACKEND=false')
    await waitForBackend()
    return
  }

  const backendRoot = isDev
    ? path.resolve(app.getAppPath(), '../backend')
    : path.join(process.resourcesPath, 'agent-workbench-backend')
  const command = isDev
    ? process.env.BACKEND_PYTHON || path.join(backendRoot, '.venv/bin/python')
    : path.join(backendRoot, process.platform === 'win32' ? 'agent-workbench-backend.exe' : 'agent-workbench-backend')
  const commandArguments = isDev ? [path.join(backendRoot, 'main.py')] : []
  if (!fs.existsSync(command)) throw new Error(`Backend executable was not found at ${command}`)

  const port = process.env.BACKEND_PORT || await availablePort()
  backendUrl = `http://127.0.0.1:${port}`
  const databasePath = path.join(app.getPath('userData'), 'agent-workbench.db')
  const searchPath = runtimePath()
  const backendEnvironment = {
    ...process.env,
    CODEX_COMMAND: resolveCodexCommand(searchPath),
    DATABASE_URL: process.env.DATABASE_URL || `sqlite+aiosqlite:///${databasePath}`,
    LOCAL_AUTH_TOKEN: backendAuthToken,
    PATH: searchPath,
    PORT: String(port),
  }
  backendProcess = spawn(command, commandArguments, {
    cwd: backendRoot,
    env: backendEnvironment,
    stdio: 'inherit',
    detached: process.platform !== 'win32',
  })
  backendProcess.on('error', (error) => console.error('Backend process failed:', error.message))
  observeBackend(backendProcess, {
    isQuitting: () => quitting,
    isReady: () => backendReady,
    onFailure: (message) => dialog.showErrorBox('Agent Workbench backend stopped', message),
  })
  await waitForBackend()
}

function installSessionSecurity() {
  const policy = contentSecurityPolicy(backendUrl, isDev)
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({ responseHeaders: cspHeaders(details.responseHeaders, policy) })
  })
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
  session.defaultSession.setPermissionCheckHandler(() => false)
  if (!isDev) {
    protocol.handle('workbench', (request) => appResponse(
      request, path.join(__dirname, '../dist'), policy,
    ))
  }
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 980,
    minHeight: 680,
    backgroundColor: '#101214',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 18, y: 18 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  installNavigationGuards(window.webContents, (value) => shell.openExternal(externalUrl(value)))
  window.loadURL(isDev ? DEV_ORIGIN : `${APP_ORIGIN}/index.html`)
}

function trustedHandle(channel, handler) {
  ipcMain.handle(channel, (event, ...args) => {
    if (!event.senderFrame || event.senderFrame !== event.sender.mainFrame
      || !isAppDocument(event.senderFrame.url, isDev)) {
      throw new Error('Untrusted desktop IPC sender')
    }
    return handler(event, ...args)
  })
}

trustedHandle('desktop:backend-connection', () => ({
  url: backendUrl,
  token: backendAuthToken,
}))
trustedHandle('desktop:select-directory', async () => {
  const result = await dialog.showOpenDialog({ properties: ['openDirectory', 'createDirectory'] })
  return result.canceled ? null : result.filePaths[0]
})
trustedHandle('desktop:reveal-workspace-file', async (_event, workspacePath, filePath) => {
  if (typeof workspacePath !== 'string' || typeof filePath !== 'string' || path.isAbsolute(filePath)) {
    throw new Error('Invalid workspace file')
  }
  const registered = await workspaceIsRegistered(async (params) => {
    const response = await fetch(`${backendUrl}/rpc`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${backendAuthToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 'reveal-file', method: 'workspace.list', params }),
    })
    if (!response.ok) throw new Error('Could not verify workspace')
    const result = await response.json()
    if (result.error) throw new Error('Could not verify workspace')
    return result.result
  }, workspacePath)
  if (!registered) {
    throw new Error('Workspace is not registered')
  }
  const root = fs.realpathSync(workspacePath)
  const target = fs.realpathSync(path.join(root, filePath))
  if (!target.startsWith(`${root}${path.sep}`) || !fs.statSync(target).isFile()) {
    throw new Error('File is outside the workspace')
  }
  shell.showItemInFolder(target)
})
trustedHandle('desktop:open-external', async (_event, value) => {
  await shell.openExternal(externalUrl(value))
})

app.whenReady().then(async () => {
  try {
    await startBackend()
    backendReady = true
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    console.error('Backend startup failed:', message)
    dialog.showErrorBox('Agent Workbench backend failed to start', message)
    // Never render a document with an invalid/non-loopback backend policy.
    app.quit()
    return
  }

  installSessionSecurity()
  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
  createWindow()
})

app.on('before-quit', (event) => {
  quitting = true
  if (quitComplete || !backendProcess) return
  event.preventDefault()
  if (shutdownStarted) return
  shutdownStarted = true
  stopBackend(backendProcess).catch((error) => {
    console.error('Backend shutdown failed:', error.message)
  }).finally(() => {
    quitComplete = true
    app.quit()
  })
})
