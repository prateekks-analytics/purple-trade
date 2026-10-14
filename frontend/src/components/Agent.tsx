import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { AgentCall, Health, Job, SuperAgentInfo, TeamDecision, TeamResult } from '../types'
import { fmtMoney } from '../lib/tree'
import { getAi, openAiConnect } from '../lib/aiSettings'
import { DecisionLog, errText, JobProgress, useJob } from './AgentBits'
import { ResultDetail, VerdictPanel } from './Results'
import { AskSentence, DESK, DeskRow, POPULAR } from './Desk'
import { IconSpark } from './Icons'
import { markDone } from '../lib/quotes'

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
const PICKS = POPULAR

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

export function Agent({ health, initialSymbol, onPaperCreated }: { health: Health | null; initialSymbol?: string; onPaperCreated: (id: string) => void }) {
  const [agents, setAgents] = useState<SuperAgentInfo[] | null>(null)
  const [agentId, setAgentId] = useState('purple-agent')
  const [symbol, setSymbol] = useState(initialSymbol?.toUpperCase() || 'RELIANCE')
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

  const live = useJob(job, j => { if (j.status === 'done' && j.result) { setCall(j.result); markDone('agent') } if (j.status === 'error') setErr(j.error) })
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
    if (!d) {  // while running: what each finished step logged
      const kinds: Record<string, string[]> = { market: ['analyst'], news: ['research'], social: [], fundamentals: ['financial'], debate: ['bull', 'bear'] }
      const text = (kinds[id] ?? []).map(k => log.find(l => l.kind === k)?.text).filter(Boolean).join('\n\n')
      return text || null
    }
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
  const shown = STEPS.filter((s, i) => stepState(s, i) !== 'off')
  const ladderAt = (p: { stop: number; target: number }, close: number) => `${Math.min(90, Math.max(10, ((close - p.stop) / (p.target - p.stop)) * 100)).toFixed(1)}%`
  const rupee = (v: number) => `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

  return (
    <div className="page wide agent-page">
      <section className="hero hero-agent" aria-labelledby="agent-h">
        <h1 id="agent-h" className="visually-hidden">Ask the AI agent</h1>
        <AskSentence value={symbol} onChange={setSymbol} onSubmit={() => { if (!running) ask() }} holding={holding} size="lg" id="agent-symbol" />
        <div className="chips hero-chips" role="group" aria-label="Popular stocks">
          {PICKS.map(p => <button key={p} type="button" className={`chip ${sym === p ? 'on' : ''}`} onClick={() => setSymbol(p)}>{p}</button>)}
        </div>

        <div className="ask-options">
          <div className="segmented dark" role="radiogroup" aria-label="Do you own it?">
            <button type="button" role="radio" aria-checked={!holding} className={!holding ? 'on' : ''} onClick={() => setHolding(false)}>I don't own it</button>
            <button type="button" role="radio" aria-checked={holding} className={holding ? 'on' : ''} onClick={() => setHolding(true)}>I own it</button>
          </div>
          <div className="check-chips" role="group" aria-label="What it checks">
            {STEPS.filter(s => s.id === 'market' || (OPTIONAL as readonly string[]).includes(s.id)).map(s => {
              const on = use.includes(s.id)
              const face = DESK.find(x => x.id === s.id)!
              return (
                <button key={s.id} type="button" className={`check-chip ${on ? 'on' : ''}`} aria-pressed={on} disabled={s.id === 'market'}
                  title={s.what} onClick={() => setUse(u => (on ? u.filter(x => x !== s.id) : [...u, s.id]))}>{face.icon}{s.title}</button>
              )
            })}
          </div>
          {original && (
            <label className="engine-select">
              <span className="visually-hidden">Agent</span>
              <select value={agentId} onChange={e => setAgentId(e.target.value)}>
                <option value="purple-agent">Purple Research Agent, about 1 min</option>
                <option value="tradingagents-original">Original TradingAgents, 10–20 min</option>
              </select>
            </label>
          )}
        </div>

        <div className="hero-actions">
          <button className="btn glow lg" onClick={() => ask()} disabled={!sym || busy || running || (!aiOk && !isOriginal)}>
            <IconSpark /> {busy ? 'Starting…' : running ? 'The agent is working…' : `Get the call on ${sym || '…'}`}
          </button>
          <span className="hero-note">
            {aiOk ? <>{isOriginal ? 'Many' : `${calls}`} AI calls on {aiName}. <button className="link-btn on-dark" onClick={openAiConnect}>Change</button></>
              : <>Connect an AI first (Google Gemini is free). <button className="link-btn on-dark" onClick={openAiConnect}>Connect</button></>}
          </span>
        </div>
        {err && <p className="hero-error" role="alert">{err}</p>}
      </section>

      {call && d && head && (
        <section className={`call-card ${head.tone}`} aria-live="polite" aria-label="The agent's call">
          <div className="call-main">
            <p className="call-who">{call.agent.title} on <b>{plain(call.symbol)}</b>{call.name && call.name !== plain(call.symbol) ? `, ${call.name}` : ''}</p>
            <p className="call-word">{head.word}</p>
            <p className="call-line">{head.line}</p>
            <ul className="call-chips">
              <li>Close of {call.date} <b className="num">{rupee(call.close)}</b></li>
              {call.quote && <li>Live <b className="num">{rupee(call.quote.price)}</b></li>}
              {d.rating && <li>Rated <b>{d.rating}</b></li>}
            </ul>
          </div>
          {d.confidence > 0 && (
            <div className="ring" role="img" aria-label={`Confidence ${Math.round(d.confidence * 100)} percent`}>
              <svg viewBox="0 0 120 120" width="120" height="120" aria-hidden="true">
                <circle cx="60" cy="60" r="50" className="ring-track" />
                <circle cx="60" cy="60" r="50" className="ring-fill" pathLength={100} strokeDasharray={`${Math.round(d.confidence * 100)} 100`} />
              </svg>
              <span className="ring-num num">{Math.round(d.confidence * 100)}<small>%</small></span>
              <span className="ring-label">confident</span>
            </div>
          )}

          {d.risk_plan && (head.tone === 'buy' || call.holding) && (
            <div className="ladder" aria-label="Stop-loss and target">
              <div className="ladder-bar">
                <span className="ladder-loss" style={{ width: ladderAt(d.risk_plan, call.close) }} />
                <span className="ladder-gain" />
                <span className="ladder-now" style={{ left: ladderAt(d.risk_plan, call.close) }} title="Last close" />
              </div>
              <div className="ladder-labels">
                <span><b className="neg">Stop {rupee(d.risk_plan.stop)}</b><small>{d.risk_plan.stop_pct}%</small></span>
                <span className="mid"><b>{rupee(call.close)}</b><small>close</small></span>
                <span className="end"><b className="pos">Target {rupee(d.risk_plan.target)}</b><small>+{d.risk_plan.target_pct}%</small></span>
              </div>
              <p className="sub">2× and 3× the average daily range (ATR {rupee(d.risk_plan.atr)}), worked out by code.</p>
            </div>
          )}

          {d.reason && <p className="call-reason">{d.reason}</p>}
          {d.risks && <p className="call-risk"><b>What would prove it wrong</b>{d.risks}</p>}
          {d.notes.length > 0 && <p className="field-note">{d.notes.join(' ')}</p>}
          <p className="call-foot">{call.cached ? 'Saved call from earlier this session. ' : ''}AI: {call.model}. <button className="link-btn" onClick={() => ask(true)} disabled={running}>Ask again</button></p>
        </section>
      )}

      {call && (
        <div className="next-grid" aria-label="What next">
          <section className="next-card primary">
            <h2>Follow it with paper money</h2>
            <p>The account acts on the agent's call after every NSE close.</p>
            <div className="field-row">
              <label className="visually-hidden" htmlFor="agent-capital">Starting money (₹)</label>
              <input id="agent-capital" type="number" min={1000} step={1000} value={capital} onChange={e => setCapital(Math.max(1000, +e.target.value || 0))} />
              <button className="btn cta" onClick={follow} disabled={paperBusy}>{paperBusy ? 'Creating…' : `Start with ${fmtMoney(capital)}`}</button>
            </div>
          </section>
          <section className="next-card">
            <h2>Check it on past days</h2>
            <p>The agent decides each recent day using only what was known then.</p>
            <div className="field-row">
              <label className="visually-hidden" htmlFor="agent-days">Days</label>
              <select id="agent-days" value={days} onChange={e => setDays(+e.target.value)}>
                {[3, 5, 10].map(n => <option key={n} value={n}>Last {n} trading days</option>)}
              </select>
              <button className="btn" onClick={backtest} disabled={btRunning || isOriginal}>{btRunning ? 'Running…' : 'Run'}</button>
            </div>
            {isOriginal && <p className="field-note">For the original TradingAgents, follow it in a paper account instead.</p>}
          </section>
        </div>
      )}

      {isOriginal && live && running && <JobProgress job={live} label="TradingAgents is working" note="Takes several minutes. You can keep this page open." />}

      <section className={`panel desk-panel ${running ? 'busy' : ''}`} aria-label="How the agent decides">
        <div className="panel-head">
          <h2 className="panel-title">{call ? 'How it got there' : running ? `Working on ${sym}…` : 'The research desk'}</h2>
          {!call && !running && <span className="sub">Six steps, same order every time</span>}
        </div>
        <div className="pad-x"><DeskRow state={id => { const i = STEPS.findIndex(s => s.id === id); return stepState(STEPS[i], i) }} /></div>
        {(running || call) && (
          <ol className="steps">
            {shown.map(s => {
              const i = STEPS.indexOf(s)
              const st = stepState(s, i)
              const out = stepOut(s.id)
              return (
                <li key={s.id} className={`step ${st}`}>
                  <span className="step-dot" aria-hidden="true">{DESK[i].icon}</span>
                  <div className="step-body">
                    <p className="step-title"><b>{s.title}</b> <span className="sub">{s.who}{s.ai ? '' : ', code only'}{st === 'working' ? ', working…' : ''}</span></p>
                    {out ? (
                      <details>
                        <summary>{s.id === 'market' ? 'Read the market report' : s.id === 'call' ? 'Read the reasoning' : out.split('\n')[0].slice(0, 140) + (out.length > 140 ? '…' : '')}</summary>
                        <p className="step-out">{out}</p>
                      </details>
                    ) : <p className="step-what">{s.what}</p>}
                  </div>
                </li>
              )
            })}
          </ol>
        )}
        {d?.report && (
          <details className="pad-x raw">
            <summary>Everything the agent read</summary>
            <pre className="report">{d.report}</pre>
          </details>
        )}
      </section>

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
      <p className="fineprint center">Research tool, not investment advice. Prices from Yahoo Finance, about 15 minutes delayed.</p>
    </div>
  )
}
