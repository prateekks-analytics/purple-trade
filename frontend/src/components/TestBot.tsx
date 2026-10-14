import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { BacktestResult, Dataset, Strategy } from '../types'
import { fmtMoney } from '../lib/tree'
import { DownloadCode, errText } from './AgentBits'
import { Assumptions, DataPicker, ResultDetail, VerdictPanel } from './Results'
import { CandleChart, RangeTabs, sliceRange, type Bar as PriceBar, type RangeKey } from './Charts'
import { isLive } from '../lib/portfolio'

/** One row in the bot chooser: a built-in rule bot or a saved version of the person's own bot. */
interface Bot {
  id: string
  group: 'rules' | 'mine'
  title: string
  entry?: string
  exit?: string
  speed: string
  costs: Strategy['costs']
  capital: number
  sizePct: number
}

const GROUPS = [
  { id: 'rules', title: 'Built-in bots' },
  { id: 'mine', title: 'Your bots' },
] as const

const DEFAULT_COSTS = { fee_bps: 3, slippage_bps: 5 }
/** Bar sizes a rule bot's paper account can follow (live symbols only for intraday; matches the server). */
const INTERVALS = ['1d', '5m', '15m', '30m']
const INTERVAL_LABEL: Record<string, string> = { '1d': 'Daily (decides on the close)', '5m': 'Every 5 minutes, live', '15m': 'Every 15 minutes, live', '30m': 'Every 30 minutes, live' }

const stockName = (d: Dataset | null | undefined) =>
  d?.synthetic ? 'the sample stock' : d?.symbol ? d.symbol.replace(/\.NS$/, '') : 'the stock'

