import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from '../api'
import type { PaperAccount, SuperAgentInfo } from '../types'
import { readWatchlist, cachedQuote, writeWatchlist } from '../lib/quotes'
import { fmtPct } from '../lib/tree'
import { BotBadge } from './Desk'
import { IconBuild, IconMoon, IconOverview, IconPaper, IconPlus, IconSpark, IconTest } from './Icons'

interface Item { id: string; group: string; label: string; hint?: string; icon: ReactNode; run: () => void; tone?: string }

/** Ctrl+K: search a stock (ask the agent about it) or jump anywhere. */
export function Palette({ open, onClose, onTheme, onConnectAi }: { open: boolean; onClose: () => void; onTheme: () => void; onConnectAi: () => void }) {
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const [bots, setBots] = useState<SuperAgentInfo[]>([])
  const [accounts, setAccounts] = useState<PaperAccount[]>([])
  const input = useRef<HTMLInputElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const d = dialog.current
    if (!d) return
    if (open && !d.open) {
      d.showModal(); setQ(''); setSel(0)
      api.saAgents().then(a => setBots(a.filter(x => x.kind === 'rules' && !x.hidden))).catch(() => {})
      api.saPaperList().then(a => setAccounts(a.filter(x => x.agent_id !== 'tradingagents'))).catch(() => {})
      setTimeout(() => input.current?.focus(), 0)
    } else if (!open && d.open) d.close()
  }, [open])

  const go = (hash: string) => () => { location.hash = hash; onClose() }
  const items = useMemo<Item[]>(() => {
    const s = q.trim().toUpperCase().replace(/[^A-Z0-9&.^-]/g, '')
    const match = (t: string) => !q.trim() || t.toLowerCase().includes(q.trim().toLowerCase())
    const out: Item[] = []
    const watch = readWatchlist()
    const stocks = s ? [s, ...watch.filter(w => w !== s && w.startsWith(s))].slice(0, 5) : watch.slice(0, 5)
    for (const sym of stocks) {
      const qt = cachedQuote(sym)
      out.push({ id: `ask-${sym}`, group: 'Stocks', label: `Should I buy ${sym}?`, hint: qt?.change_pct != null ? `₹${qt.price.toLocaleString('en-IN')} ${fmtPct(qt.change_pct)}` : 'Ask the agent',
        tone: qt?.change_pct != null ? (qt.change_pct >= 0 ? 'pos' : 'neg') : undefined, icon: <span className="pal-sym">{sym.slice(0, 2)}</span>, run: go(`#/agent/${sym}`) })
    }
    if (s && !watch.includes(s)) {
      out.push({ id: `wl-${s}`, group: 'Stocks', label: `Add ${s} to the watchlist`, icon: <IconPlus />,
        run: () => { writeWatchlist([s, ...watch].slice(0, 20)); window.dispatchEvent(new Event('purple:watchlist')); onClose() } })
    }
    const pages: Item[] = [
      { id: 'p-home', group: 'Go to', label: 'Home', icon: <IconOverview />, run: go('#/') },
      { id: 'p-agent', group: 'Go to', label: 'Ask the agent', icon: <IconSpark />, run: go('#/agent') },
      { id: 'p-test', group: 'Go to', label: 'Test a rule bot', icon: <IconTest />, run: go('#/test') },
      { id: 'p-build', group: 'Go to', label: 'Build a bot', icon: <IconBuild />, run: go('#/build') },
      { id: 'p-paper', group: 'Go to', label: 'Paper accounts', icon: <IconPaper />, run: go('#/paper') },
    ]
    out.push(...pages.filter(p => match(p.label)))
    out.push(...bots.filter(b => match(b.title)).map(b => ({ id: `b-${b.id}`, group: 'Rule bots', label: b.title, hint: 'Test', icon: <BotBadge id={b.id} size="sm" />, run: go(`#/test/${b.id}`) })))
    out.push(...accounts.filter(a => match(a.name)).slice(0, 6).map(a => ({ id: `a-${a.id}`, group: 'Paper accounts', label: a.name, icon: <IconPaper />, run: go(`#/paper/${a.id}`) })))
    const actions: Item[] = [
      { id: 'x-ai', group: 'Settings', label: 'Connect or change the AI', icon: <IconSpark />, run: () => { onClose(); onConnectAi() } },
      { id: 'x-theme', group: 'Settings', label: 'Switch light / dark theme', icon: <IconMoon />, run: () => { onClose(); onTheme() } },
    ]
    out.push(...actions.filter(a => match(a.label)))
    return out
  }, [q, bots, accounts]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { setSel(0) }, [q])
  useEffect(() => { document.getElementById(`pal-${items[sel]?.id}`)?.scrollIntoView({ block: 'nearest' }) }, [sel, items])

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel(i => Math.min(items.length - 1, i + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(i => Math.max(0, i - 1)) }
    else if (e.key === 'Enter') { e.preventDefault(); items[sel]?.run() }
  }

  let lastGroup = ''
  return (
    <dialog ref={dialog} className="palette" onClose={onClose} onClick={e => { if (e.target === dialog.current) onClose() }} aria-label="Search">
      <div className="pal-box">
        <div className="pal-input">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
          <input ref={input} value={q} onChange={e => setQ(e.target.value)} onKeyDown={onKey} placeholder="Search a stock, bot or page" aria-label="Search"
            role="combobox" aria-expanded="true" aria-controls="pal-list" aria-activedescendant={items[sel] ? `pal-${items[sel].id}` : undefined} autoComplete="off" spellCheck={false} />
          <kbd>Esc</kbd>
        </div>
        <ul className="pal-list" id="pal-list" role="listbox">
          {items.map((it, i) => {
            const head = it.group !== lastGroup ? it.group : null
            lastGroup = it.group
            return [
              head && <li key={`g-${head}`} className="pal-group" role="presentation">{head}</li>,
              <li key={it.id} id={`pal-${it.id}`} role="option" aria-selected={i === sel} className={`pal-item ${i === sel ? 'on' : ''}`}
                onMouseMove={() => setSel(i)} onClick={it.run}>
                <span className="pal-icon">{it.icon}</span>
                <span className="pal-label">{it.label}</span>
                {it.hint && <span className={`pal-hint ${it.tone ?? ''}`}>{it.hint}</span>}
              </li>,
            ]
          })}
          {items.length === 0 && <li className="pal-empty">Nothing matches. Try a stock symbol like INFY.</li>}
        </ul>
        <p className="pal-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span></p>
      </div>
    </dialog>
  )
}
