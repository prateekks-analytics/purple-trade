import { useMemo } from 'react'
import { Background, Controls, MarkerType, Position, ReactFlow, type Edge, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { Condition, Operand, Strategy } from '../types'
import { OP_LABEL, relationKey } from '../lib/tree'

const AGO = (n: number) => (n === 0 ? '' : n === 1 ? ' (yesterday)' : ` (${n}d ago)`)

function opText(o: Operand): string {
  switch (o.kind) {
    case 'price': return o.field[0].toUpperCase() + o.field.slice(1) + AGO(o.offset)
    case 'indicator': return `${o.name.toUpperCase()}(${o.period})${o.source !== 'close' ? ' of ' + o.source : ''}${AGO(o.offset)}`
    case 'const': return String(o.value)
    case 'position': return o.field === 'bars_held' ? 'Days held' : 'Trade P&L %'
  }
}

const COL = 250
const ROW = 76

function layout(root: Condition, side: 'entry' | 'exit', yStart: number) {
  const nodes: Node[] = []
  const edges: Edge[] = []
  let leafRow = 0
  const height = (c: Condition): number =>
    c.kind === 'all' || c.kind === 'any' ? 1 + Math.max(...c.items.map(height)) : c.kind === 'not' ? 1 + height(c.item) : 0
  const H = height(root)

  const place = (c: Condition, id: string): { id: string; y: number } => {
    const x = height(c) * COL  // leaves at the left, each logic level one column to the right
    if (c.kind === 'compare' || c.kind === 'cross') {
      const y = yStart + leafRow++ * ROW
      nodes.push({ id, position: { x: 0, y }, data: { label: `${opText(c.left)} ${OP_LABEL[relationKey(c)]} ${opText(c.right)}` },
        className: 'g-node cond', sourcePosition: Position.Right, targetPosition: Position.Left })
      return { id, y }
    }
    const kids = c.kind === 'not' ? [c.item] : c.items
    const placed = kids.map((k, i) => place(k, `${id}.${i}`))
    const y = placed.reduce((s, p) => s + p.y, 0) / placed.length
    const label = c.kind === 'all' ? 'AND' : c.kind === 'any' ? 'OR' : 'NOT'
    nodes.push({ id, position: { x, y }, data: { label }, className: `g-node logic ${c.kind}`,
      sourcePosition: Position.Right, targetPosition: Position.Left })
    for (const p of placed) edges.push({ id: `${p.id}->${id}`, source: p.id, target: id, type: 'smoothstep' })
    return { id, y }
  }

  const top = place(root, side)
  const actionId = `${side}-action`
  nodes.push({ id: actionId, position: { x: (H + 1) * COL, y: top.y }, data: { label: side === 'entry' ? '▲ BUY at next open' : '▼ SELL at next open' },
    className: `g-node action ${side}`, targetPosition: Position.Left, sourcePosition: Position.Right })
  edges.push({ id: `${top.id}->${actionId}`, source: top.id, target: actionId, type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed }, className: `edge-${side}` })
  return { nodes, edges, bottom: yStart + Math.max(leafRow, 1) * ROW }
}

export function GraphView({ strategy }: { strategy: Strategy }) {
  const { nodes, edges } = useMemo(() => {
    const a = layout(strategy.entry, 'entry', 0)
    const b = layout(strategy.exit, 'exit', a.bottom + 50)
    const link: Edge = { id: 'buy->sell', source: 'entry-action', target: 'exit-action', type: 'smoothstep',
      label: 'while holding', className: 'edge-hold', animated: true }
    return { nodes: [...a.nodes, ...b.nodes], edges: [...a.edges, ...b.edges, link] }
  }, [strategy])

  return (
    <div className="graph" aria-label="Strategy as a flow diagram">
      <ReactFlow nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: 0.15 }}
        nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
        proOptions={{ hideAttribution: true }} minZoom={0.3} maxZoom={1.5}>
        <Background gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
      <p className="graph-note">Read-only picture of the rules. Edit in the Rules view or by chatting.</p>
    </div>
  )
}
