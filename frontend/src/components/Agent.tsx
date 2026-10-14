import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { AgentCall, Health, Job, SuperAgentInfo, TeamDecision, TeamResult } from '../types'
import { fmtMoney } from '../lib/tree'
import { getAi, openAiConnect } from '../lib/aiSettings'
import { DecisionLog, errText, JobProgress, useJob } from './AgentBits'
import { ResultDetail, VerdictPanel } from './Results'

/** The agent's pipeline, in order. `kinds` are the job-log kinds that mark a step as finished. */
const STEPS = [
  { id: 'market', title: 'Price & indicators', who: 'Market analyst', kinds: ['analyst'], ai: false,
    what: 'Trend (SMA 50/200), momentum (MACD, RSI, EMA 10), volatility (ATR, Bollinger) from two years of daily prices.' },
  { id: 'news', title: 'News', who: 'News analyst', kinds: ['research'], ai: true,
    what: 'Reads recent Google News and Yahoo Finance headlines about the company.' },
  { id: 'social', title: 'Trader posts', who: 'Sentiment analyst', kinds: ['research'], ai: true,
    what: 'Reads what traders say on r/IndianStreetBets and r/IndianStockMarket.' },
  { id: 'fundamentals', title: 'Financials', who: 'Fundamentals analyst', kinds: ['financial'], ai: true,
    what: 'Revenue, profit, EPS, debt and free cash flow from the annual reports, and the price / earnings ratio.' },
  { id: 'debate', title: 'Bull vs bear debate', who: 'Two researchers', kinds: ['bull', 'bear'], ai: true,
    what: 'One argues for buying, the other against, both using only the reports above.' },
  { id: 'call', title: 'The call', who: 'Risk manager', kinds: ['manager'], ai: true,
    what: 'Weighs everything, decides Buy, Hold or Sell, and says what would prove it wrong. Stop-loss and target come from volatility.' },
] as const
const OPTIONAL = ['news', 'social', 'fundamentals'] as const
const PICKS = ['RELIANCE', 'INFY', 'TCS', 'HDFCBANK', 'ICICIBANK', 'SBIN']

const plain = (s: string) => s.replace(/\.NS$/, '')

/** Plain-English headline for the call, from the person's point of view (owns the stock or not). */
function headline(d: AgentCall['decision'], holding: boolean): { word: string; tone: 'buy' | 'sell' | 'hold'; line: string } {
  const view = d.view ?? d.action
  if (holding) {
    if (d.action === 'SELL') return { word: 'Sell', tone: 'sell', line: 'The agent would sell the shares you hold.' }
    return { word: 'Hold', tone: 'hold', line: view === 'BUY' ? 'Keep the shares: the agent still likes the stock.' : 'Keep the shares for now; no strong reason to sell.' }
  }
  if (d.action === 'BUY') return { word: 'Buy', tone: 'buy', line: 'The agent would buy at the next opening price.' }
  if (view === 'SELL') return { word: 'Avoid', tone: 'sell', line: 'Don\'t buy: the agent is negative on the stock.' }
  return { word: 'Wait', tone: 'hold', line: 'Don\'t buy yet: the evidence is not strong enough.' }
}

