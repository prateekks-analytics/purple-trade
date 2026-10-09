import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type {
  BacktestResult, Dataset, Health, Job, PaperAccount, PaperView, SuperAgentInfo, TeamDecision, TeamResult,
} from '../types'
import { fmtMoney, fmtPct } from '../lib/tree'
import { DataPicker, Results } from './Results'

const STEPS = ['Agent', 'Setup', 'Backtest', 'Paper trade', 'Deploy'] as const
type Step = 0 | 1 | 2 | 3 | 4

const errText = (e: unknown) => (e instanceof ApiError ? e.message : String(e))

function useJob<R>(job: Job<R> | null, onFinish?: (j: Job<R>) => void) {
  const [state, setState] = useState<Job<R> | null>(job)
  const fin = useRef(onFinish)
  fin.current = onFinish
  useEffect(() => {
    setState(job)
    if (!job || job.status !== 'running') { if (job) fin.current?.(job); return }
    let stop = false
    const tick = async () => {
      try {
        const j = await api.saJob<R>(job.id)
        if (stop) return
        setState(j)
        if (j.status === 'running') setTimeout(tick, 900)
        else fin.current?.(j)
      } catch (e) { if (!stop) setState({ ...job, status: 'error', error: errText(e) }) }
    }
    tick()
    return () => { stop = true }
  }, [job])
  return state
}

const KIND_LABEL: Record<SuperAgentInfo['kind'], string> = { 'ta-original': 'Original AI agents', 'ai-team': 'AI agent team (Purple rebuild)', rules: 'Rule bot', research: 'Research crew' }

function AgentCard({ a, selected, onPick }: { a: SuperAgentInfo; selected: boolean; onPick: () => void }) {
  return (
    <button className={`sa-card ${a.kind} ${selected ? 'on' : ''}`} onClick={onPick} disabled={!a.available} aria-pressed={selected}>
      <span className="sa-card-kind">{KIND_LABEL[a.kind]}{a.available ? '' : ' · needs setup'}</span>
      <b>{a.title}</b>
      {a.describe
        ? <span className="sa-rule-mini"><em>BUY</em> {a.describe.entry}<br /><em>SELL</em> {a.describe.exit}</span>
        : <span className="sa-card-tag" title={a.tagline}>{a.tagline}</span>}
      {a.kind !== 'rules' && (
        <span className="sa-card-foot">
          <a href={a.source.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}>{a.source.name.split(' (')[0]} ↗</a>
          <span>{a.speed.split(';')[0]}</span>
        </span>
      )}
    </button>
  )
}

function DecisionCards({ decisions, live }: { decisions: Pick<TeamDecision, 'date' | 'action' | 'confidence' | 'rating' | 'reason' | 'bull' | 'bear' | 'report'>[]; live?: boolean }) {
  return (
    <ol className="sa-days">
      {decisions.map(d => (
        <li key={d.date} className={`sa-day ${d.action.toLowerCase()}`}>
          <div className="sa-day-head">
            <span className="sa-date">{d.date}</span>
            <span className={`sa-action ${d.action.toLowerCase()}`}>{d.action}</span>
            <span className="muted small">{d.rating ? `rated ${d.rating}` : `${Math.round(d.confidence * 100)}% confidence`}</span>
          </div>
          <p className="sa-reason">{d.reason || '—'}</p>
          <details open={live}>
            <summary>Bull vs bear debate & market report</summary>
            <div className="sa-debate">
              <div className="bull"><b>🐂 Bull</b><p>{d.bull}</p></div>
              <div className="bear"><b>🐻 Bear</b><p>{d.bear}</p></div>
            </div>
            <pre className="sa-report">{d.report}</pre>
          </details>
        </li>
      ))}
    </ol>
  )
}

