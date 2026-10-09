import { useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { BacktestResult, Dataset } from '../types'
import { fmtMoney, fmtPct } from '../lib/tree'
import { readVerdict } from '../lib/verdict'
import { LineChart, type Marker } from './LineChart'

export function DataPicker({ datasets, value, onChange, onUploaded, label = 'Price data' }: {
  datasets: Dataset[]; value: string | null; onChange: (id: string) => void; onUploaded: (d: Dataset) => void; label?: string
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [symbol, setSymbol] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'err' | 'ok'; text: string } | null>(null)
  const current = datasets.find(d => d.id === value)

  const upload = async () => {
    const f = fileRef.current?.files?.[0]
    if (!f) { setMsg({ kind: 'err', text: 'Choose a CSV file first.' }); return }
    setBusy(true); setMsg(null)
    try {
      const d = await api.uploadDataset(f, symbol, note)
      onUploaded(d)
      setMsg({ kind: 'ok', text: `Imported ${d.rows} trading days, ${d.first_date} to ${d.last_date}.${d.warnings?.length ? ' ' + d.warnings.join(' ') : ''}` })
      setOpen(false)
    } catch (e) {
      setMsg({ kind: 'err', text: e instanceof ApiError ? e.message : String(e) })
    } finally { setBusy(false) }
  }

  return (
    <div className="data-picker">
      <div className="field">
        <label htmlFor="dp-select">{label}</label>
        <div className="field-row">
          <select id="dp-select" value={value ?? ''} onChange={e => onChange(e.target.value)}>
            {datasets.map(d => <option key={d.id} value={d.id}>{d.synthetic ? 'Sample stock (synthetic prices)' : d.symbol ?? d.name}, {d.first_date} to {d.last_date}, {d.rows} days</option>)}
          </select>
          <button type="button" className="btn quiet" onClick={() => setOpen(o => !o)} aria-expanded={open}>Import NSE prices</button>
        </div>
        {current && (
          <p className={`field-note ${current.synthetic ? 'warn' : ''}`}>
            {current.synthetic ? 'Synthetic prices made for trying the app. Not market data.'
              : `Source you gave: ${current.source_note || 'not stated'}.`}
          </p>
        )}
      </div>
      {open && (
        <div className="upload-panel">
          <p className="field-note">Daily prices for one stock: the CSV from NSE's historical data page, or any file with date, open, high, low and close columns.</p>
          <div className="upload-row">
            <input ref={fileRef} type="file" accept=".csv,text/csv" aria-label="CSV file" />
            <input placeholder="Symbol, e.g. INFY" value={symbol} onChange={e => setSymbol(e.target.value)} aria-label="Symbol" />
            <input placeholder="Where it came from" value={note} onChange={e => setNote(e.target.value)} aria-label="Source of the prices" />
            <button type="button" className="btn" onClick={upload} disabled={busy}>{busy ? 'Importing…' : 'Import prices'}</button>
          </div>
        </div>
      )}
      {msg && <p className={msg.kind === 'err' ? 'error-text' : 'ok-text'} role="status">{msg.text}</p>}
    </div>
  )
}

export function VerdictPanel({ result, bot, stock }: { result: BacktestResult; bot: string; stock: string }) {
  const v = useMemo(() => readVerdict(result, bot, stock), [result, bot, stock])
  return (
    <section className={`verdict ${v.outcome}`} aria-label="Verdict">
      <p className="verdict-tag">{v.outcome === 'beat' ? '▲ Beat buy and hold' : v.outcome === 'lagged' ? '▼ Trailed buy and hold' : v.outcome === 'idle' ? '– No trades' : '= Matched buy and hold'}</p>
      <p className="verdict-headline">{v.headline}</p>
      <p className="verdict-money">{v.money}</p>
      <dl className="facts">
        {v.facts.map(f => (
          <div key={f.label} className="fact">
            <dt>{f.label}</dt>
            <dd className={`fact-value ${f.tone ?? ''}`}>{f.value}</dd>
            <dd className="fact-note">{f.note}</dd>
          </div>
        ))}
      </dl>
      <div className="meaning">
        <h3>What this means</h3>
        <ul>{v.meaning.map((m, i) => <li key={i}>{m}</li>)}</ul>
      </div>
    </section>
  )
}

const tone = (v: number | null | undefined) => (v === null || v === undefined ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : '')

export function ResultDetail({ result }: { result: BacktestResult }) {
  const [showAll, setShowAll] = useState(false)
  const [tab, setTab] = useState<'equity' | 'price' | 'trades'>('equity')

  const view = useMemo(() => {
    const eq = result.equity
    const dates = eq.map(e => e.date)
    const start = result.metrics.start_equity
    const first = eq[0]?.close ?? 1
    const idx = new Map(dates.map((d, i) => [d, i]))
    const markers: Marker[] = []
    for (const t of result.trades) {
      const i = idx.get(t.entry_date)
      if (i !== undefined) markers.push({ index: i, value: t.entry_price, kind: 'buy', label: `Bought ${t.qty} at ${t.entry_price.toFixed(2)}: ${t.entry_reason}` })
      if (t.exit_date) {
        const j = idx.get(t.exit_date)
        if (j !== undefined) markers.push({ index: j, value: t.exit_price ?? eq[j].close, kind: 'sell', label: `Sold at ${t.exit_price?.toFixed(2)}: ${t.exit_reason}` })
      }
    }
    return { dates, equity: eq.map(e => e.equity), bh: eq.map(e => (start * e.close) / first), close: eq.map(e => e.close), markers }
  }, [result])

  if (view.dates.length < 2) return <p className="field-note">The chart appears after the second trading day.</p>
  const trades = [...result.trades].reverse()
  const shown = showAll ? trades : trades.slice(0, 12)
  const tabs = [['equity', 'Account value'], ['price', 'Price and trades'], ['trades', `Trade list (${trades.length})`]] as const

  return (
    <section className="detail" aria-label="Backtest detail">
      <div className="tabs" role="tablist" aria-label="Result views">
        {tabs.map(([k, label]) => (
          <button key={k} role="tab" id={`tab-${k}`} aria-selected={tab === k} aria-controls={`panel-${k}`} className={tab === k ? 'on' : ''}
            tabIndex={tab === k ? 0 : -1} onClick={() => setTab(k)}
            onKeyDown={e => {
              const i = tabs.findIndex(t => t[0] === k)
              const j = e.key === 'ArrowRight' ? (i + 1) % tabs.length : e.key === 'ArrowLeft' ? (i + tabs.length - 1) % tabs.length : -1
              if (j < 0) return
              e.preventDefault(); setTab(tabs[j][0]); document.getElementById(`tab-${tabs[j][0]}`)?.focus()
            }}>{label}</button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="tab-panel">
        {tab === 'equity' && (
          <>
            <p className="chart-caption">What the account was worth each day, against buying on day one and holding. Hover or use the arrow keys for values.</p>
            <LineChart dates={view.dates} ariaLabel="Account value over time: this bot against buying and holding"
              series={[
                { key: 's', label: 'This bot', color: 'var(--series-1)', values: view.equity },
                { key: 'b', label: 'Buy and hold', color: 'var(--series-2)', values: view.bh, dashed: true },
              ]}
              baseline={result.metrics.start_equity} format={v => fmtMoney(v)} />
          </>
        )}
        {tab === 'price' && (
          <>
            <p className="chart-caption">Closing price with each purchase (▲ green) and sale (▼ red). Hover a marker to see which rule fired.</p>
            <LineChart dates={view.dates} ariaLabel="Closing price with buy and sell markers"
              series={[{ key: 'c', label: 'Close', color: 'var(--price-line)', values: view.close }]}
              markers={view.markers} format={v => v.toLocaleString('en-IN', { maximumFractionDigits: 0 })} />
          </>
        )}
        {tab === 'trades' && (trades.length === 0 ? (
          <p className="field-note">{result.strategy_hash === 'ai-team'
            ? 'No trades: the agent never decided to buy in this period.'
            : `No trades: the buy rules never matched on this data${result.warmup_bars ? ` (the first ${result.warmup_bars} days only warm up the indicators)` : ''}.`}</p>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th scope="col">Bought</th><th scope="col">Sold</th><th scope="col" className="r">Shares</th><th scope="col" className="r">Result</th><th scope="col" className="r">Days</th><th scope="col">Why it sold</th></tr>
                </thead>
                <tbody>
                  {shown.map((t, i) => (
                    <tr key={i} className={t.open ? 'open-row' : ''}>
                      <td title={t.entry_reason}><div>{t.entry_date}</div><div className="sub">at {t.entry_price.toFixed(2)}</div></td>
                      <td>{t.exit_date ? <><div>{t.exit_date}</div><div className="sub">at {t.exit_price?.toFixed(2)}</div></> : <span className="badge">Still open</span>}</td>
                      <td className="r">{t.qty}</td>
                      <td className={`r ${tone(t.pnl)}`}><div>{fmtPct(t.pnl_pct)}</div><div className="sub">{fmtMoney(t.pnl)}</div></td>
                      <td className="r">{t.bars_held}</td>
                      <td className="reason">{t.open ? 'Not sold yet' : t.exit_reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {trades.length > 12 && (
              <button className="link-btn" onClick={() => setShowAll(s => !s)}>{showAll ? 'Show fewer' : `Show all ${trades.length} trades`}</button>
            )}
          </>
        ))}
      </div>
    </section>
  )
}

/** The rules of the test, stated before and after every run. */
export function Assumptions({ fee = 3, slippage = 5, extra }: { fee?: number; slippage?: number; extra?: string }) {
  return (
    <ul className="assumptions">
      <li>Decides after each day's close and trades at the next day's opening price.</li>
      <li>Costs {fee} bps fee and {slippage} bps slippage on every buy and sell ({((fee + slippage) / 100).toFixed(2)}% per side).</li>
      <li>Buys whole shares only, holds one position at a time, never sells short.</li>
      <li>Leaves out STT, stamp duty, GST and exchange charges.</li>
      {extra && <li>{extra}</li>}
    </ul>
  )
}

/** Compact result block used inside the rule builder. */
export function Results({ result, running, error, bot = 'These rules' }: { result: BacktestResult | null; running: boolean; error: string | null; bot?: string }) {
  if (error) return <div className="results-empty error-text" role="alert">{error}</div>
  if (!result) return <div className="results-empty">{running ? 'Running the backtest…' : 'The backtest runs as soon as the rules are complete.'}</div>
  const stock = result.dataset.synthetic ? 'the sample stock' : result.dataset.symbol?.replace(/\.NS$/, '') ?? 'the stock'
  return (
    <div className={`results ${running ? 'stale' : ''}`} aria-busy={running}>
      <VerdictPanel result={result} bot={bot} stock={stock} />
      <ResultDetail result={result} />
      <p className="fineprint">Fingerprint: engine {result.engine}, rules {result.strategy_hash.slice(0, 10)}, data {result.data_hash.slice(0, 10)}. Research estimate, not investment advice.</p>
    </div>
  )
}
