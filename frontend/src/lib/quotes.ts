import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Quote } from '../types'

/** Delayed quotes shared by every component: one Yahoo call per symbol per minute at most. */
const cache = new Map<string, { at: number; q: Quote | null; p?: Promise<Quote | null> }>()
const TTL = 60_000
const POLL = 120_000

function fetchQuote(sym: string): Promise<Quote | null> {
  const hit = cache.get(sym)
  if (hit?.p) return hit.p
  if (hit && Date.now() - hit.at < TTL) return Promise.resolve(hit.q)
  const p = api.marketQuote(sym).then(q => q, () => null).then(q => { cache.set(sym, { at: Date.now(), q }); return q })
  cache.set(sym, { at: hit?.at ?? 0, q: hit?.q ?? null, p })
  return p
}

export const cachedQuote = (sym: string) => cache.get(sym)?.q ?? null

/** Quotes for a list of symbols, refreshed every two minutes while the tab is visible. */
export function useQuotes(symbols: string[]) {
  const key = symbols.join(',')
  const [quotes, setQuotes] = useState<Record<string, Quote | null | undefined>>(() =>
    Object.fromEntries(symbols.map(s => [s, cache.get(s)?.p ? undefined : cache.has(s) ? cachedQuote(s) : undefined])))
  useEffect(() => {
    let alive = true
    const list = key ? key.split(',') : []
    const load = (first = false) => {
      if (!first && document.hidden) return
      list.forEach(s => fetchQuote(s).then(q => { if (alive) setQuotes(prev => (prev[s] === q ? prev : { ...prev, [s]: q })) }))
    }
    load(true)
    const t = setInterval(load, POLL)
    return () => { alive = false; clearInterval(t) }
  }, [key])
  return quotes
}

const WL_KEY = 'purple.watchlist'
export const DEFAULT_WATCH = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK', 'SBIN', 'ITC', 'LT']

export function readWatchlist(): string[] {
  try { const v = JSON.parse(localStorage.getItem(WL_KEY) ?? 'null'); if (Array.isArray(v) && v.every(x => typeof x === 'string')) return v } catch { /* ignore */ }
  return DEFAULT_WATCH
}
export function writeWatchlist(list: string[]) {
  try { localStorage.setItem(WL_KEY, JSON.stringify(list)) } catch { /* private mode */ }
}

/** First-run checklist flags (per browser). */
export function markDone(step: 'agent' | 'test') {
  try { localStorage.setItem(`purple.done.${step}`, '1') } catch { /* ignore */ }
  window.dispatchEvent(new Event('purple:done'))
}
export function isDone(step: 'agent' | 'test') {
  try { return localStorage.getItem(`purple.done.${step}`) === '1' } catch { return false }
}