function JobProgress({ job, label, note = 'local AI, about 30–60 s per day' }: { job: Job; label: string; note?: string }) {
  const pct = job.total ? Math.round((job.done / job.total) * 100) : 100
  const last = job.log.slice(-4)
  return (
    <div className="sa-job" aria-live="polite">
      <div className="sa-job-head">
        <span className="sa-pulse" aria-hidden /> {label}: day {Math.min(job.done + 1, job.total)} of {job.total}
        <span className="muted small"> · {note}</span>
      </div>
      <div className="sa-bar"><i style={{ width: `${pct}%` }} /></div>
      <ul className="sa-feed">
        {last.map((l, i) => (
          <li key={i}><span className={`who ${l.kind}`}>{({ analyst: 'Market analyst', bull: 'Bull', bear: 'Bear', manager: 'Trader & risk', note: 'Check' } as Record<string, string>)[l.kind] ?? l.kind}</span>
            <span className="sa-date">{l.date}</span> {l.kind === 'analyst' ? l.text.split('\n')[0] : l.text}</li>
        ))}
      </ul>
    </div>
  )
}

function Tiles({ r }: { r: BacktestResult }) {
  const m = r.metrics
  const tone = (v: number | null) => (v === null ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : '')
  return (
    <div className="tiles">
      <div className="tile"><div className="tile-label">Account</div><div className="tile-value">{fmtMoney(m.end_equity)}</div><div className="tile-sub">from {fmtMoney(m.start_equity)}</div></div>
      <div className="tile"><div className="tile-label">Return</div><div className={`tile-value ${tone(m.total_return_pct)}`}>{fmtPct(m.total_return_pct)}</div><div className="tile-sub">buy & hold {fmtPct(m.buy_hold_return_pct)}</div></div>
      <div className="tile"><div className="tile-label">Trades</div><div className="tile-value">{m.trades}</div><div className="tile-sub">{r.trades.some(t => t.open) ? 'plus 1 open' : 'closed'}</div></div>
      <div className="tile"><div className="tile-label">Days</div><div className="tile-value">{m.bars}</div><div className="tile-sub">{m.first_date} → {m.last_date}</div></div>
    </div>
  )
}

