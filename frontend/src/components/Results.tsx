import { useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { BacktestResult, Dataset } from '../types'
import { fmtMoney, fmtPct } from '../lib/tree'
import { LineChart, type Marker } from './LineChart'

export function DataPicker({ datasets, value, onChange, onUploaded }: {
  datasets: Dataset[]; value: string | null; onChange: (id: string) => void; onUploaded: (d: Dataset) => void
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
      setMsg({ kind: 'ok', text: `Imported ${d.rows} days (${d.first_date} → ${d.last_date}).${d.warnings?.length ? ' ' + d.warnings.join(' ') : ''}` })
      setOpen(false)
    } catch (e) {
      setMsg({ kind: 'err', text: e instanceof ApiError ? e.message : String(e) })
    } finally { setBusy(false) }
  }

  return (
    <div className="data-picker">
      <label className="field-inline">
        <span>Test on</span>
        <select value={value ?? ''} onChange={e => onChange(e.target.value)} aria-label="Price data">
          {datasets.map(d => <option key={d.id} value={d.id}>{d.name} · {d.rows} days</option>)}
        </select>
      </label>
      <button className="btn ghost sm" onClick={() => setOpen(o => !o)} aria-expanded={open}>Import NSE CSV…</button>
      {current?.synthetic ? <span className="badge warn" title={current.source_note ?? ''}>Synthetic prices — not market data</span> : null}
      {current && !current.synthetic && current.source_note ? <span className="badge" title="Your stated source">Source: {current.source_note}</span> : null}
      {open && (
        <div className="upload-panel">
          <p className="hint">Daily prices for one stock. Works with the CSV from NSE's historical data page, or any file with <code>date, open, high, low, close</code> columns.</p>
          <div className="upload-row">
            <input ref={fileRef} type="file" accept=".csv,text/csv" aria-label="CSV file" />
            <input placeholder="Symbol (e.g. INFY)" value={symbol} onChange={e => setSymbol(e.target.value)} aria-label="Symbol" />
            <input placeholder="Source (e.g. NSE website, adjusted?)" value={note} onChange={e => setNote(e.target.value)} aria-label="Source note" />
            <button className="btn sm" onClick={upload} disabled={busy}>{busy ? 'Importing…' : 'Import'}</button>
          </div>
        </div>
      )}
      {msg && <p className={msg.kind === 'err' ? 'error-text' : 'ok-text'} role="status">{msg.text}</p>}
    </div>
  )
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'pos' | 'neg' }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className={`tile-value ${tone ?? ''}`}>{value}</div>
      {sub && <div className="tile-sub">{sub}</div>}
    </div>
  )
}

const tone = (v: number | null | undefined) => (v === null || v === undefined ? undefined : v > 0 ? 'pos' : v < 0 ? 'neg' : undefined)

