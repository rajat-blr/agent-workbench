import { useState, useSyncExternalStore } from 'react'
import { ChatSyncStore } from './chatSync'

export function useChatSync() {
  const [store] = useState(() => new ChatSyncStore())
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot)
  return { store, ...snapshot }
}
