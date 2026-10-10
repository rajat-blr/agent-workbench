import type { GitStatus } from './runtime'

export function stageSelection(status: GitStatus, selected: string[]): string[] {
  const available = new Set(status.files.filter(file => file.unstaged).map(file => file.path))
  if (!selected.length || new Set(selected).size !== selected.length || selected.some(path => !available.has(path))) {
    throw new Error('Select available changed files; refresh if the list changed.')
  }
  return [...selected]
}

export function fileCaution(path: string): string | null {
  return /(^|\/)(\.env(?:\..*)?|.*\.(?:pem|key)|dist|build|node_modules)(\/|$)/i.test(path)
    ? 'May contain secrets or generated output — review before selecting.' : null
}
