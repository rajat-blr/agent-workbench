const { app, BrowserWindow, dialog } = require('electron')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const isDev = !app.isPackaged
const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000'
let backendProcess

function startBackend() {
  if (process.env.START_BACKEND === 'false') return
  const backendRoot = path.resolve(app.getAppPath(), '../backend')
  const python = process.env.BACKEND_PYTHON || path.join(backendRoot, '.venv/bin/python')
  const entrypoint = path.join(backendRoot, 'main.py')
  if (!fs.existsSync(python) || !fs.existsSync(entrypoint)) return
  backendProcess = spawn(python, [entrypoint], { cwd: backendRoot, env: process.env, stdio: 'inherit' })
  backendProcess.on('error', (error) => console.error('Backend process failed:', error.message))
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
    },
  })

  if (isDev) {
    window.loadURL('http://127.0.0.1:5173')
  } else {
    window.loadFile(path.join(__dirname, '../dist/index.html'))
  }
}

app.whenReady().then(() => {
  startBackend()
  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })

  createWindow()
})

app.on('before-quit', () => {
  if (backendProcess && backendProcess.exitCode === null) backendProcess.kill('SIGTERM')
})

require('electron').ipcMain.handle('desktop:backend-url', () => backendUrl)
require('electron').ipcMain.handle('desktop:select-directory', async () => {
  const result = await dialog.showOpenDialog({ properties: ['openDirectory', 'createDirectory'] })
  return result.canceled ? null : result.filePaths[0]
})
