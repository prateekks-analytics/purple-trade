import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { BacktestResult, Dataset, Job, Strategy, SuperAgentInfo, TeamResult } from '../types'
import { fmtMoney } from '../lib/tree'
import { DecisionLog, DownloadCode, errText, JobProgress, useJob } from './AgentBits'
import { Assumptions, DataPicker, ResultDetail, VerdictPanel } from './Results'
import { openAiConnect } from '../lib/aiSettings'

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
  { id: 'ai', title: 'AI agents', note: 'Language-model analysts debate each trading day and decide to buy, sell or hold. Slow: minutes per day.' },
  { id: 'rules', title: 'Rule bots', note: 'Fixed indicator rules from the TradingAgents indicator guide. Instant.' },
  { id: 'mine', title: 'Your strategies', note: 'Saved versions from Build your own. Instant.' },
] as const

const TA_COSTS = { fee_bps: 3, slippage_bps: 5 }

export const stockName = (d: Dataset | null | undefined) =>
  d?.synthetic ? 'the sample stock' : d?.symbol ? d.symbol.replace(/\.NS$/, '') : 'the stock'

export function TestBot({ initialBot, onPaperCreated, onBuild }: {
  initialBot?: string; onPaperCreated: (id: string) => void; onBuild: () => void
}) {
  const [bots, setBots] = useState<Bot[] | null>(null)
  const [botId, setBotId] = useState<string | null>(initialBot ?? null)
  const [choosing, setChoosing] = useState(!initialBot)
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
  const [paperBusy, setPaperBusy] = useState(false)

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

  const pick = (id: string) => { setBotId(id); setChoosing(false) }

  const minutes = engine ? [days * engine.minutes[0], days * engine.minutes[1]] : [days * 10, days * 20]
  const cost = engine?.paid && engine.cost_per_day ? [engine.cost_per_day[0] * days, engine.cost_per_day[1] * days] : null
  const ready = Boolean(bot) && (isAI
    ? Boolean(symbol.trim()) && (!engines.length || (Boolean(engine?.available) && (!engine?.paid || paidOk))) && analyses.length > 0
    : Boolean(datasetId))

  const run = async () => {
    if (!bot || !ready) return
    if (isAI && !confirm(`This runs the original TradingAgents for ${days} trading day${days > 1 ? 's' : ''} of ${symbol}. Expect about ${minutes[0]}–${minutes[1]} minutes${cost ? ` and about $${cost[0].toFixed(2)}–${cost[1].toFixed(2)} of API credit` : ''}. Start now?`)) return
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
      const v = await api.saPaperCreate(bot.id, isAI ? null : datasetId, capital, isAI ? analyses : [], isAI ? symbol : undefined)
      onPaperCreated(v.account.id)
    } catch (e) { setErr(errText(e)); setPaperBusy(false) }
  }

  const step2Done = Boolean(bot)
  const step3Done = Boolean(shown)

  return (
    <div className="page">
      <header className="page-head">
        <h1>Test a bot</h1>
        <p className="lede">Pick a bot, choose the stock and period, run a backtest on past prices, then read what the result means. If it holds up, follow it with virtual money in a paper account.</p>
      </header>

      <ol className="steps">
        {/* ---------- 1. choose ---------- */}
        <li className={`step ${bot && !choosing ? 'done' : 'current'}`}>
          <div className="step-mark" aria-hidden>1</div>
          <div className="step-body">
            <h2>Choose a bot</h2>
            {bots === null ? <p className="field-note">Loading bots…</p> : bot && !choosing ? (
              <div className="chosen">
                <div>
                  <b>{bot.title}</b>
                  <span className="sub"> {GROUPS.find(g => g.id === bot.group)?.title.replace(/s$/, '')}{bot.group === 'mine' ? `, ${bot.speed.toLowerCase()}` : ''}</span>
                </div>
                <button className="btn quiet" onClick={() => setChoosing(true)}>Change bot</button>
              </div>
            ) : (
              <div className="bot-groups">
                {GROUPS.map(g => {
                  const list = bots.filter(b => b.group === g.id)
                  return (
                    <fieldset key={g.id} className="bot-group">
                      <legend>{g.title}</legend>
                      <p className="field-note">{g.note}</p>
                      {list.length === 0 ? (
                        <p className="empty-line">{g.id === 'mine'
                          ? <>No saved versions yet. <button className="link-btn" onClick={onBuild}>Build your own</button> and save a version to test it here.</>
                          : 'Not installed on this computer.'}</p>
                      ) : list.map(b => (
                        <label key={b.id} className={`bot-row ${botId === b.id ? 'on' : ''}`}>
                          <input type="radio" name="bot" checked={botId === b.id} onChange={() => pick(b.id)} />
                          <span className="bot-main">
                            <b>{b.title}</b>
                            {b.entry ? <span className="bot-rules"><span>Buys when {b.entry}</span><span>Sells when {b.exit}</span></span>
                              : <span className="bot-blurb">{b.blurb}</span>}
                          </span>
                          <span className="bot-speed">{b.speed}</span>
                        </label>
                      ))}
                    </fieldset>
                  )
                })}
              </div>
            )}
          </div>
        </li>

        {/* ---------- 2. set up ---------- */}
        <li className={`step ${!step2Done ? 'todo' : step3Done ? 'done' : 'current'}`}>
          <div className="step-mark" aria-hidden>2</div>
          <div className="step-body">
            <h2>Set up the test</h2>
            {!bot ? <p className="field-note">Choose a bot first.</p> : (
              <div className="setup">
                <div className="setup-fields">
                  {isAI ? (
                    <>
                      <div className="field">
                        <label htmlFor="ta-symbol">NSE stock symbol</label>
                        <input id="ta-symbol" value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} />
                        <p className="field-note">Prices and news come from Yahoo Finance as {symbol.includes('.') ? symbol : `${symbol || '…'}.NS`} (unofficial source).</p>
                      </div>
                      <div className="field">
                        <span className="label" id="analysts-label">Analysts</span>
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
                        <p className="field-note">Each extra analyst adds time per day.</p>
                      </div>
                      <div className="field">
                        <label htmlFor="ta-days">Trading days to test</label>
                        <select id="ta-days" value={days} onChange={e => setDays(+e.target.value)}>
                          {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n} most recent day{n > 1 ? 's' : ''}</option>)}
                        </select>
                        <p className="field-note">The agent decides each day using only information up to that day.</p>
                      </div>
                      {engines.length > 0 && (
                        <div className="field">
                          <label htmlFor="ta-engine">AI model</label>
                          <select id="ta-engine" value={engineId} onChange={e => { setEngineId(e.target.value); setPaidOk(false) }}>
                            {engines.map(e => <option key={e.id} value={e.id} disabled={!e.available}>{e.label}{e.available ? '' : ' (needs an API key)'}</option>)}
                          </select>
                          <p className="field-note">{engine ? (engine.available ? engine.note : engine.why) : ''}</p>
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      <DataPicker datasets={datasets} value={datasetId} onChange={setDatasetId}
                        onUploaded={d => { setDatasets(x => [d, ...x.filter(y => y.id !== d.id)]); setDatasetId(d.id) }} />
                      {bot.entry && (
                        <div className="rules-readout">
                          <p><span className="side buy">Buy</span> when {bot.entry}</p>
                          <p><span className="side sell">Sell</span> when {bot.exit}</p>
                        </div>
                      )}
                    </>
                  )}
                </div>
                <aside className="setup-rules" aria-label="How the test trades">
                  <h3>How the test trades</h3>
                  <Assumptions fee={bot.costs.fee_bps} slippage={bot.costs.slippage_bps}
                    extra={`Starts with ${fmtMoney(bot.capital)} of virtual money and puts ${bot.sizePct >= 100 ? 'the whole account' : `${bot.sizePct}% of the account`} into each trade.`} />
                </aside>
              </div>
            )}
          </div>
        </li>

        {/* ---------- 3. run ---------- */}
        <li className={`step ${!step2Done ? 'todo' : step3Done ? 'done' : 'current'}`}>
          <div className="step-mark" aria-hidden>3</div>
          <div className="step-body">
            <h2>Run the backtest</h2>
            {!bot ? <p className="field-note">Set up the test first.</p> : (
              <>
                <p className="run-summary">
                  {isAI
                    ? <>Ask {bot.title} to decide each of the last {days} trading day{days > 1 ? 's' : ''} for {symbol || '…'}. Expect about {minutes[0]}–{minutes[1]} minutes{cost ? `; estimated cost $${cost[0].toFixed(2)}–${cost[1].toFixed(2)} of API credit` : ', free'}.</>
                    : <>Replay {bot.title} over {dataset ? `${dataset.rows} trading days of ${stockName(dataset)} (${dataset.first_date} to ${dataset.last_date})` : 'the chosen prices'}. Takes a second, free.</>}
                </p>
                {isAI && cost && (
                  <label className="confirm">
                    <input type="checkbox" checked={paidOk} onChange={e => setPaidOk(e.target.checked)} />
                    <span>I approve spending up to about ${cost[1].toFixed(2)} of my API credit on this run.</span>
                  </label>
                )}
                {isAI && engine && !engine.available && <p className="error-text">{engine.why} <button className="link-btn" onClick={openAiConnect}>Connect an AI</button></p>}
                <div className="run-row">
                  <button className="btn primary" onClick={run} disabled={!ready || busy || running}>{busy ? 'Starting…' : running ? 'Running…' : shown ? 'Run again' : 'Run backtest'}</button>
                </div>
                {live && running && <JobProgress job={live} label={`${bot.title} is working`} note="You can leave this page open; decisions already made are kept if the run stops." />}
              </>
            )}
            {err && <p className="error-text" role="alert">{err}</p>}
          </div>
        </li>

        {/* ---------- 4. verdict ---------- */}
        <li className={`step ${shown ? 'current' : 'todo'}`}>
          <div className="step-mark" aria-hidden>4</div>
          <div className="step-body">
            <h2>Read the verdict</h2>
            {!shown || !bot ? <p className="field-note">The result appears here in plain English, with the chart and every trade.</p> : (
              <>
                <VerdictPanel result={shown} bot={bot.title} stock={stock} />
                <ResultDetail result={shown} />
                {teamResult && teamResult.decisions.length > 0 && (
                  <section className="sub-section">
                    <h3>Day-by-day decisions</h3>
                    <DecisionLog decisions={[...teamResult.decisions].reverse()} />
                  </section>
                )}
                <section className="next">
                  <h3>Next: follow it with virtual money</h3>
                  <p>A paper account starts on the latest day in the data and follows this bot forward one trading day at a time. No real orders are placed.</p>
                  <div className="run-row">
                    <div className="field inline">
                      <label htmlFor="paper-capital">Starting money (₹)</label>
                      <input id="paper-capital" type="number" min={1000} step={1000} value={capital} onChange={e => setCapital(Math.max(1000, +e.target.value || 0))} />
                    </div>
                    <button className="btn primary" onClick={startPaper} disabled={paperBusy}>{paperBusy ? 'Creating…' : `Start paper account with ${fmtMoney(capital)}`}</button>
                  </div>
                  <DownloadCode agentId={bot.id} symbol={isAI ? symbol : dataset?.symbol ?? 'INFY'} />
                </section>
              </>
            )}
          </div>
        </li>
      </ol>
    </div>
  )
}
