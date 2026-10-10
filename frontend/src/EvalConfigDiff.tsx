import { useState } from 'react'
import { rpcClient } from './runtime'
import type { EvalConfig } from './runtime'

type Difference = { field: string; left: unknown; right: unknown }

export function EvalConfigDiff({ configs }: { configs: EvalConfig[] }) {
  const [left, setLeft] = useState(0)
  const [right, setRight] = useState(0)
  const [differences, setDifferences] = useState<Difference[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const compare = async () => {
    setLoading(true); setError(null); setDifferences(null)
    try {
      const result = await rpcClient.request('eval.config.diff', { left_snapshot_id: left, right_snapshot_id: right })
      setDifferences(result.differences)
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not compare snapshots.') }
    finally { setLoading(false) }
  }
  const choose = (side: 'left' | 'right', value: number) => { if (side === 'left') setLeft(value); else setRight(value); setDifferences(null); setError(null) }
  if (configs.length < 2) return null
  return <section className="config-comparison">
    <h2>Compare snapshots</h2>
    <div className="matrix-filters">
      <label>A <select aria-label="Snapshot A" value={left} onChange={(event) => choose('left', Number(event.target.value))}><option value={0}>Choose configuration</option>{configs.map((config) => <option key={config.id} value={config.snapshot.id}>{config.name}</option>)}</select></label>
      <label>B <select aria-label="Snapshot B" value={right} onChange={(event) => choose('right', Number(event.target.value))}><option value={0}>Choose configuration</option>{configs.map((config) => <option key={config.id} value={config.snapshot.id}>{config.name}</option>)}</select></label>
      <button className="secondary-action" disabled={loading || !left || !right || left === right} onClick={() => void compare()}>Compare</button>
    </div>
    {error && <p className="evals-error">{error}</p>}
    {differences && <><p className="verdict-context">{differences.length > 1 ? `${differences.length} dimensions differ. Results cannot isolate the effect of a single change.` : differences.length === 1 ? 'One snapshot dimension differs.' : 'Snapshots have identical captured inputs.'}</p>{differences.map((difference) => <article className="config-difference" key={difference.field}><h3>{difference.field.replaceAll('_', ' ')}</h3><div><pre>A: {JSON.stringify(difference.left, null, 2)}</pre><pre>B: {JSON.stringify(difference.right, null, 2)}</pre></div></article>)}</>}
  </section>
}
