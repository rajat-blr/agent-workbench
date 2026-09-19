import type { ActivityEvent, CodebaseMap, SessionStatus } from './runtime'

type Check = { label: string; command: string; passed: boolean }
export type WorkSummary = {
  title: string
  detail: string
  mode: 'chat' | 'map'
  commands: number
  changedFiles: string[]
  checks: Check[]
  error: string | null
  map: CodebaseMap | null
  mapUnavailable: boolean
  recentEvents: ActivityEvent[]
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function string(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function codebaseMap(value: unknown): CodebaseMap | null {
  const map = record(value)
  if (!map || !Array.isArray(map.nodes) || !Array.isArray(map.edges)) return null
  if (!map.nodes.every((node) => {
    const item = record(node)
    return item && string(item.id) && string(item.label) && string(item.summary) && Array.isArray(item.files) && item.files.every((file) => typeof file === 'string')
  })) return null
  if (!map.edges.every((edge) => {
    const item = record(edge)
    return item && string(item.source) && string(item.target) && string(item.label)
  })) return null
  return map as CodebaseMap
}

function checkLabel(command: string): string | null {
  // A compound shell script can exit successfully even when an earlier check failed.
  if (command.length > 220 || /[;|]/.test(command)) return null
  if (/\bpytest\b/.test(command)) return 'Backend tests'
  if (/\b(?:ruff check|npm (?:--prefix \S+ )?run lint|oxlint)\b/.test(command)) return 'Lint'
  if (/\b(?:mypy|tsc)\b/.test(command)) return 'Type check'
  if (/\b(?:vite build|npm (?:--prefix \S+ )?run build)\b/.test(command)) return 'Frontend build'
  return null
}

export function summarizeWork(events: ActivityEvent[], status: SessionStatus): WorkSummary {
  const latestRunId = [...events].reverse().find((event) => event.run_id != null)?.run_id
  const runEvents = latestRunId == null ? [] : events.filter((event) => event.run_id === latestRunId)
  const mode = runEvents.find((event) => event.type === 'session.started')?.payload.mode === 'map' ? 'map' : 'chat'
  const commands = runEvents.filter((event) => event.type === 'codex.item.completed' && record(event.payload.item)?.type === 'command_execution')
  const changedFiles = new Set<string>()
  const checks: Check[] = []
  let error: string | null = null
  for (const event of runEvents) {
    const item = record(event.payload.item)
    if (event.type === 'codex.item.completed' && item?.type === 'file_change' && Array.isArray(item.changes)) {
      for (const change of item.changes) {
        const path = string(record(change)?.path)
        if (path) changedFiles.add(path)
      }
    }
    if (event.type === 'codex.item.completed' && item?.type === 'command_execution') {
      const command = string(item.command)
      const exitCode = item.exit_code
      const label = command ? checkLabel(command) : null
      if (command && label && typeof exitCode === 'number') {
        checks.push({ label, command, passed: exitCode === 0 })
      }
    }
    if (event.type === 'agent.error') error = string(event.payload.content)
    if (event.type === 'session.failed') error = string(event.payload.error) ?? error
  }
  const currentItem = [...runEvents].reverse().find((event) => event.type === 'codex.item.started')
  const activeType = record(currentItem?.payload.item)?.type
  const title = status === 'running'
    ? activeType === 'file_change' ? 'Editing files' : activeType === 'command_execution' ? 'Working in the project' : mode === 'map' ? 'Mapping the codebase' : 'Working on your request'
    : status === 'stopping' ? 'Stopping Codex'
    : status === 'completed' ? 'Run completed'
    : status === 'failed' ? 'Run failed'
    : status === 'cancelled' ? 'Run stopped'
    : 'Ready for a prompt'
  const detail = status === 'running'
    ? mode === 'map' ? 'Building a map from inspected files.' : 'Changes and check results appear here as they complete.'
    : status === 'completed' ? 'Review the results and the reply in chat.'
    : status === 'failed' ? 'Review the issue below or open technical details.'
    : status === 'cancelled' ? 'This run stopped. You can send another prompt.'
    : 'Start a session to see work progress.'
  const mapEvent = [...events].reverse().find((event) => event.type === 'artifact.codebase_map')
  return {
    title,
    detail,
    mode,
    commands: commands.length,
    changedFiles: [...changedFiles],
    checks: checks.slice(-5),
    error,
    map: codebaseMap(mapEvent?.payload),
    mapUnavailable: runEvents.some((event) => event.type === 'artifact.map_unavailable'),
    recentEvents: runEvents.slice(-40),
  }
}
