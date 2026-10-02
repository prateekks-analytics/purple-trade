import type { Condition, Operand } from '../types'
import {
  OPERAND_CHOICES, OP_LABEL, asGroup, makeOperand, newRule, operandKey, relationKey, setRelation,
  type OperandKey,
} from '../lib/tree'

type Side = 'entry' | 'exit'

function OperandControl({ value, side, onChange, label }: {
  value: Operand; side: Side; onChange: (o: Operand) => void; label: string
}) {
  const key = operandKey(value)
  const choices = OPERAND_CHOICES.filter(c => side === 'exit' || c.group !== 'Open trade')
  const groups = [...new Set(choices.map(c => c.group))]
  return (
    <span className="operand">
      <select aria-label={`${label}: value type`} className="chip-select" value={key}
        onChange={e => onChange(makeOperand(e.target.value as OperandKey, value))}>
        {groups.map(g => (
          <optgroup key={g} label={g}>
            {choices.filter(c => c.group === g).map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
          </optgroup>
        ))}
      </select>
      {value.kind === 'indicator' && (
        <label className="mini">
          <span className="paren">(</span>
          <input aria-label={`${label}: period`} type="number" min={1} max={500} value={value.period}
            onChange={e => onChange({ ...value, period: clampInt(e.target.value, 1, 500) })} />
          <span className="paren">)</span>
        </label>
      )}
      {value.kind === 'indicator' && (value.name === 'highest' || value.name === 'lowest') && (
        <select aria-label={`${label}: of`} className="chip-select subtle" value={value.source}
          onChange={e => onChange({ ...value, source: e.target.value as never })}>
          {['high', 'low', 'close', 'open'].map(s => <option key={s} value={s}>of {s}</option>)}
        </select>
      )}
      {value.kind === 'const' && (
        <input aria-label={`${label}: number`} className="num" type="number" step="any" value={value.value}
          onChange={e => onChange({ ...value, value: Number(e.target.value) })} />
      )}
      {(value.kind === 'price' || value.kind === 'indicator') && (
        <select aria-label={`${label}: when`} className="chip-select subtle" value={value.offset}
          onChange={e => onChange({ ...value, offset: Number(e.target.value) })}>
          <option value={0}>today</option>
          <option value={1}>yesterday</option>
          {[2, 3, 5, 10, 20].map(n => <option key={n} value={n}>{n} days ago</option>)}
        </select>
      )}
    </span>
  )
}

function clampInt(v: string, lo: number, hi: number) {
  const n = Math.round(Number(v) || lo)
  return Math.min(hi, Math.max(lo, n))
}

function ConstUnitHint({ c }: { c: Condition }) {
  if (c.kind !== 'compare' || c.right.kind !== 'const' || c.left.kind !== 'position') return null
  return <span className="unit">{c.left.field === 'pnl_pct' ? '%' : 'days'}</span>
}

function Rule({ value, side, onChange, onRemove, canRemove, path }: {
  value: Condition; side: Side; onChange: (c: Condition) => void; onRemove: () => void; canRemove: boolean; path: string
}) {
  if (value.kind === 'all' || value.kind === 'any') {
    return <Group value={value} side={side} onChange={onChange} onRemove={onRemove} canRemove={canRemove} path={path} />
  }
  if (value.kind === 'not') {
    return (
      <div className="rule not">
        <span className="kw">NOT</span>
        <Rule value={value.item} side={side} path={path + '.n'} canRemove={false}
          onChange={item => onChange({ ...value, item })} onRemove={onRemove} />
        <button className="icon-btn not-btn" title="Remove NOT" onClick={() => onChange(value.item)}>undo NOT</button>
      </div>
    )
  }
  const rel = relationKey(value)
  return (
    <div className="rule">
      <OperandControl label={`${path} left`} value={value.left} side={side} onChange={left => onChange({ ...value, left } as Condition)} />
      <select aria-label={`${path} comparison`} className="chip-select rel" value={rel}
        onChange={e => onChange(setRelation(value, e.target.value))}>
        {Object.entries(OP_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
      <OperandControl label={`${path} right`} value={value.right} side={side} onChange={right => onChange({ ...value, right } as Condition)} />
      <ConstUnitHint c={value} />
      <span className="rule-actions">
        <button className="icon-btn not-btn" title="Invert this rule (NOT)" onClick={() => onChange({ kind: 'not', item: value })}>NOT</button>
        {canRemove && <button className="icon-btn" title="Remove rule" aria-label="Remove rule" onClick={onRemove}>×</button>}
      </span>
    </div>
  )
}

function Group({ value, side, onChange, onRemove, canRemove, path }: {
  value: Extract<Condition, { kind: 'all' | 'any' }>; side: Side
  onChange: (c: Condition) => void; onRemove: () => void; canRemove: boolean; path: string
}) {
  const set = (i: number, c: Condition) => onChange({ ...value, items: value.items.map((x, j) => (j === i ? c : x)) })
  const remove = (i: number) => {
    const items = value.items.filter((_, j) => j !== i)
    if (items.length) onChange({ ...value, items })
    else onRemove()
  }
  return (
    <div className={`group ${value.kind}`}>
      {value.items.length > 1 && (
        <div className="group-head">
          <button className="join-toggle" onClick={() => onChange({ ...value, kind: value.kind === 'all' ? 'any' : 'all' })}
            title="Switch between ALL (and) and ANY (or)">
            {value.kind === 'all' ? 'ALL of these' : 'ANY of these'} <span aria-hidden>⇄</span>
          </button>
          {canRemove && <button className="icon-btn" title="Remove group" onClick={onRemove}>×</button>}
        </div>
      )}
      <div className="group-items">
        {value.items.map((c, i) => (
          <div className="group-item" key={i}>
            {i > 0 && <span className="joiner">{value.kind === 'all' ? 'and' : 'or'}</span>}
            <Rule value={c} side={side} path={`${path}.${i}`} canRemove={value.items.length > 1 || canRemove}
              onChange={x => set(i, x)} onRemove={() => remove(i)} />
          </div>
        ))}
      </div>
      <div className="group-add">
        <button className="link-btn" onClick={() => onChange({ ...value, items: [...value.items, newRule(side)] })}>+ rule</button>
        <button className="link-btn" onClick={() => onChange({
          ...value, items: [...value.items, { kind: value.kind === 'all' ? 'any' : 'all', items: [newRule(side), newRule(side)] }],
        })}>+ {value.kind === 'all' ? 'OR' : 'AND'} group</button>
      </div>
    </div>
  )
}

export function RuleEditor({ side, value, onChange }: { side: Side; value: Condition; onChange: (c: Condition) => void }) {
  const root = asGroup(value, side === 'entry' ? 'all' : 'any')
  return (
    <section className={`rule-block ${side}`} aria-label={side === 'entry' ? 'Buy rules' : 'Sell rules'}>
      <header>
        <span className={`action-tag ${side}`}>{side === 'entry' ? '▲ BUY' : '▼ SELL'}</span>
        <span className="when">{side === 'entry' ? 'when (checked at each close, while not holding)' : 'when (checked at each close, while holding)'}</span>
      </header>
      <Rule value={root} side={side} path={side} canRemove={false} onChange={onChange} onRemove={() => {}} />
    </section>
  )
}
