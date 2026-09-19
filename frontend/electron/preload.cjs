const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('desktop', {
  getBackendConnection: () => ipcRenderer.invoke('desktop:backend-connection'),
  selectDirectory: () => ipcRenderer.invoke('desktop:select-directory'),
  revealWorkspaceFile: (workspacePath, filePath) => ipcRenderer.invoke('desktop:reveal-workspace-file', workspacePath, filePath),
})
