function isRunning(child) {
  return Boolean(child?.pid) && child.exitCode === null && child.signalCode === null
}

function observeBackend(child, { isQuitting, isReady, onFailure }) {
  let reported = false
  const report = (message) => {
    if (!reported && !isQuitting() && isReady()) {
      reported = true
      onFailure(message)
    }
  }
  child.on('error', (error) => report(error.message))
  child.on('exit', (code, signal) => report(
    `The local backend exited unexpectedly (${signal || `code ${code}`}). Restart Agent Workbench to reconnect. Active runs may be interrupted; saved history is retained.`,
  ))
}

async function stopBackend(child, {
  processGroup = process.platform !== 'win32',
  graceMs = 10000,
  forceMs = 2000,
  kill = process.kill,
} = {}) {
  if (!isRunning(child)) return
  const signal = (value) => {
    try {
      if (processGroup) kill(-child.pid, value)
      else child.kill(value)
    } catch (error) {
      if (error.code !== 'ESRCH') throw error
    }
  }
  const waitForExit = (timeout) => new Promise((resolve) => {
    if (!isRunning(child)) return resolve(true)
    const onExit = () => { clearTimeout(timer); resolve(true) }
    const timer = setTimeout(() => {
      child.removeListener('exit', onExit)
      resolve(false)
    }, timeout)
    child.once('exit', onExit)
  })
  // Graceful ASGI shutdown cancels separately grouped agents and scorers.
  signal('SIGTERM')
  if (await waitForExit(graceMs)) return
  signal('SIGKILL')
  if (!await waitForExit(forceMs)) throw new Error('Backend did not exit after forced shutdown')
}

module.exports = { isRunning, observeBackend, stopBackend }
