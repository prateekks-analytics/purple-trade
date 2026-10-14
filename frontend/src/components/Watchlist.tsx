import { useEffect, useState } from 'react'
import { readWatchlist, useQuotes, writeWatchlist } from '../lib/quotes'
import { fmtPct } from '../lib/tree'
import { IconPlus, IconSpark } from './Icons'

/** Kite-style watchlist: live (delayed) prices, hover actions, add and remove symbols. */
export function Watchlist() {
  const [list, setList] = useState(readWatchlist)
  const [adding, setAdding] = useState('')
  const quotes = useQuotes(list)
  useEffect(() => { const f = () => setList(readWatchlist()); window.addEventListener('purple:watchlist', f); return () => window.removeEventListener('purple:watchlist', f) }, [])
  const save = (next: string[]) => { setList(next); writeWatchlist(next) }
  const add = () => {
    const s = adding.trim().toUpperCase().replace(/[^A-Z0-9&.^-]/g, '').replace(/\.NS$/, '')
    if (s && !list.includes(s)) save([s, ...list].slice(0, 20))
    setAdding('')
  }

  return (
    <section className="watchlist panel" aria-labelledby="wl-h">
      <div className="wl-head">
        <h2 id="wl-h" className="panel-title">Watchlist</h2>
        <span className="sub">{list.length} stocks</span>
      </div>
      <form className="wl-add" onSubmit={e => { e.preventDefault(); add() }}>
        <IconPlus />
        <label htmlFor="wl-add" className="visually-hidden">Add a stock</label>
        <input id="wl-add" value={adding} onChange={e => setAdding(e.target.value.toUpperCase())} placeholder="Add a stock, e.g. ITC" autoComplete="off" spellCheck={false} />
      </form>
      <ul className="wl-list">
        {list.map(sym => {
          const q = quotes[sym]
          const chg = q?.change_pct
          const tone = chg == null ? '' : chg > 0 ? 'pos' : chg < 0 ? 'neg' : ''
          return (
            <li key={sym} className="wl-row">
              <span className="wl-sym">
                <b className={tone}>{sym}</b>
                <small>{q?.name ?? (q === null ? 'No price' : '…')}</small>
              </span>
              <span className="wl-px">
                <b className="num">{q ? q.price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</b>
                <small className={`num ${tone}`}>{chg == null ? '' : `${chg > 0 ? '▲' : chg < 0 ? '▼' : ''} ${fmtPct(chg)}`}</small>
              </span>
              <span className="wl-actions">
                <a className="wl-btn ask" href={`#/agent/${sym}`} title={`Ask the agent about ${sym}`}><IconSpark /><span>Ask</span></a>
                <button className="wl-btn" onClick={() => save(list.filter(x => x !== sym))} aria-label={`Remove ${sym} from the watchlist`} title="Remove">×</button>
              </span>
            </li>
          )
        })}
      </ul>
      <p className="wl-foot">Yahoo Finance, about 15 minutes delayed.</p>
    </section>
  )
}
