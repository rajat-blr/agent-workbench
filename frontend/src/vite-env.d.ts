/// <reference types="vite/client" />

interface Window {
  desktop?: {
    getBackendUrl: () => Promise<string>
    selectDirectory: () => Promise<string | null>
  }
}
