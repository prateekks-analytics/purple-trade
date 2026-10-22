import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api'
import type { DeskBacktest, DeskTrade, DeskView } from '../types'
import { fmtMoney } from '../lib/tree'
import { errText } from './AgentBits'
import { IconBolt, IconNews, IconShield, IconTrend, IconWave } from './Icons'
import { LineChart } from './LineChart'
import type { Marker } from './LineChart'

export const AGENT_ICON: Record<string, ReactNode> = {
  momentum: <IconBolt />, trend: <IconTrend />, dip: <IconWave />, news: <IconNews />, guard: <IconShield />,
}

export function AgentMark({ id, size = 'md' }: { id: string; size?: 'sm' | 'md' | 'lg' }) {
  return <span className={`agent-mark a-${id} ${size}`} aria-hidden="true">{AGENT_ICON[id]}</span>
}

/** The bot's state, refreshed every 30 s while the tab is visible (decisions happen every 30 minutes). */
export function useDesk() {
  const [view, setView] = useState<DeskView | null>(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    const load = (first = false) => {
      if (first || !document.hidden) api.desk().then(v => { if (alive) { setView(v); setError('') } }).catch(e => alive && setError(errText(e)))
    }
    load(true)
    const t = setInterval(load, 30_000)
    return () => { alive = false; clearInterval(t) }
  }, [tick])
  return { view, setView, error, reload: () => setTick(t => t + 1) }
}

export function useBacktest(days = 40, capital = 500000) {
  const [bt, setBt] = useState<DeskBacktest | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    setBt(null)
    api.deskBacktest(days, capital).then(b => alive && setBt(b)).catch(e => alive && setError(errText(e)))
    return () => { alive = false }
  }, [days, capital])
  return { bt, error }
}

export const signed = (v: number) => `${v >= 0 ? '+' : '−'}${fmtMoney(Math.abs(v))}`
export const pct = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}%`
export const clock = (t: string) => t.slice(11, 16)
export const dayLabel = (t: string) => new Date(`${t.slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
export const when = (t: string) => `${dayLabel(t)}, ${clock(t)}`
/** Decisions are stored under the 30-minute bar they read; they are made when that bar closes, 30 minutes later. */
export const decidedAt = (t: string) => {
  const [h, m] = t.slice(11, 16).split(':').map(Number)
  const mins = h * 60 + m + 30
  return `${dayLabel(t)}, ${String(Math.floor(mins / 60)).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}`
}

/** Portfolio against NIFTY 50 on the same money, with a marker for every bar in which the bot traded. */
export function PortfolioChart({ series, trades = [], height = 300, label = 'Your bot' }: {
  series: { time: string; value: number; market: number }[]
  trades?: DeskTrade[]
  height?: number
  label?: string
}) {
  const idx = new Map(series.map((s, i) => [s.time, i]))
  const byBar = new Map<number, DeskTrade[]>()
  for (const t of trades) {
    const i = idx.get(t.time)
    if (i !== undefined) byBar.set(i, [...(byBar.get(i) ?? []), t])
  }
  const markers: Marker[] = [...byBar.entries()].map(([i, ts]) => ({
    index: i, value: series[i].value, kind: ts.some(t => t.side === 'BUY') ? 'buy' : 'sell',
    label: ts.map(t => `${t.side === 'BUY' ? 'Bought' : 'Sold'} ${t.qty} ${t.symbol}`).join(', '),
  }))
  return (
    <LineChart dates={series.map(s => s.time)} height={height} format={v => fmtMoney(v)} baseline={series[0]?.market}
      ariaLabel={`${label} against NIFTY 50`} markers={markers}
      series={[{ key: 'bot', label, color: 'var(--series-1)', values: series.map(s => s.value) },
        { key: 'mkt', label: 'NIFTY 50, same money', color: 'var(--series-2)', values: series.map(s => s.market), dashed: true }]} />
  )
}
