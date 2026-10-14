import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { BacktestResult, Dataset, Job, Strategy, SuperAgentInfo, TeamResult } from '../types'
import { fmtMoney } from '../lib/tree'
import { DecisionLog, DownloadCode, errText, JobProgress, useJob } from './AgentBits'
import { Assumptions, DataPicker, ResultDetail, VerdictPanel } from './Results'
import { CandleChart, RangeTabs, sliceRange, type Bar as PriceBar, type RangeKey } from './Charts'
import { openAiConnect } from '../lib/aiSettings'
import { isLive } from '../lib/portfolio'

/** One row in the bot chooser: a curated agent, a rule bot, or a saved strategy version. */
interface Bot {
  id: string
  group: 'ai' | 'rules' | 'mine'
  title: string
  entry?: string
  exit?: string
  blurb?: string
  speed: string
  costs: Strategy['costs']
  capital: number
  sizePct: number
  info?: SuperAgentInfo
}

const GROUPS = [
  { id: 'ai', title: 'AI agents', note: 'Language-model agents read prices and news and decide to buy, sell or hold. Slower than rules; they use your AI.' },
  { id: 'rules', title: 'Rule bots', note: 'Fixed indicator rules from the TradingAgents indicator guide. Instant.' },
  { id: 'mine', title: 'Your strategies', note: 'Saved versions from Build your own. Instant.' },
] as const

const TA_COSTS = { fee_bps: 3, slippage_bps: 5 }
const NEWS_KINDS = ['ai-news', 'ai-crew']
/** AI calls per decision and rough seconds per decision, for the time and API-limit warnings. */
const PER_DECISION: Record<string, { calls: number; secs: [number, number] }> = { 'ai-news': { calls: 1, secs: [5, 20] }, 'ai-crew': { calls: 3, secs: [15, 60] } }
/** Bar sizes a paper account can follow, per bot kind (matches the server). */
const INTERVALS: Record<string, string[]> = { rules: ['1d', '5m', '15m', '30m'], 'ai-news': ['1d', '15m', '30m'], 'ai-crew': ['1d', '30m'] }
const BARS_PER_DAY: Record<string, number> = { '1d': 1, '5m': 75, '15m': 25, '30m': 13 }
const INTERVAL_LABEL: Record<string, string> = { '1d': 'Daily (decides on the close)', '5m': 'Every 5 minutes, live', '15m': 'Every 15 minutes, live', '30m': 'Every 30 minutes, live' }

export const stockName = (d: Dataset | null | undefined) =>
  d?.synthetic ? 'the sample stock' : d?.symbol ? d.symbol.replace(/\.NS$/, '') : 'the stock'

