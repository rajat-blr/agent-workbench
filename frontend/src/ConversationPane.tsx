import type { RefObject } from 'react'
import { AlertCircle, Folder, FolderPlus, LoaderCircle, Map, Send, Square, WifiOff, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message, Session, Workspace } from './runtime'

async function openExternal(href: string) {
  try {
    const url = new URL(href)
    if (!['http:', 'https:'].includes(url.protocol)) return
    if (window.desktop) await window.desktop.openExternal(url.href)
    else window.open(url.href, '_blank', 'noopener,noreferrer')
  } catch { /* Relative and unsupported links are not opened from agent output. */ }
}

type Props = {
  workspace: Workspace
  session: Session
  messages: Message[]
  prompt: string
  live: boolean
  error: string | null
  conversationScrollRef: RefObject<HTMLDivElement | null>
  onPromptChange: (value: string) => void
  onSend: () => void
  onMapCodebase: () => void
  onStop: () => void
  onDismissError: () => void
  onAddWorkspace: () => void
}

export function ConversationPane({ workspace, session, messages, prompt, live, error, conversationScrollRef, onPromptChange, onSend, onMapCodebase, onStop, onDismissError, onAddWorkspace }: Props) {
  const working = session.status === 'running' || session.status === 'stopping'
  return <section className="main-panel">
    <div className="session-header">
      <div><div className="eyebrow">{session.id ? `Session #${String(session.id).padStart(3, '0')}` : 'No active session'}</div><h1>{session.title || workspace.name}</h1><p className="path-line"><Folder size={13} /> {workspace.path}</p></div>
      <div className="session-controls"><span className={`status-label ${session.status}`}><span className="status-dot" /> {session.status}</span>{session.status === 'running' && <button className="stop-button" onClick={onStop}><Square size={13} fill="currentColor" /> Stop</button>}</div>
    </div>
    {error && <div className="notice"><AlertCircle size={15} /><span>{error}</span><button onClick={onDismissError} aria-label="Dismiss"><X size={14} /></button></div>}
    <div className="conversation-scroll" ref={conversationScrollRef}><div className="conversation-inner">
      {messages.length === 0 ? <div className="empty-conversation"><h2>{workspace.id ? 'What would you like to work on?' : live ? 'Add a workspace to begin' : 'Connecting to the local backend…'}</h2><p>{workspace.id ? 'Ask Codex to inspect, explain, or change this project.' : live ? 'Choose a project folder to start a session.' : 'Your workspaces and conversations will appear once the connection is ready.'}</p>{!workspace.id && live && <button className="primary-action" onClick={onAddWorkspace}><FolderPlus size={14} /> Add workspace</button>}</div> : messages.map((message, index) => <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
        <div className="message-meta">{message.role === 'user' ? 'You' : 'Codex'}</div>
        <div className="message-body">{message.role === 'assistant' ? <div className="markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ href, children }) => href && /^https?:\/\//i.test(href) ? <a href={href} onClick={(event) => { event.preventDefault(); void openExternal(href) }}>{children}</a> : <span>{children}</span> }}>{message.content}</ReactMarkdown></div> : <p>{message.content}</p>}</div>
      </article>)}
      {session.status === 'running' && <div className="thinking"><LoaderCircle size={15} className="spin" /> Codex is working…</div>}
    </div></div>
    <div className="composer-wrap"><div className="composer"><textarea aria-label="Message Codex" value={prompt} onChange={(event) => onPromptChange(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); onSend() } }} placeholder="Ask Codex to work on your code…" rows={2} /><div className="composer-toolbar"><div className="composer-hints">Enter to send · Shift+Enter for newline</div><div className="composer-actions"><button className="map-action" disabled={!live || !session.id || working} onClick={onMapCodebase}><Map size={14} /> Map codebase</button><button className="send-button" disabled={!prompt.trim() || !live || !session.id || working} onClick={onSend}>{live ? <Send size={15} /> : <WifiOff size={15} />} {live ? 'Send' : 'Offline'}</button></div></div></div></div>
  </section>
}
