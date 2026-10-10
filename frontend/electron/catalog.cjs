// Scan bounded ID pages instead of assuming all workspaces fit in one response.
async function workspaceIsRegistered(requestPage, workspacePath) {
  let beforeId = 0
  while (true) {
    const page = await requestPage({ before_id: beforeId, limit: 200 })
    if (!Array.isArray(page) || page.length > 200) throw new Error('Invalid workspace page')
    let lastId = beforeId || Infinity
    for (const workspace of page) {
      if (!Number.isSafeInteger(workspace.id) || workspace.id <= 0 || workspace.id >= lastId) {
        throw new Error('Invalid workspace cursor')
      }
      lastId = workspace.id
    }
    if (page.some((workspace) => workspace.path === workspacePath)) return true
    if (page.length < 200) return false
    beforeId = lastId
  }
}

module.exports = { workspaceIsRegistered }