export function Agent({ health, onPaperCreated }: { health: Health | null; onPaperCreated: (id: string) => void }) {
  const [agents, setAgents] = useState<SuperAgentInfo[] | null>(null)
  const [agentId, setAgentId] = useState('purple-agent')
  const [symbol, setSymbol] = useState('RELIANCE')
  const [holding, setHolding] = useState(false)
  const [use, setUse] = useState<string[]>(['market', 'news', 'social', 'fundamentals'])
  const [job, setJob] = useState<Job<AgentCall> | null>(null)
  const [call, setCall] = useState<AgentCall | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // follow-ups: paper account and past-days check
  const [capital, setCapital] = useState(100000)
  const [paperBusy, setPaperBusy] = useState(false)
  const [days, setDays] = useState(5)
  const [btJob, setBtJob] = useState<Job<TeamResult> | null>(null)
  const [bt, setBt] = useState<TeamResult | null>(null)

  useEffect(() => { api.saAgents().then(setAgents).catch(e => setErr(errText(e))) }, [])

  const live = useJob(job, j => { if (j.status === 'done' && j.result) setCall(j.result); if (j.status === 'error') setErr(j.error) })
  const running = live?.status === 'running'
  const btLive = useJob(btJob, j => { if (j.status === 'done' && j.result) setBt(j.result); if (j.status === 'error') setErr(j.error) })
  const btRunning = btLive?.status === 'running'

  const original = agents?.find(a => a.id === 'tradingagents-original' && a.available)
  const isOriginal = agentId === 'tradingagents-original'
  const aiOk = Boolean(health?.ai.available)
  const ai = getAi()
  const aiName = ai ? `${ai.provider} · ${ai.model}` : health ? `${health.ai.provider} · ${health.ai.model}` : '…'
  const calls = 2 + (use.some(u => u === 'news' || u === 'social') ? 1 : 0) + (use.includes('fundamentals') ? 1 : 0) + 1
  const sym = symbol.trim().toUpperCase()

  // a new question clears the old answer
  useEffect(() => { setCall(null); setJob(null); setBt(null); setBtJob(null); setErr(null) }, [sym, holding, use.join(), agentId])

  const ask = async (fresh = false) => {
    if (!sym) return
    if (isOriginal && !confirm(`The original TradingAgents takes about 2–10 minutes on Google Gemini or 10–20 minutes on local Qwen for one call on ${sym}. Start now?`)) return
    setErr(null); setCall(null); setBt(null); setBtJob(null); setBusy(true)
    try {
      const r = await api.agentCall({ agent_id: agentId, symbol: sym, analyses: use, holding, fresh })
      setJob(r.job)
    } catch (e) { setErr(errText(e)) } finally { setBusy(false) }
  }

  const follow = async () => {
    if (!call) return
    setPaperBusy(true); setErr(null)
    try {
      const v = await api.saPaperCreate(call.agent.id, null, capital, call.analyses, call.symbol, '1d')
      window.dispatchEvent(new Event('purple:data'))
      onPaperCreated(v.account.id)
    } catch (e) { setErr(errText(e)); setPaperBusy(false) }
  }

  const backtest = async () => {
    if (!call) return
    const n = days * calls
    if (!confirm(`The agent will decide each of the last ${days} trading days of ${plain(call.symbol)}: about ${n} AI calls and ${Math.ceil(days * 0.6)}–${days * 2} minutes. Free AI tiers limit calls per minute; if one is refused, run again (finished days are kept). Start?`)) return
    setErr(null); setBt(null)
    try {
      const r = await api.saRun(call.agent.id, null, days, call.analyses, call.symbol)
      if (r.kind === 'job') setBtJob(r.job)
    } catch (e) { setErr(errText(e)) }
  }

  const log = live?.log ?? []
  const seen = new Set(log.map(l => l.kind))
  const d = call?.decision
  const head = d ? headline(d, call!.holding) : null

  /** Status of one pipeline step: off (analyst switched off), done, working (first unfinished while running), waiting. */
  const stepState = (s: typeof STEPS[number], i: number): 'off' | 'done' | 'working' | 'waiting' => {
    if ((OPTIONAL as readonly string[]).includes(s.id) && !use.includes(s.id)) return 'off'
    if (call) return 'done'
    if (!running || isOriginal) return 'waiting'
    const finished = (x: typeof STEPS[number]) => x.kinds.every(k => seen.has(k))
    if (finished(s)) return 'done'
    const first = STEPS.findIndex(x => !finished(x) && !((OPTIONAL as readonly string[]).includes(x.id) && !use.includes(x.id)))
    return first === i ? 'working' : 'waiting'
  }
  const stepOut = (id: string): string | null => {
    if (!d) return null
    const st = d.steps ?? {}
    if (id === 'market') return st.market ?? null
    if (id === 'news') return st.news || null
    if (id === 'social') return st.social || null
    if (id === 'fundamentals') return st.fundamentals ? `${st.health ? `Health: ${st.health}. ` : ''}${st.fundamentals}` : null
    if (id === 'debate') return d.bull || d.bear ? `Bull: ${d.bull}\n\nBear: ${d.bear}` : null
    if (id === 'call') return d.reason
    return null
  }

  const decisions = useMemo(() => (bt ? [...bt.decisions].reverse() as TeamDecision[] : []), [bt])

  return (
    <div className="page wide">
      <header className="page-head">
        <p className="kicker">AI agent</p>
        <h1>Should you buy this stock?</h1>
        <p className="lede">Name an NSE stock. The agent researches it the way an analyst team would, then gives one call:
          Buy, Hold or Sell, with its reasons, a stop-loss and what would prove it wrong.</p>
      </header>

      <div className="agent-grid">
        {/* ---------- the question ---------- */}
        <aside className="panel ticket agent-ask" aria-label="Ask the agent">
          <h2 className="panel-title">Ask the agent</h2>
          <div className="field">
            <label htmlFor="agent-symbol">Stock (NSE symbol)</label>
            <input id="agent-symbol" value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())}
              onKeyDown={e => { if (e.key === 'Enter' && !running) ask() }} placeholder="e.g. RELIANCE" autoComplete="off" />
            <div className="chips" role="group" aria-label="Popular stocks">
              {PICKS.map(p => <button key={p} type="button" className={`chip ${sym === p ? 'on' : ''}`} onClick={() => setSymbol(p)}>{p}</button>)}
            </div>
          </div>

          <div className="field">
            <span className="label" id="own-label">Do you own it?</span>
            <div className="segmented" role="radiogroup" aria-labelledby="own-label">
              <button type="button" role="radio" aria-checked={!holding} className={!holding ? 'on' : ''} onClick={() => setHolding(false)}>Not yet</button>
              <button type="button" role="radio" aria-checked={holding} className={holding ? 'on' : ''} onClick={() => setHolding(true)}>I own it</button>
            </div>
          </div>

          <div className="field">
            <span className="label" id="use-label">What it checks</span>
            <div className="toggles" role="group" aria-labelledby="use-label">
              {STEPS.filter(s => s.id === 'market' || (OPTIONAL as readonly string[]).includes(s.id)).map(s => {
                const on = use.includes(s.id)
                return (
                  <button key={s.id} type="button" className={`toggle ${on ? 'on' : ''}`} aria-pressed={on} disabled={s.id === 'market'}
                    title={s.what} onClick={() => setUse(u => (on ? u.filter(x => x !== s.id) : [...u, s.id]))}>{s.title}</button>
                )
              })}
            </div>
            <p className="field-note">Price & indicators is always on. Fewer checks = fewer AI calls ({isOriginal ? 'many' : calls} per call).</p>
          </div>

          {original && (
            <div className="field">
              <span className="label" id="engine-label">Agent</span>
              <div className="engine-pick" role="radiogroup" aria-labelledby="engine-label">
                <label className={agentId === 'purple-agent' ? 'on' : ''}>
                  <input type="radio" name="engine" checked={agentId === 'purple-agent'} onChange={() => setAgentId('purple-agent')} />
                  <span><b>Purple Research Agent</b><small>About 1 minute · up to 5 AI calls</small></span>
                </label>
                <label className={isOriginal ? 'on' : ''}>
                  <input type="radio" name="engine" checked={isOriginal} onChange={() => setAgentId('tradingagents-original')} />
                  <span><b>Original TradingAgents</b><small>Research version · 10–20 minutes</small></span>
                </label>
              </div>
            </div>
          )}

          <p className="field-note">AI: {aiOk ? aiName : 'not connected'} · <button className="link-btn" onClick={openAiConnect}>{aiOk ? 'change' : 'Connect an AI'}</button></p>
          <button className="btn primary block" onClick={() => ask()} disabled={!sym || busy || running || (!aiOk && !isOriginal)}>
            {busy ? 'Starting…' : running ? 'The agent is working…' : `Get the call on ${sym || '…'}`}
          </button>
          {!aiOk && !isOriginal && <p className="field-note warn">Connect an AI first (free Google Gemini works).</p>}
          {err && <p className="error-text" role="alert">{err}</p>}
          <p className="fineprint">Research tool, not investment advice. Prices from Yahoo Finance, about 15 minutes delayed.</p>
        </aside>

        {/* ---------- the answer ---------- */}
        <section className="trade-main" aria-label="The agent's work">
          {call && d && head && (
            <section className={`panel verdict-call ${head.tone}`} aria-live="polite">
              <div className="call-top">
                <div>
                  <p className="today-label">{call.agent.title} · {plain(call.symbol)}{call.name && call.name !== plain(call.symbol) ? ` (${call.name})` : ''}</p>
                  <p className="call-word">{head.word}</p>
                  <p className="call-line">{head.line}</p>
                </div>
                <dl className="call-facts">
                  <div><dt>Based on the close of</dt><dd>{call.date}</dd></div>
                  <div><dt>Close</dt><dd className="num">₹{call.close.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</dd></div>
                  {call.quote && <div><dt>Live price</dt><dd className="num">₹{call.quote.price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</dd></div>}
                  {d.confidence > 0 && <div><dt>Confidence</dt><dd className="num">{Math.round(d.confidence * 100)}%</dd></div>}
                  {d.rating && <div><dt>Rating</dt><dd>{d.rating}</dd></div>}
                </dl>
              </div>
              {d.reason && <p className="call-reason">{d.reason}</p>}
              {d.risks && <p className="call-risk"><b>What would prove it wrong:</b> {d.risks}</p>}
              {d.risk_plan && (head.tone === 'buy' || call.holding) && (
                <p className="call-plan">
                  <span><b>Stop-loss</b> ₹{d.risk_plan.stop.toLocaleString('en-IN')} <span className="neg">({d.risk_plan.stop_pct}%)</span></span>
                  <span><b>Target</b> ₹{d.risk_plan.target.toLocaleString('en-IN')} <span className="pos">(+{d.risk_plan.target_pct}%)</span></span>
                  <span className="sub">2× and 3× the average daily range (ATR ₹{d.risk_plan.atr}), computed by code.</span>
                </p>
              )}
              {d.notes.length > 0 && <p className="field-note">{d.notes.join(' ')}</p>}
              <p className="field-note">{call.cached ? 'Saved call from earlier for this session. ' : ''}AI: {call.model}. <button className="link-btn" onClick={() => ask(true)} disabled={running}>Ask again</button></p>
            </section>
          )}

          {isOriginal && live && running && <JobProgress job={live} label="TradingAgents is working" note="Takes several minutes. You can keep this page open." />}

          <section className="panel pipeline" aria-label="How the agent decides">
            <div className="panel-head">
              <div>
                <h2 className="panel-title">{call ? 'How it got there' : running ? `Working on ${sym}…` : 'How the agent decides'}</h2>
                {!call && !running && <p className="field-note">Six steps, in this order, every time. Click a finished step to read it.</p>}
              </div>
            </div>
            <ol className="steps">
              {STEPS.map((s, i) => {
                const st = stepState(s, i)
                const out = stepOut(s.id)
                return (
                  <li key={s.id} className={`step ${st}`}>
                    <span className="step-dot" aria-hidden="true">{st === 'done' ? '✓' : i + 1}</span>
                    <div className="step-body">
                      <p className="step-title"><b>{s.title}</b> <span className="sub">{s.who}{s.ai ? '' : ' · code, no AI'}{st === 'off' ? ' · switched off' : st === 'working' ? ' · working…' : ''}</span></p>
                      {out ? (
                        <details open={s.id === 'debate'}>
                          <summary>{s.id === 'market' ? 'Read the market report' : s.id === 'call' ? 'Read the reasoning' : out.split('\n')[0].slice(0, 140) + (out.length > 140 ? '…' : '')}</summary>
                          <p className="step-out">{out}</p>
                        </details>
                      ) : <p className="step-what">{s.what}</p>}
                    </div>
                  </li>
                )
              })}
            </ol>
            {d?.report && (
              <details className="pad-x raw">
                <summary>Everything the agent read (headlines, figures, indicators)</summary>
                <pre className="report">{d.report}</pre>
              </details>
            )}
          </section>

          {call && (
            <section className="panel next-steps" aria-label="What next">
              <h2 className="panel-title">What next?</h2>
              <div className="next-grid">
                <div className="next-card">
                  <h3>Follow this agent with virtual money</h3>
                  <p className="field-note">A paper account acts on the agent's call after every NSE close. No real orders.</p>
                  <div className="field-row">
                    <label className="visually-hidden" htmlFor="agent-capital">Starting money (₹)</label>
                    <input id="agent-capital" type="number" min={1000} step={1000} value={capital} onChange={e => setCapital(Math.max(1000, +e.target.value || 0))} />
                    <button className="btn cta" onClick={follow} disabled={paperBusy}>{paperBusy ? 'Creating…' : `Start with ${fmtMoney(capital)}`}</button>
                  </div>
                </div>
                <div className="next-card">
                  <h3>Check it on past days</h3>
                  <p className="field-note">The agent decides each recent day using only what was known then, and we count the result.</p>
                  <div className="field-row">
                    <label className="visually-hidden" htmlFor="agent-days">Days</label>
                    <select id="agent-days" value={days} onChange={e => setDays(+e.target.value)}>
                      {[3, 5, 10].map(n => <option key={n} value={n}>Last {n} trading days</option>)}
                    </select>
                    <button className="btn" onClick={backtest} disabled={btRunning || isOriginal}>{btRunning ? 'Running…' : 'Run'}</button>
                  </div>
                  {isOriginal && <p className="field-note">For the original TradingAgents, follow it in a paper account instead (minutes per day).</p>}
                </div>
              </div>
            </section>
          )}

          {btLive && btRunning && <JobProgress job={btLive} label={`Checking the agent on ${plain(call?.symbol ?? '')}`} note="Days already decided are kept if the run stops." />}
          {bt && call && (
            <>
              <ResultDetail result={bt} defaultTab="price" />
              <VerdictPanel result={bt} bot={call.agent.title} stock={plain(call.symbol)} />
              {decisions.length > 0 && (
                <section className="panel sub-section">
                  <h3 className="panel-title">Day-by-day calls</h3>
                  <DecisionLog decisions={decisions} />
                </section>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}