export function Results({ result, running, error }: { result: BacktestResult | null; running: boolean; error: string | null }) {
  const [showAll, setShowAll] = useState(false)
  const [tab, setTab] = useState<'equity' | 'price' | 'trades'>('equity')

  const view = useMemo(() => {
    if (!result) return null
    const eq = result.equity
    const dates = eq.map(e => e.date)
    const start = result.metrics.start_equity
    const firstOpen = eq[0].close
    const bh = eq.map(e => (start * e.close) / firstOpen)
    const idx = new Map(dates.map((d, i) => [d, i]))
    const markers: Marker[] = []
    for (const t of result.trades) {
      const i = idx.get(t.entry_date)
      if (i !== undefined) markers.push({ index: i, value: t.entry_price, kind: 'buy', label: `Buy ${t.qty} @ ${t.entry_price.toFixed(2)} — ${t.entry_reason}` })
      if (t.exit_date) {
        const j = idx.get(t.exit_date)
        if (j !== undefined) markers.push({ index: j, value: t.exit_price ?? eq[j].close, kind: 'sell', label: `Sell @ ${t.exit_price?.toFixed(2)} — ${t.exit_reason}` })
      }
    }
    return { dates, equity: eq.map(e => e.equity), bh, close: eq.map(e => e.close), markers }
  }, [result])

  if (error) return <div className="results-empty error-text" role="alert">{error}</div>
  if (!result || !view) {
    return <div className="results-empty">{running ? 'Running backtest…' : 'Results appear here as soon as the rules are complete.'}</div>
  }
  const m = result.metrics
  const trades = [...result.trades].reverse()
  const shown = showAll ? trades : trades.slice(0, 12)

  return (
    <div className={`results ${running ? 'stale' : ''}`} aria-busy={running}>
      <div className="tiles">
        <Tile label="Return" value={fmtPct(m.total_return_pct)} tone={tone(m.total_return_pct)} sub={`${fmtMoney(m.start_equity)} → ${fmtMoney(m.end_equity)}`} />
        <Tile label="Buy & hold" value={fmtPct(m.buy_hold_return_pct)} tone={tone(m.buy_hold_return_pct)} sub="same period" />
        <Tile label="Max drawdown" value={fmtPct(m.max_drawdown_pct)} tone={m.max_drawdown_pct < 0 ? 'neg' : undefined} sub="worst peak-to-trough" />
        <Tile label="Trades" value={String(m.trades)} sub={m.win_rate_pct === null ? 'no closed trades' : `${m.win_rate_pct.toFixed(0)}% winners`} />
        <Tile label="Avg trade" value={fmtPct(m.avg_trade_pct)} tone={tone(m.avg_trade_pct)} sub={m.profit_factor === null ? '' : `profit factor ${m.profit_factor.toFixed(2)}`} />
        <Tile label="Time in market" value={`${m.exposure_pct.toFixed(0)}%`} sub={`fees ${fmtMoney(m.fees_paid)}`} />
      </div>

      <div className="chart-card">
        <div className="chart-tabs" role="tablist" aria-label="Result views">
          {([['equity', 'Account value'], ['price', 'Price & trades'], ['trades', `Trades (${trades.length})`]] as const).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{label}</button>
          ))}
          {tab === 'price' && <span className="legend-inline"><span className="mk buy">▲</span> buy <span className="mk sell">▼</span> sell</span>}
        </div>
        {tab === 'equity' && (
          <LineChart dates={view.dates} ariaLabel="Account value over time, strategy versus buy and hold"
            series={[
              { key: 's', label: 'This strategy', color: 'var(--series-1)', values: view.equity },
              { key: 'b', label: 'Buy & hold', color: 'var(--series-2)', values: view.bh, dashed: true },
            ]}
            baseline={m.start_equity}
            format={v => fmtMoney(v)} />
        )}
        {tab === 'price' && (
          <LineChart dates={view.dates} ariaLabel="Closing price with buy and sell markers"
            series={[{ key: 'c', label: 'Close', color: 'var(--series-1)', values: view.close }]}
            markers={view.markers}
            format={v => v.toLocaleString('en-IN', { maximumFractionDigits: 0 })} />
        )}
        {tab === 'trades' && (trades.length === 0 ? (
          <p className="hint">{result.strategy_hash === 'ai-team'
            ? 'No trades. The team did not decide to buy in this period.'
            : `No trades. The buy rules never matched on this data${result.warmup_bars ? ` (the first ${result.warmup_bars} days are indicator warm-up)` : ''}.`}</p>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Bought</th><th>Sold</th><th className="r">Qty</th><th className="r">P&L</th><th className="r">Days</th><th>Why it sold</th></tr>
                </thead>
                <tbody>
                  {shown.map((t, i) => (
                    <tr key={i} className={t.open ? 'open-row' : ''}>
                      <td title={t.entry_reason}><div>{t.entry_date}</div><div className="sub">@ {t.entry_price.toFixed(2)}</div></td>
                      <td>{t.exit_date ? <><div>{t.exit_date}</div><div className="sub">@ {t.exit_price?.toFixed(2)}</div></> : <span className="badge">open</span>}</td>
                      <td className="r">{t.qty}</td>
                      <td className={`r ${tone(t.pnl)}`}><div>{fmtPct(t.pnl_pct)}</div><div className="sub">{fmtMoney(t.pnl)}</div></td>
                      <td className="r">{t.bars_held}</td>
                      <td className="reason">{t.exit_reason}</td>
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

      <p className="fineprint">
        {result.describe.execution} Engine {result.engine} · rules {result.strategy_hash} · data {result.data_hash} ·
        {' '}{m.first_date} → {m.last_date}, {m.bars} days. Excludes STT, stamp duty, GST and exchange charges. Research estimate, not advice.
      </p>
    </div>
  )
}