function PaperPanel({ agent, datasetId, symbol, capital, analyses }: { agent: SuperAgentInfo; datasetId: string | null; symbol: string; capital: number; analyses: string[] }) {
  const isTA = agent.kind === 'ta-original'
  const [accounts, setAccounts] = useState<PaperAccount[]>([])
  const [view, setView] = useState<PaperView | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const live = useJob(job, j => { if (j.status === 'done' && view) api.saPaper(view.account.id).then(setView); if (j.status === 'error') setErr(j.error) })

  const refresh = () => api.saPaperList().then(setAccounts).catch(() => {})
  useEffect(() => { refresh() }, [])
  const mine = accounts.filter(a => a.agent_id === agent.id)

  const act = async (fn: () => Promise<PaperView>) => {
    setBusy(true); setErr(null)
    try { const v = await fn(); setView(v); refresh() } catch (e) { setErr(errText(e)) } finally { setBusy(false) }
  }
  const decide = async () => {
    if (!view) return
    setErr(null)
    try { setJob((await api.saPaperDecide(view.account.id)).job) } catch (e) { setErr(errText(e)) }
  }
  const remove = async (id: string) => {
    if (!confirm('Delete this paper account and its logbook? This cannot be undone.')) return
    await api.saPaperDelete(id)
    if (view?.account.id === id) setView(null)
    refresh()
  }
  const running = live?.status === 'running'

  return (
    <div className="sa-paper">
      <div className="sa-row sa-toolbar">
        <button className="btn sa-go" disabled={busy || (isTA ? !symbol.trim() : !datasetId)} onClick={() => act(() => api.saPaperCreate(agent.id, isTA ? null : datasetId, capital, analyses, isTA ? symbol : undefined))}>
          Start paper account · {fmtMoney(capital)}
        </button>
        {mine.length > 0 && (
          <label className="field-inline">
            <select value={view?.account.id ?? ''} onChange={e => e.target.value && act(() => api.saPaper(e.target.value))} aria-label="Open an existing paper account">
              <option value="">Open existing account…</option>
              {mine.map(a => <option key={a.id} value={a.id}>{a.name} · since {a.start_date}</option>)}
            </select>
          </label>
        )}
        <span className="muted small sa-toolbar-note">Virtual money from the last day in the data · decide on close, fill next open · no real orders</span>
      </div>
      {err && <p className="error-text" role="alert">{err}</p>}
      {view && (
        <div className="sa-paper-view">
          <div className="sa-today">
            <div>
              <div className="tile-label">Agent's call for {view.today.date}</div>
              <div className={`sa-action big ${(view.today.action ?? 'none').toLowerCase()}`}>{view.today.action ?? 'Not decided yet'}</div>
              <p className="sa-reason">{view.today.reason}</p>
              {view.today.action && view.today.action !== 'HOLD' && <p className="muted small">Would fill at the next trading day's open.</p>}
            </div>
            <div className="sa-today-actions">
              {view.agent.kind === 'ai-team' && view.pending_days.length > 0 && (
                <button className="btn sa-go" onClick={decide} disabled={running}>Ask the agent ({view.pending_days.length} day{view.pending_days.length > 1 ? 's' : ''})</button>
              )}
              {view.account.synthetic ? (
                <button className="btn ghost" disabled={busy || running} onClick={() => act(() => api.saPaperNextDay(view.account.id))}>Next trading day ▶</button>
              ) : null}
              {view.can_refresh && (
                <button className="btn ghost" disabled={busy || running} onClick={() => act(() => api.saPaperRefresh(view.account.id))}>Refresh prices ⟳</button>
              )}
              <button className="link-btn muted" onClick={() => remove(view.account.id)}>Delete account</button>
            </div>
          </div>
          {live && running && <JobProgress job={live} label="Team deciding" />}
          <p className="muted small">{view.data_note}</p>
          <Tiles r={view.result} />
          {view.decisions.some(d => d.date !== view.today.date) && (
            <><h3 className="sa-h3">Earlier days</h3><DecisionCards decisions={view.decisions.filter(d => d.date !== view.today.date).reverse()} /></>
          )}
          {view.result.trades.length > 0 && (
            <div className="table-wrap"><table>
              <thead><tr><th>Bought</th><th>Sold</th><th className="r">Qty</th><th className="r">P&L</th><th>Why</th></tr></thead>
              <tbody>{[...view.result.trades].reverse().map((t, i) => (
                <tr key={i}><td>{t.entry_date}<div className="sub">@ {t.entry_price.toFixed(2)}</div></td>
                  <td>{t.exit_date ?? <span className="badge">open</span>}</td><td className="r">{t.qty}</td>
                  <td className={`r ${t.pnl > 0 ? 'pos' : t.pnl < 0 ? 'neg' : ''}`}>{fmtPct(t.pnl_pct)}</td><td className="reason">{t.exit_reason}</td></tr>))}
              </tbody></table></div>
          )}
        </div>
      )}
    </div>
  )
}

function DeployPanel({ agent }: { agent: { id: string; title: string; kind: string } }) {
  const [symbol, setSymbol] = useState('INFY')
  const [out, setOut] = useState<{ filename: string; code: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const gen = async () => { setErr(null); try { setOut(await api.saExport(agent.id, symbol)) } catch (e) { setErr(errText(e)) } }
  const download = () => {
    if (!out) return
    const url = URL.createObjectURL(new Blob([out.code], { type: 'text/x-python' }))
    const a = document.createElement('a')
    a.href = url; a.download = out.filename; a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return (
    <div className="sa-deploy">
      <p className="muted small sa-intro">A standalone Python file that prints today's BUY / SELL / HOLD
        {agent.kind === 'rules' ? ' from the exact rules you tested' : ' from the agent'}. Starts in <b>DRY_RUN</b>: it only prints orders until you switch that off and add your own broker keys.</p>
      <div className="sa-row sa-toolbar">
        <label className="field-inline">NSE symbol <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} className="sa-input" aria-label="NSE symbol" /></label>
        <button className="btn sa-go" onClick={gen}>Generate code</button>
        {out && <button className="btn ghost" onClick={download}>Download {out.filename}</button>}
        {out && <button className="btn ghost" onClick={() => navigator.clipboard?.writeText(out.code)}>Copy</button>}
      </div>
      {err && <p className="error-text">{err}</p>}
      {out && <pre className="sa-code">{out.code}</pre>}
      <details className="sa-brokers">
        <summary>Taking it to a broker in India</summary>
        <ul>
          <li><b>Zerodha Kite Connect</b>: built into the file (set <code>BROKER = "zerodha"</code>, <code>KITE_API_KEY</code>, <code>KITE_ACCESS_TOKEN</code>). Paid API subscription.</li>
          <li><b>Angel One SmartAPI, Upstox, Dhan, Fyers</b> also offer order APIs. Replace <code>place_order()</code> with their client call.</li>
          <li>Automated retail orders go through SEBI's algo-trading framework via your broker (registration and controls may apply). Check with your broker first.</li>
          <li>Pricing and current API details are not verified by Purple Trade. Start with DRY_RUN and small quantities.</li>
        </ul>
      </details>
    </div>
  )
}

export function SuperAgent({ health, initialAgent, onExit }: {
  health: Health | null; initialAgent?: string; onExit: () => void
}) {
  const [agents, setAgents] = useState<SuperAgentInfo[]>([])
  const [agentId, setAgentId] = useState<string | null>(initialAgent ?? null)
  const [step, setStep] = useState<Step>(initialAgent ? 1 : 0)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [analyses, setAnalyses] = useState<string[]>(['market'])
  const [days, setDays] = useState(5)
  const [symbol, setSymbol] = useState('RELIANCE')
  const [capital, setCapital] = useState(100000)
  const [engineId, setEngineId] = useState('local')
  const [paidOk, setPaidOk] = useState(false)
  const [rulesResult, setRulesResult] = useState<BacktestResult | null>(null)
  const [job, setJob] = useState<Job<TeamResult> | null>(null)
  const [teamResult, setTeamResult] = useState<TeamResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.saAgents().then(setAgents).catch(e => setErr(errText(e)))
    api.datasets().then(ds => { setDatasets(ds); setDatasetId(ds[0]?.id ?? null) }).catch(() => {})
  }, [])

  const live = useJob(job, j => { if (j.status === 'done' && j.result) setTeamResult(j.result); if (j.status === 'error') setErr(j.error) })

  const agent = useMemo(() => agents.find(x => x.id === agentId) ?? null, [agentId, agents])
  const isTA = agent?.kind === 'ta-original'
  const isTeam = agent?.kind === 'ai-team' || isTA
  const maxDays = isTA ? 5 : 30
  const aiReady = Boolean(health?.ai.available)
  const engines = agent?.engines ?? []
  const engine = engines.find(e => e.id === engineId) ?? null
  const nDays = Math.min(days, maxDays)
  // older servers send no engine list: the original agent then runs on local Qwen as before
  const engineReady = isTA && engines.length ? Boolean(engine?.available) && (!engine?.paid || paidOk) : aiReady

  useEffect(() => {
    if (!agent) return
    setAnalyses(agent.kind === 'ta-original' ? ['market', 'news'] : ['market'])
    if (agent.kind === 'ta-original') setDays(d => Math.min(d, 2))
  }, [agent?.id])  // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (id: string) => { setAgentId(id); setRulesResult(null); setTeamResult(null); setJob(null); setErr(null); setStep(1) }

  const run = async () => {
    if (!agent || !datasetId) return
    setBusy(true); setErr(null); setRulesResult(null); setTeamResult(null); setJob(null)
    setStep(2)
    try {
      const r = await api.saRun(agent.id, isTA ? null : datasetId, Math.min(days, maxDays), analyses, isTA ? symbol : undefined,
        isTA ? engineId : undefined, isTA && Boolean(engine?.paid) && paidOk)
      if (r.kind === 'rules') setRulesResult(r.result)
      else setJob(r.job)
    } catch (e) { setErr(errText(e)) } finally { setBusy(false) }
  }

  const reachable = (s: number) => s === 0 || (agent !== null && (s <= 1 || s === 4 || rulesResult !== null || teamResult !== null || s === 3))
  const teamRunning = live?.status === 'running'

  return (
    <div className="sa">
      <header className="sa-head">
        <div>
          <div className="sa-kicker">Trading SuperAgent</div>
          <h1>{agent ? agent.title : 'Choose an agent'}</h1>
        </div>
        <button className="btn ghost sa-exit" onClick={onExit}>Exit SuperAgent</button>
      </header>

      <nav className="sa-steps" aria-label="SuperAgent steps">
        {STEPS.map((s, i) => (
          <button key={s} className={`${step === i ? 'on' : ''} ${i < step ? 'past' : ''}`} disabled={!reachable(i)} onClick={() => setStep(i as Step)} aria-current={step === i ? 'step' : undefined}>
            <i>{i + 1}</i>{s}
          </button>
        ))}
      </nav>

      {err && <p className="sa-err" role="alert">{err}</p>}

      {step === 0 && (
        <section className="sa-panel">
          <div className="sa-sec-head"><h2>AI agents</h2><span className="muted small">Reviewed and approved · TradingAgents (Tauric Research)</span></div>
          <div className="sa-grid ai">
            {agents.filter(a => a.kind !== 'rules').map(a => <AgentCard key={a.id} a={a} selected={a.id === agentId} onPick={() => pick(a.id)} />)}
          </div>
          <div className="sa-sec-head"><h2>Rule bots</h2><span className="muted small">From the TradingAgents indicator guide · instant backtests</span></div>
          <div className="sa-grid rules">
            {agents.filter(a => a.kind === 'rules').map(a => <AgentCard key={a.id} a={a} selected={a.id === agentId} onPick={() => pick(a.id)} />)}
          </div>
        </section>
      )}

      {step === 1 && agent && (
        <section className="sa-panel sa-setup">
          <div className="sa-form">
            <div className="sa-field">
              <label htmlFor="sa-stock">Stock</label>
              {isTA ? (
                <div>
                  <input id="sa-stock" className="sa-input" value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} />
                  <span className="muted small"> Yahoo Finance · {symbol.includes('.') ? symbol : `${symbol || '…'}.NS`}</span>
                </div>
              ) : (
                <DataPicker datasets={datasets} value={datasetId} onChange={setDatasetId} onUploaded={d => { setDatasets(x => [d, ...x.filter(y => y.id !== d.id)]); setDatasetId(d.id) }} />
              )}
            </div>
            {isTeam ? (
              <>
                <div className="sa-field">
                  <span className="sa-label">Analysts</span>
                  <div className="sa-chips">
                    {(agent as SuperAgentInfo).analyses.map(x => {
                      const on = analyses.includes(x.id)
                      const fixed = (!isTA && x.id === 'market') || (on && analyses.length === 1)
                      return (
                        <button key={x.id} type="button" className={`sa-chip ${on ? 'on' : ''}`} aria-pressed={on}
                          disabled={!x.available} title={x.detail}
                          onClick={() => { if (!fixed) setAnalyses(a => on ? a.filter(y => y !== x.id) : [...a, x.id]) }}>
                          {x.label.replace(' / technical', '').replace(' analyst', '')}
                        </button>
                      )
                    })}
                  </div>
                </div>
                <div className="sa-field">
                  <label htmlFor="sa-days">Days to backtest</label>
                  <div className="sa-row">
                    <input id="sa-days" type="range" min={1} max={maxDays} value={nDays} onChange={e => setDays(+e.target.value)} />
                    <span className="sa-days-n">{nDays} day{nDays > 1 ? 's' : ''}</span>
                  </div>
                </div>
                {isTA && engines.length > 0 && (
                  <div className="sa-field">
                    <label htmlFor="sa-engine">AI model</label>
                    <div>
                      <select id="sa-engine" className="sa-input" value={engineId} onChange={e => { setEngineId(e.target.value); setPaidOk(false) }}>
                        {engines.map(e => <option key={e.id} value={e.id} disabled={!e.available}>{e.label}{e.available ? '' : ' — needs key'}</option>)}
                      </select>
                      <p className="muted small sa-note">{engine ? (engine.available ? engine.note : engine.why) : ''}</p>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="sa-field">
                <span className="sa-label">Rules</span>
                {'describe' in agent && agent.describe
                  ? <p className="sa-rules"><em>BUY</em> {agent.describe.entry}<br /><em>SELL</em> {agent.describe.exit}</p>
                  : <p className="muted small">Your agent's saved rules.</p>}
              </div>
            )}
            <div className="sa-field">
              <label htmlFor="sa-cap">Paper capital</label>
              <div className="sa-row"><span>₹</span><input id="sa-cap" type="number" className="sa-input" min={1000} step={1000} value={capital} onChange={e => setCapital(Math.max(1000, +e.target.value || 0))} /></div>
            </div>
          </div>

          <aside className="sa-summary" aria-label="Run summary">
            <h2>Summary</h2>
            <dl>
              <dt>Agent</dt><dd>{agent.title}</dd>
              {isTeam && <><dt>Analysts</dt><dd>{analyses.length}</dd></>}
              {isTA && <><dt>AI model</dt><dd>{engine?.label.split(' (')[0] ?? 'Local Qwen'}</dd></>}
              <dt>Est. time</dt><dd>{isTA ? `${nDays * (engine?.minutes[0] ?? 10)}–${nDays * (engine?.minutes[1] ?? 20)} min`
                : isTeam ? `${Math.max(1, Math.round(nDays * 0.75))}–${Math.max(1, Math.round(nDays * 1.2))} min` : 'Instant'}</dd>
              <dt>Cost</dt><dd>{isTA && engine?.paid && engine.cost_per_day
                ? `≈ $${(engine.cost_per_day[0] * nDays).toFixed(2)}–${(engine.cost_per_day[1] * nDays).toFixed(2)}` : 'Free'}</dd>
            </dl>
            {isTA && engine?.paid && engine.cost_per_day && (
              <label className="sa-confirm">
                <input type="checkbox" checked={paidOk} onChange={e => setPaidOk(e.target.checked)} />
                <span>I approve this spend from my API credits (estimate; more analysts cost more).</span>
              </label>
            )}
            {!isTA && isTeam && !aiReady && <p className="sa-err">Local AI is offline.</p>}
            <button className="btn sa-go big" onClick={run} disabled={busy || (isTA ? !symbol.trim() : !datasetId) || (isTeam && !engineReady)}>Run backtest</button>
            <button className="link-btn" onClick={() => setStep(3)}>Skip to paper trading</button>
            <p className="muted small sa-fine">{isTeam ? (agent as SuperAgentInfo).fidelity : "Fills at the next day's open; fees and slippage included."}</p>
          </aside>
        </section>
      )}

      {step === 2 && agent && (
        <section className="sa-panel">
          <h2 className="sa-step-h">Backtest</h2>
          {busy && <p className="hint">Starting…</p>}
          {live && teamRunning && <JobProgress job={live} label="Analyst team working"
            note={isTA ? `${engine?.label ?? 'Local Qwen'}, about ${engine?.minutes[0] ?? 10}–${engine?.minutes[1] ?? 20} min per day` : undefined} />}
          {live && teamRunning && live.log.some(l => l.kind === 'manager') && (
            <p className="muted small">Decisions so far appear when the run finishes. Leave this tab open.</p>
          )}
          {rulesResult && <Results result={rulesResult} running={false} error={null} />}
          {teamResult && (
            <>
              <Results result={teamResult} running={false} error={null} />
              <h3 className="sa-h3">Decisions</h3>
              <DecisionCards decisions={[...teamResult.decisions].reverse()} />
            </>
          )}
          {(rulesResult || teamResult) && (
            <div className="sa-row sa-next">
              <button className="btn sa-go big" onClick={() => setStep(3)}>Paper trade this agent →</button>
              <button className="btn ghost" onClick={() => setStep(4)}>Get the code</button>
            </div>
          )}
        </section>
      )}

      {step === 3 && agent && (
        <section className="sa-panel">
          <h2 className="sa-step-h">Paper trading</h2>
          <PaperPanel agent={agent} datasetId={datasetId} symbol={symbol} capital={capital} analyses={analyses} />
          <div className="sa-row sa-next"><button className="link-btn" onClick={() => setStep(4)}>Deploy: get the code →</button></div>
        </section>
      )}

      {step === 4 && agent && (
        <section className="sa-panel">
          <h2 className="sa-step-h">Deploy</h2>
          <DeployPanel agent={agent} />
        </section>
      )}

      <footer className="sa-foot">Research and paper trading only. Purple Trade places no real orders. Backtests are estimates, not investment advice.</footer>
    </div>
  )
}
