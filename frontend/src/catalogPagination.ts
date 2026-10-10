import type { SessionRecord, WorkspaceRecord } from './generated/rpcContract'

export const CATALOG_PAGE_SIZE = 200

// IDs, unlike names/activity timestamps, cannot move between pages during loading.
export async function fetchCatalog<T extends { id: number }>(
  requestPage: (params: { before_id: number; limit: number }) => Promise<T[]>,
  isCurrent: () => boolean = () => true,
): Promise<T[]> {
  const records: T[] = []
  let beforeId = 0
  while (isCurrent()) {
    const page = await requestPage({ before_id: beforeId, limit: CATALOG_PAGE_SIZE })
    if (!isCurrent()) return []
    let previousId = beforeId || Infinity
    for (const record of page) {
      if (!Number.isSafeInteger(record.id) || record.id <= 0 || record.id >= previousId) {
        throw new Error('Catalog cursor did not advance')
      }
      previousId = record.id
    }
    if (page.length > CATALOG_PAGE_SIZE) throw new Error('Catalog page exceeded its limit')
    records.push(...page)
    if (page.length < CATALOG_PAGE_SIZE) return records
    beforeId = previousId
  }
  return []
}

export const sortWorkspaces = (records: WorkspaceRecord[]) =>
  records.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : a.id - b.id))

export const sortSessions = (records: SessionRecord[]) =>
  records.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at) || b.id - a.id)
