import { useEffect, useState } from 'react'
import { api } from '../api'
import type { PaperAccount, PaperView } from '../types'

const HIDDEN = new Set(['tradingagents'])  // the hidden Analyst Team rebuild

export interface Holding { account: PaperAccount; view: PaperView | null }

/** All visible paper accounts with their current view (value, trades, today's call). */
export function usePortfolio(refreshKey: unknown = 0) {
  const [rows, setRows] = useState<Holding[] | null>(null)
  useEffect(() => {
    let alive = true
    api.saPaperList().then(async list => {
      const shown = list.filter(a => !HIDDEN.has(a.agent_id))
      const views = await Promise.all(shown.map(a => api.saPaper(a.id).catch(() => null)))
      if (alive) setRows(shown.map((account, i) => ({ account, view: views[i] })))
    }).catch(() => alive && setRows([]))
    return () => { alive = false }
  }, [refreshKey])
  return rows
}

export function totals(rows: Holding[] | null) {
  if (!rows) return null
  let value = 0, start = 0, prev = 0
  for (const { view } of rows) {
    if (!view) continue
    const eq = view.result.equity
    value += view.result.metrics.end_equity
    start += view.result.metrics.start_equity
    prev += eq.length > 1 ? eq[eq.length - 2].equity : view.result.metrics.start_equity
  }
  return { value, start, change: value - start, changePct: start ? (value / start - 1) * 100 : 0, day: value - prev }
}

/** NSE regular session, Mon–Fri 09:15–15:30 IST. Exchange holidays are not checked. */
export function nseStatus(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(now)
  const get = (t: string) => parts.find(p => p.type === t)?.value ?? ''
  const mins = Number(get('hour')) * 60 + Number(get('minute'))
  const open = !['Sat', 'Sun'].includes(get('weekday')) && mins >= 555 && mins < 930
  return { open, label: open ? 'NSE open' : 'NSE closed', time: `${get('hour')}:${get('minute')} IST` }
}
