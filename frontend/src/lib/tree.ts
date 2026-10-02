import type { Condition, Operand, Strategy } from '../types'

export const OPERAND_CHOICES = [
  { key: 'close', label: 'Close', group: 'Price' },
  { key: 'open', label: 'Open', group: 'Price' },
  { key: 'high', label: 'High', group: 'Price' },
  { key: 'low', label: 'Low', group: 'Price' },
  { key: 'volume', label: 'Volume', group: 'Price' },
  { key: 'sma', label: 'SMA', group: 'Indicator' },
  { key: 'ema', label: 'EMA', group: 'Indicator' },
  { key: 'rsi', label: 'RSI', group: 'Indicator' },
  { key: 'highest', label: 'Highest', group: 'Indicator' },
  { key: 'lowest', label: 'Lowest', group: 'Indicator' },
  { key: 'const', label: 'Number', group: 'Value' },
  { key: 'bars_held', label: 'Days held', group: 'Open trade' },
  { key: 'pnl_pct', label: 'Trade P&L %', group: 'Open trade' },
] as const

export type OperandKey = (typeof OPERAND_CHOICES)[number]['key']

const DEFAULT_PERIOD: Record<string, number> = { sma: 20, ema: 20, rsi: 14, highest: 20, lowest: 20 }

export function operandKey(o: Operand): OperandKey {
  switch (o.kind) {
    case 'price': return o.field
    case 'indicator': return o.name
    case 'const': return 'const'
    case 'position': return o.field
  }
}

export function makeOperand(key: OperandKey, prev?: Operand): Operand {
  const offset = prev && (prev.kind === 'price' || prev.kind === 'indicator') ? prev.offset : 0
  switch (key) {
    case 'close': case 'open': case 'high': case 'low': case 'volume':
      return { kind: 'price', field: key, offset }
    case 'sma': case 'ema': case 'rsi': case 'highest': case 'lowest': {
      const period = prev?.kind === 'indicator' ? prev.period : DEFAULT_PERIOD[key]
      const source = prev?.kind === 'indicator' ? prev.source : (key === 'highest' ? 'high' : key === 'lowest' ? 'low' : 'close')
      return { kind: 'indicator', name: key, period, source, offset }
    }
    case 'const':
      return { kind: 'const', value: prev?.kind === 'const' ? prev.value : 0 }
    case 'bars_held': case 'pnl_pct':
      return { kind: 'position', field: key }
  }
}

export const OP_LABEL: Record<string, string> = {
  '<': '<', '<=': '≤', '==': '=', '!=': '≠', '>=': '≥', '>': '>',
  'cross:above': 'crosses above', 'cross:below': 'crosses below',
}

export function relationKey(c: Condition): string {
  if (c.kind === 'compare') return c.op
  if (c.kind === 'cross') return `cross:${c.direction}`
  return ''
}

export function setRelation(c: Condition, key: string): Condition {
  if (c.kind !== 'compare' && c.kind !== 'cross') return c
  if (key.startsWith('cross:')) {
    return { kind: 'cross', left: c.left, right: c.right, direction: key.slice(6) as 'above' | 'below' }
  }
  return { kind: 'compare', left: c.left, right: c.right, op: key as never }
}

export function newRule(side: 'entry' | 'exit'): Condition {
  return side === 'exit'
    ? { kind: 'compare', left: { kind: 'position', field: 'pnl_pct' }, op: '<=', right: { kind: 'const', value: -2 } }
    : { kind: 'compare', left: { kind: 'price', field: 'close', offset: 0 }, op: '>', right: makeOperand('sma') }
}

export function blankStrategy(name = 'Untitled strategy'): Strategy {
  return {
    name,
    entry: { kind: 'all', items: [newRule('entry')] },
    exit: { kind: 'any', items: [newRule('exit')] },
    sizing: { mode: 'percent_equity', value: 100 },
    costs: { fee_bps: 3, slippage_bps: 5 },
    initial_capital: 100000,
    questions: [],
  }
}

/** Convert every 'crosses' rule to a plain comparison (state, not event). */
export function crossesToCompare(c: Condition): Condition {
  switch (c.kind) {
    case 'cross': return { kind: 'compare', left: c.left, right: c.right, op: c.direction === 'above' ? '>' : '<' }
    case 'all': case 'any': return { ...c, items: c.items.map(crossesToCompare) }
    case 'not': return { ...c, item: crossesToCompare(c.item) }
    default: return c
  }
}

/** Wrap a single rule in a group so users can always add siblings. */
export function asGroup(c: Condition, kind: 'all' | 'any'): Condition {
  return c.kind === 'all' || c.kind === 'any' ? c : { kind, items: [c] }
}

export function lineDiff(before: string[] = [], after: string[] = []) {
  const b = new Set(before.map(l => l.trim()))
  const a = new Set(after.map(l => l.trim()))
  return {
    added: after.filter(l => !b.has(l.trim())).map(l => l.trim()),
    removed: before.filter(l => !a.has(l.trim())).map(l => l.trim()),
  }
}

export const fmtPct = (v: number | null | undefined, sign = true) =>
  v === null || v === undefined ? '—' : `${sign && v > 0 ? '+' : ''}${v.toFixed(2)}%`

export const fmtMoney = (v: number) =>
  '₹' + v.toLocaleString('en-IN', { maximumFractionDigits: 0 })
