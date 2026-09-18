const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('desktop', {
  getBackendUrl: () => ipcRenderer.invoke('desktop:backend-url'),
  selectDirectory: () => ipcRenderer.invoke('desktop:select-directory'),
})
