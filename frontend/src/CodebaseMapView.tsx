import { FileCode2, X } from 'lucide-react'
import type { CodebaseMap } from './runtime'

type Props = { map: CodebaseMap; onClose: () => void; onOpenFile: (path: string) => void }

export function CodebaseMapView({ map, onClose, onOpenFile }: Props) {
  const positions = new Map(map.nodes.map((node, index) => {
    const angle = -Math.PI / 2 + 2 * Math.PI * index / map.nodes.length
    return [node.id, { x: 490 + 355 * Math.cos(angle), y: 320 + 225 * Math.sin(angle) }] as const
  }))
  return <div className="modal-backdrop map-backdrop" onClick={onClose}>
    <section className="map-modal" role="dialog" aria-modal="true" aria-labelledby="map-title" onClick={(event) => event.stopPropagation()}>
      <div className="map-modal-header"><div><span className="eyebrow">Saved artifact</span><h2 id="map-title">Codebase map</h2><p>Components and relationships identified from inspected files.</p></div><button className="icon-button" aria-label="Close codebase map" onClick={onClose}><X size={17} /></button></div>
      <div className="map-scroll"><div className="map-canvas">
        <svg className="map-lines" viewBox="0 0 980 640" aria-hidden="true">
          {map.nodes.map((node) => { const point = positions.get(node.id)!; return <line className="map-spoke" key={`spoke-${node.id}`} x1="490" y1="320" x2={point.x} y2={point.y} /> })}
          {map.edges.map((edge, index) => { const source = positions.get(edge.source); const target = positions.get(edge.target); return source && target ? <line className="map-edge" key={`${edge.source}-${edge.target}-${index}`} x1={source.x} y1={source.y} x2={target.x} y2={target.y} /> : null })}
        </svg>
        <div className="map-hub">CODEBASE</div>
        {map.nodes.map((node) => { const point = positions.get(node.id)!; return <article className="map-node" key={node.id} style={{ left: point.x, top: point.y }}><strong>{node.label}</strong><p>{node.summary}</p><div className="map-node-files">{node.files.map((file) => <button key={file} title={`Reveal ${file}`} onClick={() => onOpenFile(file)}><FileCode2 size={11} /> {file}</button>)}</div></article> })}
      </div></div>
      <div className="map-relations"><strong>Relationships</strong>{map.edges.length ? <div>{map.edges.map((edge, index) => <span key={`${edge.source}-${edge.target}-${index}`}>{map.nodes.find((node) => node.id === edge.source)?.label} <b>→</b> {map.nodes.find((node) => node.id === edge.target)?.label}: {edge.label}</span>)}</div> : <p>No relationships were specified.</p>}</div>
    </section>
  </div>
}