export function TestBot({ initialBot, onPaperCreated, onBuild }: {
  initialBot?: string; onPaperCreated: (id: string) => void; onBuild: () => void
}) {
  const [bots, setBots] = useState<Bot[] | null>(null)
  const [botId, setBotId] = useState<string | null>(initialBot ?? null)

  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [symbol, setSymbol] = useState('RELIANCE')
  const [analyses, setAnalyses] = useState<string[]>(['market', 'news'])
  const [days, setDays] = useState(2)
  const [engineId, setEngineId] = useState('local')
  const [paidOk, setPaidOk] = useState(false)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [teamResult, setTeamResult] = useState<TeamResult | null>(null)
  const [job, setJob] = useState<Job<TeamResult> | null>(null)
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
        if (a.kind === 'ta-original' && a.available) {
          out.push({ id: a.id, group: 'ai', title: a.title, blurb: 'The original open-source TradingAgents framework: market, news, sentiment and fundamentals analysts, a bull and bear debate, then trader, risk and portfolio managers.',
            speed: 'About 10 minutes per trading day', costs: TA_COSTS, capital: 100000, sizePct: 100, info: a })
        } else if (NEWS_KINDS.includes(a.kind) && a.available) {
          out.push({ id: a.id, group: 'ai', title: a.title, blurb: a.tagline,
            speed: a.speed, costs: TA_COSTS, capital: 100000, sizePct: 100, info: a })
        } else if (a.kind === 'rules' && a.strategy) {
          out.push({ id: a.id, group: 'rules', title: a.title, entry: a.describe?.entry, exit: a.describe?.exit, speed: 'Instant', costs: a.strategy.costs ?? TA_COSTS, capital: a.strategy.initial_capital ?? 100000, sizePct: a.strategy.sizing?.value ?? 100, info: a })
        }
      }
      for (const { s, v } of saved) {
        out.push({ id: `version:${v.id}`, group: 'mine', title: `${s.name}`, entry: v.review.describe?.entry, exit: v.review.describe?.exit,
          speed: `Version ${v.number}`, costs: v.body.costs ?? TA_COSTS, capital: v.body.initial_capital ?? 100000, sizePct: v.body.sizing?.value ?? 100 })
      }
      setBots(out)
      setDatasets(ds)
      setDatasetId(ds[0]?.id ?? null)
    })().catch(e => alive && setErr(errText(e)))
    return () => { alive = false }
  }, [])

  const live = useJob(job, j => { if (j.status === 'done' && j.result) setTeamResult(j.result); if (j.status === 'error') setErr(j.error) })
  const running = live?.status === 'running'

  const bot = useMemo(() => bots?.find(b => b.id === botId) ?? null, [bots, botId])
  const isAI = bot?.group === 'ai'
  const kind = bot?.info?.kind ?? (bot ? 'rules' : '')
  const isNews = NEWS_KINDS.includes(kind)
  const per = PER_DECISION[kind]
  const engines = bot?.info?.engines ?? []
  const engine = engines.find(e => e.id === engineId) ?? null
  const dataset = datasets.find(d => d.id === datasetId) ?? null
  const stock = isAI ? symbol : stockName(dataset)
  const shown = result ?? teamResult

  // Prefer the free Google Gemini engine when the person running the app has set a key.
  useEffect(() => {
    if (engines.some(e => e.id === 'gemini-flash' && e.available)) setEngineId('gemini-flash')
  }, [engines.length])  // eslint-disable-line react-hooks/exhaustive-deps

  const clear = () => { setResult(null); setTeamResult(null); setJob(null); setErr(null) }
  useEffect(clear, [botId, datasetId, symbol, days, engineId, analyses.join()])

  // sensible defaults when switching between the TradingAgents analysts and the news agents' sources
  useEffect(() => {
    if (isNews) { setAnalyses(['google', 'reddit']); setDays(d => Math.min(d, 10)) }
    else if (kind === 'ta-original') { setAnalyses(['market', 'news']); setDays(d => Math.min(d, 5)) }
    setInterval_('1d')
  }, [botId, bots === null])  // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (id: string) => setBotId(id)

  const minutes = per ? [Math.max(1, Math.round(days * per.secs[0] / 60)), Math.max(1, Math.ceil(days * per.secs[1] / 60))]
    : engine ? [days * engine.minutes[0], days * engine.minutes[1]] : [days * 10, days * 20]
  const cost = engine?.paid && engine.cost_per_day ? [engine.cost_per_day[0] * days, engine.cost_per_day[1] * days] : null
  const ready = Boolean(bot) && (isAI
    ? Boolean(symbol.trim()) && (!engines.length || (Boolean(engine?.available) && (!engine?.paid || paidOk))) && analyses.length > 0
    : Boolean(datasetId))

  const run = async () => {
    if (!bot || !ready) return
    if (per && !confirm(`${bot.title} will decide ${days} trading day${days > 1 ? 's' : ''} of ${symbol}: about ${days * per.calls} AI call${days * per.calls > 1 ? 's' : ''} and ${minutes[0] === minutes[1] ? `about ${minutes[0]}` : `${minutes[0]}–${minutes[1]}`} minute${minutes[1] > 1 ? 's' : ''}. Free AI tiers limit calls per minute; if a call is refused, wait a minute and run again (finished days are kept). Start now?`)) return
    if (isAI && !per && !confirm(`This runs the original TradingAgents for ${days} trading day${days > 1 ? 's' : ''} of ${symbol}. Expect about ${minutes[0]}–${minutes[1]} minutes${cost ? ` and about $${cost[0].toFixed(2)}–${cost[1].toFixed(2)} of API credit` : ''}. Start now?`)) return
    clear(); setBusy(true)
    try {
      const r = await api.saRun(bot.id, isAI ? null : datasetId, isAI ? days : 5, isAI ? analyses : [], isAI ? symbol : undefined,
        isAI ? engineId : undefined, isAI && Boolean(engine?.paid) && paidOk)
      if (r.kind === 'rules') setResult(r.result)
      else setJob(r.job)
    } catch (e) { setErr(errText(e)) } finally { setBusy(false) }
  }

  const startPaper = async () => {
    if (!bot) return
    setPaperBusy(true); setErr(null)
    try {
      const v = await api.saPaperCreate(bot.id, isAI ? null : datasetId, capital, isAI ? analyses : [], isAI ? symbol : isLive(dataset) ? dataset!.symbol! : undefined, interval)
      onPaperCreated(v.account.id)
    } catch (e) { setErr(errText(e)); setPaperBusy(false) }
  }

  // Price history for the chart: the chosen data before a run, the data the run used afterwards.
  const barsFor = shown?.dataset.id ?? (isAI ? null : datasetId)
  useEffect(() => {
    setBars(null)
    if (barsFor) api.datasetBars(barsFor).then(setBars).catch(() => setBars(null))
  }, [barsFor])

  const groupTitle = GROUPS.find(g => g.id === bot?.group)?.title.replace(/s$/, '')
  const stockLabel = stock.replace(/^the /, '').replace(/^./, c => c.toUpperCase())

  return (
    <div className="page wide">
      <header className="page-head row">
        <div>
          <h1>Test a bot</h1>
          <p className="lede">Choose a bot, set up the test on the right, run it, and read what the result means.</p>
        </div>
      </header>

      <div className="trade-grid">
        {/* ---------- bot list ---------- */}
        <aside className="panel watch" aria-label="Bots">
          <h2 className="panel-title">Bots</h2>
          {bots === null ? <p className="field-note">Loading bots…</p> : GROUPS.map(g => {
            const list = bots.filter(b => b.group === g.id)
            return (
              <fieldset key={g.id} className="watch-group">
                <legend>{g.title}</legend>
                {list.length === 0 ? (
                  <p className="watch-empty">{g.id === 'mine'
                    ? <>No saved versions yet. <button className="link-btn" onClick={onBuild}>Build one</button></>
                    : 'Not installed on this computer.'}</p>
                ) : list.map(b => (
                  <label key={b.id} className={`watch-row ${botId === b.id ? 'on' : ''}`} title={b.entry ? `Buys when ${b.entry}. Sells when ${b.exit}.` : b.blurb}>
                    <input type="radio" name="bot" className="visually-hidden" checked={botId === b.id} onChange={() => pick(b.id)} />
                    <span className="watch-name">{b.title}</span>
                    <span className="watch-meta">{b.group === 'ai' ? 'AI agent, slow' : b.group === 'mine' ? b.speed : 'Rules, instant'}</span>
                  </label>
                ))}
              </fieldset>
            )
          })}
        </aside>

        {/* ---------- chart, verdict ---------- */}
        <section className="trade-main" aria-label="Chart and result">
          {!bot ? (
            <div className="panel empty-main">
              <h2>Pick a bot to start</h2>
              <p>Rule bots run instantly on past prices. The AI agent takes minutes per trading day.</p>
            </div>
          ) : (
            <>
              <div className="panel instrument">
                <div className="instrument-head">
                  <div className="instrument-id">
                    <p className="sub">{groupTitle}</p>
                    <h2 className="instrument-title">{bot.title}</h2>
                    {bot.entry ? (
                      <p className="rule-line"><span className="side buy">Buy</span> {bot.entry}<span className="side sell">Sell</span> {bot.exit}</p>
                    ) : <p className="rule-line sub">{bot.blurb}</p>}
                  </div>
                  <div className="instrument-stock">
                    <span className="sub">Stock</span>
                    <b>{stockLabel}</b>
                    {bars?.length ? <span className="num">₹{bars[bars.length - 1].close.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</span> : null}
                  </div>
                </div>
                {!shown && (bars?.length ? (
                  <>
                    <div className="detail-head"><span className="sub">Daily prices. Run the backtest to see its trades.</span><RangeTabs value={range} onChange={setRange} total={bars.length} /></div>
                    <div className="pad-x"><CandleChart bars={sliceRange(bars, range)} /></div>
                  </>
                ) : <p className="field-note pad">{isAI ? 'Prices are downloaded for the symbol when the run starts.' : 'Loading prices…'}</p>)}
              </div>

              {live && running && <JobProgress job={live} label={`${bot.title} is working`} note="You can leave this page open; decisions already made are kept if the run stops." />}

              {shown && (
                <>
                  <ResultDetail result={shown} bars={bars} defaultTab="price" />
                  <VerdictPanel result={shown} bot={bot.title} stock={stock} />
                  {teamResult && teamResult.decisions.length > 0 && (
                    <section className="panel sub-section">
                      <h3 className="panel-title">Day-by-day decisions</h3>
                      <DecisionLog decisions={[...teamResult.decisions].reverse()} roles={kind === 'ai-crew' ? ['Research analyst', 'Financial analyst'] : undefined} />
                    </section>
                  )}
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
                {isAI ? (
                  <>
                    <div className="field">
                      <label htmlFor="ta-symbol">NSE symbol</label>
                      <input id="ta-symbol" value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} />
                      <p className="field-note">{isNews ? 'Prices from Yahoo Finance as ' : 'Prices and news from Yahoo Finance as '}{symbol.includes('.') ? symbol : `${symbol || '…'}.NS`}{isNews ? '; news from the sources below.' : '.'}</p>
                    </div>
                    <div className="field">
                      <span className="label" id="analysts-label">{isNews ? 'News sources' : 'Analysts'}</span>
                      <div className="toggles" role="group" aria-labelledby="analysts-label">
                        {bot.info!.analyses.map(x => {
                          const on = analyses.includes(x.id)
                          return (
                            <button key={x.id} type="button" className={`toggle ${on ? 'on' : ''}`} aria-pressed={on} disabled={!x.available || (on && analyses.length === 1)}
                              title={x.detail} onClick={() => setAnalyses(a => on ? a.filter(y => y !== x.id) : [...a, x.id])}>
                              {x.label.replace(' / technical', '').replace(' analyst', '')}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                    <div className="field">
                      <label htmlFor="ta-days">Trading days</label>
                      <select id="ta-days" value={days} onChange={e => setDays(+e.target.value)}>
                        {(isNews ? [1, 2, 3, 5, 10] : [1, 2, 3, 4, 5]).map(n => <option key={n} value={n}>{n} most recent day{n > 1 ? 's' : ''}</option>)}
                      </select>
                    </div>
                    {engines.length > 0 && (
                      <div className="field">
                        <label htmlFor="ta-engine">AI model</label>
                        <select id="ta-engine" value={engineId} onChange={e => { setEngineId(e.target.value); setPaidOk(false) }}>
                          {engines.map(e => <option key={e.id} value={e.id} disabled={!e.available}>{e.label}{e.available ? '' : ' (not connected)'}</option>)}
                        </select>
                        {engine && !engine.available && <p className="error-text">{engine.why} <button className="link-btn" onClick={openAiConnect}>Connect an AI</button></p>}
                      </div>
                    )}
                  </>
                ) : (
                  <DataPicker datasets={datasets} value={datasetId} onChange={setDatasetId}
                    onUploaded={d => { setDatasets(x => [d, ...x.filter(y => y.id !== d.id)]); setDatasetId(d.id) }} />
                )}
              </div>

              <dl className="ticket-summary">
                <div><dt>Period</dt><dd>{isAI ? `Last ${days} trading day${days > 1 ? 's' : ''}` : dataset ? `${dataset.first_date} to ${dataset.last_date}` : '—'}</dd></div>
                <div><dt>Starting money</dt><dd className="num">{fmtMoney(bot.capital)}</dd></div>
                <div><dt>Per trade</dt><dd>{bot.sizePct >= 100 ? 'Whole account' : `${bot.sizePct}% of account`}</dd></div>
                <div><dt>Costs per side</dt><dd>{((bot.costs.fee_bps + bot.costs.slippage_bps) / 100).toFixed(2)}%</dd></div>
                <div><dt>Time</dt><dd>{isAI ? `${minutes[0]}–${minutes[1]} min` : 'About a second'}</dd></div>
                <div><dt>AI cost</dt><dd>{cost ? `${cost[0].toFixed(2)}–${cost[1].toFixed(2)}` : per ? `${days * per.calls} AI calls` : 'Free'}</dd></div>
              </dl>
              {isAI && cost && (
                <label className="confirm">
                  <input type="checkbox" checked={paidOk} onChange={e => setPaidOk(e.target.checked)} />
                  <span>I approve spending up to about ${cost[1].toFixed(2)} of my API credit.</span>
                </label>
              )}
              {isNews && <p className="field-note">Uses the AI you connected (<button className="link-btn" onClick={openAiConnect}>change</button>). Free tiers such as Gemini limit calls per minute and per day.</p>}
              <button className="btn primary block" onClick={run} disabled={!ready || busy || running}>
                {busy ? 'Starting…' : running ? 'Running…' : shown ? 'Run again' : 'Run backtest'}
              </button>
              {err && <p className="error-text" role="alert">{err}</p>}

              <details className="ticket-rules">
                <summary>How the test trades</summary>
                <Assumptions fee={bot.costs.fee_bps} slippage={bot.costs.slippage_bps} />
              </details>

              {shown && (
                <div className="ticket-paper">
                  <h3>Paper trade this bot</h3>
                  <p className="field-note">Follows the bot forward with virtual money from the latest day. No real orders.</p>
                  <div className="field">
                    <label htmlFor="paper-capital">Starting money (₹)</label>
                    <input id="paper-capital" type="number" min={1000} step={1000} value={capital} onChange={e => setCapital(Math.max(1000, +e.target.value || 0))} />
                  </div>
                  {(() => {
                    const options = (INTERVALS[kind] ?? ['1d']).filter(iv => iv === '1d' || isAI || isLive(dataset))
                    const calls = per ? BARS_PER_DAY[interval] * per.calls : 0
                    return options.length > 1 && (
                      <div className="field">
                        <label htmlFor="paper-interval">How often it trades</label>
                        <select id="paper-interval" value={interval} onChange={e => setInterval_(e.target.value)}>
                          {options.map(iv => <option key={iv} value={iv}>{INTERVAL_LABEL[iv]}</option>)}
                        </select>
                        {interval !== '1d' && <p className="field-note">Live NSE bars from Yahoo Finance, about 15 minutes late. Purple fetches each finished bar every minute while it runs, 09:15–15:30 IST.</p>}
                        {calls > 1 && <p className="field-note warn">About {calls} AI calls per trading day. Free AI tiers may refuse some; the account then waits and catches up.</p>}
                      </div>
                    )
                  })()}
                  <button className="btn cta block" onClick={startPaper} disabled={paperBusy}>{paperBusy ? 'Creating…' : `Start paper account, ${fmtMoney(capital)}`}</button>
                  {!isNews && <DownloadCode agentId={bot.id} symbol={isAI ? symbol : dataset?.symbol ?? 'INFY'} />}
                </div>
              )}
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
