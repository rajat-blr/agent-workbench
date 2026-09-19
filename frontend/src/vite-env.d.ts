/// <reference types="vite/client" />

interface Window {
  desktop?: {
    getBackendConnection: () => Promise<{ url: string; token: string }>
    selectDirectory: () => Promise<string | null>
    revealWorkspaceFile: (workspacePath: string, filePath: string) => Promise<void>
  }
}