export function TestBot({ initialBot, onPaperCreated, onBuild }: {
  initialBot?: string; onPaperCreated: (id: string) => void; onBuild: () => void
}) {
  const [bots, setBots] = useState<Bot[] | null>(null)
  const [botId, setBotId] = useState<string | null>(initialBot ?? null)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [capital, setCapital] = useState(100000)
  const [interval, setInterval_] = useState('1d')
  const [paperBusy, setPaperBusy] = useState(false)
  const [bars, setBars] = useState<PriceBar[] | null>(null)
  const [range, setRange] = useState<RangeKey>('1Y')

  useEffect(() => {
    let alive = true
    ;(async () => {
      const [agents, list, ds] = await Promise.all([api.saAgents(), api.listStrategies(), api.datasets()])
      const saved = await Promise.all(list.filter(s => s.versions > 0).map(async s => {
        const doc = await api.getStrategy(s.id)
        const v = await api.getVersion(doc.versions[0].id)
        return { s, v }
      }))
      if (!alive) return
      const out: Bot[] = []
      for (const a of agents) {
        if (a.hidden || a.kind !== 'rules' || !a.strategy) continue
        out.push({ id: a.id, group: 'rules', title: a.title, entry: a.describe?.entry, exit: a.describe?.exit, speed: 'Instant',
          costs: a.strategy.costs ?? DEFAULT_COSTS, capital: a.strategy.initial_capital ?? 100000, sizePct: a.strategy.sizing?.value ?? 100 })
      }
      for (const { s, v } of saved) {
        out.push({ id: `version:${v.id}`, group: 'mine', title: s.name, entry: v.review.describe?.entry, exit: v.review.describe?.exit,
          speed: `Version ${v.number}`, costs: v.body.costs ?? DEFAULT_COSTS, capital: v.body.initial_capital ?? 100000, sizePct: v.body.sizing?.value ?? 100 })
      }
      setBots(out)
      setDatasets(ds)
      setDatasetId(ds[0]?.id ?? null)
    })().catch(e => alive && setErr(errText(e)))
    return () => { alive = false }
  }, [])

  const bot = useMemo(() => bots?.find(b => b.id === botId) ?? null, [bots, botId])
  const dataset = datasets.find(d => d.id === datasetId) ?? null
  const stock = stockName(dataset)

  useEffect(() => { setResult(null); setErr(null); setInterval_('1d') }, [botId, datasetId])

  const run = async () => {
    if (!bot || !datasetId) return
    setResult(null); setErr(null); setBusy(true)
    try {
      const r = await api.saRun(bot.id, datasetId, 5, [])
      if (r.kind === 'rules') setResult(r.result)
    } catch (e) { setErr(errText(e)) } finally { setBusy(false) }
  }

  const startPaper = async () => {
    if (!bot) return
    setPaperBusy(true); setErr(null)
    try {
      const v = await api.saPaperCreate(bot.id, datasetId, capital, [], isLive(dataset) ? dataset!.symbol! : undefined, interval)
      onPaperCreated(v.account.id)
    } catch (e) { setErr(errText(e)); setPaperBusy(false) }
  }

  // Price history for the chart: the chosen data before a run, the data the run used afterwards.
  const barsFor = result?.dataset.id ?? datasetId
  useEffect(() => {
    setBars(null)
    if (barsFor) api.datasetBars(barsFor).then(setBars).catch(() => setBars(null))
  }, [barsFor])

  const stockLabel = stock.replace(/^the /, '').replace(/^./, c => c.toUpperCase())
  const intervals = INTERVALS.filter(iv => iv === '1d' || isLive(dataset))

  return (
    <div className="page wide">
      <header className="page-head">
        <p className="kicker">Rule bots</p>
        <h1>Test a rule bot</h1>
        <p className="lede">A rule bot follows fixed indicator rules: same prices, same trades, no AI. Pick one, run it on past prices,
          then follow it in a paper account. Want an AI opinion on a stock instead? <a href="#/agent">Ask the AI agent</a>.</p>
      </header>

      <div className="trade-grid">
        {/* ---------- bot list ---------- */}
        <aside className="panel watch" aria-label="Rule bots">
          <h2 className="panel-title">Rule bots</h2>
          {bots === null ? <p className="field-note">Loading bots…</p> : GROUPS.map(g => {
            const list = bots.filter(b => b.group === g.id)
            return (
              <fieldset key={g.id} className="watch-group">
                <legend>{g.title}</legend>
                {list.length === 0 ? (
                  <p className="watch-empty">No saved bots yet. <button className="link-btn" onClick={onBuild}>Build one</button></p>
                ) : list.map(b => (
                  <label key={b.id} className={`watch-row ${botId === b.id ? 'on' : ''}`} title={b.entry ? `Buys when ${b.entry}. Sells when ${b.exit}.` : undefined}>
                    <input type="radio" name="bot" className="visually-hidden" checked={botId === b.id} onChange={() => setBotId(b.id)} />
                    <span className="watch-name">{b.title}</span>
                    <span className="watch-meta">{b.group === 'mine' ? b.speed : 'Instant'}</span>
                  </label>
                ))}
              </fieldset>
            )
          })}
          {bots && <p className="watch-empty"><button className="link-btn" onClick={onBuild}>+ Build a new bot</button></p>}
        </aside>

        {/* ---------- chart, verdict ---------- */}
        <section className="trade-main" aria-label="Chart and result">
          {!bot ? (
            <div className="panel empty-main">
              <h2>Pick a bot to start</h2>
              <p>Each bot runs instantly on past prices and shows every trade it would have made.</p>
            </div>
          ) : (
            <>
              <div className="panel instrument">
                <div className="instrument-head">
                  <div className="instrument-id">
                    <p className="sub">{bot.group === 'mine' ? 'Your bot' : 'Built-in bot'}</p>
                    <h2 className="instrument-title">{bot.title}</h2>
                    {bot.entry && <p className="rule-line"><span className="side buy">Buy</span> {bot.entry}<span className="side sell">Sell</span> {bot.exit}</p>}
                  </div>
                  <div className="instrument-stock">
                    <span className="sub">Stock</span>
                    <b>{stockLabel}</b>
                    {bars?.length ? <span className="num">₹{bars[bars.length - 1].close.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span> : null}
                  </div>
                </div>
                {!result && (bars?.length ? (
                  <>
                    <div className="detail-head"><span className="sub">Daily prices. Run the backtest to see its trades.</span><RangeTabs value={range} onChange={setRange} total={bars.length} /></div>
                    <div className="pad-x"><CandleChart bars={sliceRange(bars, range)} /></div>
                  </>
                ) : <p className="field-note pad">Loading prices…</p>)}
              </div>

              {result && (
                <>
                  <ResultDetail result={result} bars={bars} defaultTab="price" />
                  <VerdictPanel result={result} bot={bot.title} stock={stock} />
                </>
              )}
            </>
          )}
        </section>

        {/* ---------- ticket ---------- */}
        <aside className="panel ticket" aria-label="Backtest ticket">
          <h2 className="panel-title">Backtest ticket</h2>
          {!bot ? <p className="field-note">Choose a bot from the list.</p> : (
            <>
              <div className="ticket-fields">
                <DataPicker datasets={datasets} value={datasetId} onChange={setDatasetId}
                  onUploaded={d => { setDatasets(x => [d, ...x.filter(y => y.id !== d.id)]); setDatasetId(d.id) }} />
              </div>

              <dl className="ticket-summary">
                <div><dt>Period</dt><dd>{dataset ? `${dataset.first_date} to ${dataset.last_date}` : '—'}</dd></div>
                <div><dt>Starting money</dt><dd className="num">{fmtMoney(bot.capital)}</dd></div>
                <div><dt>Per trade</dt><dd>{bot.sizePct >= 100 ? 'Whole account' : `${bot.sizePct}% of account`}</dd></div>
                <div><dt>Costs per side</dt><dd>{((bot.costs.fee_bps + bot.costs.slippage_bps) / 100).toFixed(2)}%</dd></div>
                <div><dt>Time · AI</dt><dd>About a second · none</dd></div>
              </dl>
              <button className="btn primary block" onClick={run} disabled={!datasetId || busy}>
                {busy ? 'Running…' : result ? 'Run again' : 'Run backtest'}
              </button>
              {err && <p className="error-text" role="alert">{err}</p>}

              <details className="ticket-rules">
                <summary>How the test trades</summary>
                <Assumptions fee={bot.costs.fee_bps} slippage={bot.costs.slippage_bps} />
              </details>

              {result && (
                <div className="ticket-paper">
                  <h3>Paper trade this bot</h3>
                  <p className="field-note">Follows the bot forward with virtual money from the latest day. No real orders.</p>
                  <div className="field">
                    <label htmlFor="paper-capital">Starting money (₹)</label>
                    <input id="paper-capital" type="number" min={1000} step={1000} value={capital} onChange={e => setCapital(Math.max(1000, +e.target.value || 0))} />
                  </div>
                  {intervals.length > 1 && (
                    <div className="field">
                      <label htmlFor="paper-interval">How often it trades</label>
                      <select id="paper-interval" value={interval} onChange={e => setInterval_(e.target.value)}>
                        {intervals.map(iv => <option key={iv} value={iv}>{INTERVAL_LABEL[iv]}</option>)}
                      </select>
                      {interval !== '1d' && <p className="field-note">Live NSE bars from Yahoo Finance, about 15 minutes late. Purple fetches each finished bar every minute while it runs, 09:15–15:30 IST.</p>}
                    </div>
                  )}
                  <button className="btn cta block" onClick={startPaper} disabled={paperBusy}>{paperBusy ? 'Creating…' : `Start paper account, ${fmtMoney(capital)}`}</button>
                  <DownloadCode agentId={bot.id} symbol={dataset?.symbol ?? 'INFY'} />
                </div>
              )}
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
