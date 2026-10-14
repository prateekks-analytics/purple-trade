import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Job, MarketStatus, PaperAccount, PaperView, Quote } from '../types'
import { fmtMoney, fmtPct } from '../lib/tree'
import { isLive } from '../lib/portfolio'
import { DecisionLog, DownloadCode, errText, JobProgress, useJob } from './AgentBits'
import { ResultDetail } from './Results'
import { BotBadge } from './Desk'
import { IconSpark } from './Icons'

const HIDDEN = new Set(['tradingagents'])
const CALL = { BUY: 'Buy', SELL: 'Sell', HOLD: 'Hold' } as const
const NEWS_KINDS = ['ai-agent', 'ai-news', 'ai-crew']
const CALLS: Record<string, number> = { 'ai-agent': 5, 'ai-news': 1, 'ai-crew': 3 }
/** Accounts followed by an AI agent (everything else follows a rule bot or a saved strategy). */
const AI_IDS = new Set(['purple-agent', 'tradingagents-original', 'tradingagents', 'news-pulse', 'crew-nse'])
export const isAgentAccount = (a: { agent_id: string }) => AI_IDS.has(a.agent_id)
const autoKey = (id: string) => `purple.autoDecide.${id}`
const readAuto = (id: string) => { try { return localStorage.getItem(autoKey(id)) === '1' } catch { return false } }
const writeAuto = (id: string, on: boolean) => { try { localStorage.setItem(autoKey(id), on ? '1' : '0') } catch { /* private mode */ } }

/** Plain-English sentence about what the account holds right now. */
function position(v: PaperView) {
  const r = v.result
  const open = r.trades.find(t => t.open)
  const lastClose = r.equity[r.equity.length - 1]?.close
  if (open) {
    const worth = open.qty * (lastClose ?? open.entry_price)
    return `Holding ${open.qty} shares bought on ${open.entry_date} at ₹${open.entry_price.toFixed(2)}. They are worth ${fmtMoney(worth)} at the last close (${fmtPct(open.pnl_pct)}).`
  }
  return `Not holding any shares. All ${fmtMoney(r.metrics.end_equity)} is in cash.`
}

/** Account value at the live (delayed) price: the last close's value plus the open position's move since then. */
function liveValue(v: PaperView, q: Quote) {
  const open = v.result.trades.find(t => t.open)
  const lastClose = v.result.equity[v.result.equity.length - 1]?.close ?? q.price
  return v.result.metrics.end_equity + (open ? open.qty * (q.price - lastClose) : 0)
}

const QUOTE_MS = 60_000
const REFRESH_MS = 10 * 60_000

/** Live quote for a real-symbol account, and the account moved forward once a newer session has closed. */
function useLive(view: PaperView | null, onView: (v: PaperView) => void) {
  const [quote, setQuote] = useState<Quote | null>(null)
  const [qErr, setQErr] = useState<string | null>(null)
  const lastRefresh = useRef(0)
  const id = view?.account.id
  const live = isLive(view?.account)
  const latest = useRef(view?.latest_date)
  latest.current = view?.latest_date

  useEffect(() => {
    setQuote(null); setQErr(null)
    if (!id || !live) return
    let alive = true
    const refresh = () => {
      lastRefresh.current = Date.now()
      api.saPaperRefresh(id).then(v => { if (alive && v.latest_date !== latest.current) { onView(v); window.dispatchEvent(new Event('purple:data')) } }).catch(() => {})
    }
    const tick = () => {
      if (document.hidden) return
      if (view!.interval && view!.interval !== '1d') {
        api.saPaper(id).then(v => { if (alive && v.latest_date !== latest.current) { onView(v); window.dispatchEvent(new Event('purple:data')) } }).catch(() => {})
      }
      api.marketQuote(view!.account.symbol!).then(q => {
        if (!alive) return
        setQuote(q); setQErr(null)
        const day = q.time?.slice(0, 10)
        if (!q.session_open && day && latest.current && day > latest.current && Date.now() - lastRefresh.current > REFRESH_MS) refresh()
      }).catch(e => alive && setQErr(errText(e)))
    }
    if (view!.interval && view!.interval !== '1d') lastRefresh.current = Date.now()
    else refresh()
    tick()
    const t = setInterval(tick, QUOTE_MS)
    return () => { alive = false; clearInterval(t) }
  }, [id, live]) // eslint-disable-line react-hooks/exhaustive-deps

  return { quote, qErr, live }
}

/** Feed health (Yahoo rate limits, live loop errors), polled every minute while a live account is open. */
function useMarketStatus(on: boolean) {
  const [st, setSt] = useState<MarketStatus | null>(null)
  useEffect(() => {
    if (!on) { setSt(null); return }
    let alive = true
    const tick = () => { if (!document.hidden) api.marketStatus().then(x => alive && setSt(x)).catch(() => {}) }
    tick()
    const t = setInterval(tick, QUOTE_MS)
    return () => { alive = false; clearInterval(t) }
  }, [on])
  return st
}

function todayLine(v: PaperView) {
  const a = v.today.action
  const next = v.interval && v.interval !== '1d' ? "the next bar's" : "the next trading day's"
  if (!a) return 'The agent has not decided the latest day yet.'
  if (a === 'HOLD') return 'No trade: keep the account as it is.'
  return a === 'BUY' ? `It would buy at ${next} opening price.` : `It would sell at ${next} opening price.`
}

export function Paper({ accountId, onSelect }: { accountId?: string; onSelect: (id: string) => void }) {
  const [accounts, setAccounts] = useState<PaperAccount[] | null>(null)
  const [view, setView] = useState<PaperView | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [job, setJob] = useState<Job | null>(null)

  // Accounts of the hidden Analyst Team rebuild stay in the database but are not shown.
  const refreshList = () => api.saPaperList().then(a => setAccounts(a.filter(x => !HIDDEN.has(x.agent_id)))).catch(e => setErr(errText(e)))
  useEffect(() => { refreshList() }, [])

  useEffect(() => {
    setView(null); setErr(null); setJob(null)
    if (accountId) api.saPaper(accountId).then(setView).catch(e => setErr(errText(e)))
  }, [accountId])

  // open the newest account when none is chosen
  useEffect(() => { if (!accountId && accounts?.length) onSelect(accounts[0].id) }, [accountId, accounts]) // eslint-disable-line react-hooks/exhaustive-deps

  const market = useLive(view, setView)
  const status = useMarketStatus(market.live)
  const [auto, setAuto] = useState(false)
  useEffect(() => { setAuto(view ? readAuto(view.account.id) : false) }, [view?.account.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const live = useJob(job, j => { if (j.status === 'done' && view) api.saPaper(view.account.id).then(setView); if (j.status === 'error') setErr(j.error) })
  const running = live?.status === 'running'

  const act = async (fn: () => Promise<PaperView>) => {
    setBusy(true); setErr(null)
    try { setView(await fn()); window.dispatchEvent(new Event('purple:data')) } catch (e) { setErr(errText(e)) } finally { setBusy(false) }
  }
  const isNewsAgent = Boolean(view && NEWS_KINDS.includes(view.agent.kind))
  useEffect(() => {
    if (!auto || !view || !isNewsAgent || running || job?.status === 'running' || !view.pending_days.length) return
    api.saPaperDecide(view.account.id).then(r => setJob(r.job)).catch(e => setErr(errText(e)))
  }, [auto, view?.pending_days.length, running]) // eslint-disable-line react-hooks/exhaustive-deps

  const decide = async () => {
    if (!view) return
    const slow = view.agent.kind === 'ta-original'
    if (slow && !confirm(`The original TradingAgents needs about 2–10 minutes per trading day on Google Gemini, or 10–20 on local Qwen (${view.pending_days.length} day${view.pending_days.length > 1 ? 's' : ''} pending). Start now?`)) return
    setErr(null)
    try { setJob((await api.saPaperDecide(view.account.id)).job) } catch (e) { setErr(errText(e)) }
  }
  const remove = async () => {
    if (!view || !confirm(`Delete the paper account "${view.account.name}" and its logbook? This cannot be undone.`)) return
    await api.saPaperDelete(view.account.id)
    const rest = (accounts ?? []).filter(a => a.id !== view.account.id)
    setAccounts(rest); setView(null)
    if (rest.length) onSelect(rest[0].id); else location.hash = '#/paper'
  }

  if (accounts !== null && accounts.length === 0) {
    return (
      <div className="page">
        <header className="page-head">
          <h1>Paper accounts</h1>
          <p className="lede">Follow the agent or a rule bot forward with virtual money. No real orders.</p>
        </header>
        <div className="empty big">
          <span className="empty-art" aria-hidden="true"><IconSpark /></span>
          <h2>No paper accounts yet</h2>
          <p>Get a call from the agent or test a bot, then follow it with virtual money.</p>
          <div className="head-actions"><a className="btn glow" href="#/agent"><IconSpark /> Ask the agent</a><a className="btn" href="#/test">Test a rule bot</a></div>
        </div>
      </div>
    )
  }

  const m = view?.result.metrics
  const isAI = view && view.agent.kind !== 'rules'
  const vs = m ? m.total_return_pct - m.buy_hold_return_pct : 0
  const who = isAI ? 'Agent' : 'Bot'
  const latest = view?.decisions.length ? view.decisions[view.decisions.length - 1] : null
  const tone = (v: number) => (v > 0 ? 'pos' : v < 0 ? 'neg' : '')

  return (
    <div className="page wide">
      <header className="page-head row">
        <div>
          <h1>Paper accounts</h1>
          <p className="lede">Virtual money following the agent or a bot, with every call explained.</p>
        </div>
        <div className="head-actions"><a className="btn primary" href="#/agent"><IconSpark /> Ask the agent</a><a className="btn" href="#/test">Test a bot</a></div>
      </header>

      <nav className="bot-rail" aria-label="Paper accounts">
        {(accounts ?? []).map(a => {
          const agent = isAgentAccount(a)
          return (
            <button key={a.id} className={`bot-card ${a.id === accountId ? 'on' : ''}`} aria-current={a.id === accountId ? 'page' : undefined} onClick={() => onSelect(a.id)}>
              {agent ? <span className="bot-badge md look-violet" aria-hidden="true"><IconSpark /></span> : <BotBadge id={a.agent_id} />}
              <span className="bot-card-name">{a.name}</span>
              <span className="bot-card-meta">{agent ? 'AI agent' : 'Rule bot'}, since {a.start_date}{a.synthetic ? ', sample' : ''}</span>
            </button>
          )
        })}
      </nav>

      <div className="trade-grid two">
        <section className="trade-main" aria-label="Account">
          {err && <p className="error-text" role="alert">{err}</p>}
          {!view || !m ? <div className="panel empty-main"><p>{accountId ? 'Loading the account…' : 'Choose an account.'}</p></div> : (
            <>
              <div className="panel account-bar">
                <div className="instrument-id">
                  <p className="sub"><span className={`badge ${isAI ? 'ok' : ''}`}>{isAI ? 'AI agent' : 'Rule bot'}</span> {view.agent.title}</p>
                  <h2 className="instrument-title">{view.account.name}</h2>
                  <p className="sub">Opened {view.account.start_date} with {fmtMoney(view.account.capital)}. Prices up to {view.latest_date}.</p>
                </div>
                <dl className="acct-stats">
                  <div><dt>{market.quote ? 'Value at last close' : 'Account value'}</dt><dd className="num">{fmtMoney(m.end_equity)}</dd></div>
                  {market.quote && <div><dt>Value now</dt><dd className="num">{fmtMoney(liveValue(view, market.quote))}</dd></div>}
                  <div><dt>Return</dt><dd className={`num ${tone(m.total_return_pct)}`}>{fmtPct(m.total_return_pct)}</dd></div>
                  <div><dt>vs holding</dt><dd className={`num ${tone(vs)}`}>{vs >= 0 ? '+' : ''}{vs.toFixed(1)} pts</dd></div>
                  <div><dt>Trades</dt><dd className="num">{m.trades}</dd></div>
                  <div><dt>{view.interval && view.interval !== '1d' ? 'Bars followed' : 'Days followed'}</dt><dd className="num">{m.bars}</dd></div>
                </dl>
              </div>

              <ResultDetail result={view.result} />

              {view.decisions.length > 0 && (
                <section className="panel sub-section">
                  <h3 className="panel-title">Logbook</h3>
                  <DecisionLog decisions={[...view.decisions].reverse()} roles={view.agent.kind === 'ai-crew' ? ['Research analyst', 'Financial analyst'] : undefined} />
                </section>
              )}
            </>
          )}
        </section>

        <aside className="panel ticket" aria-label="Today">
          <h2 className="panel-title">Today</h2>
          {!view ? <p className="field-note">Choose an account.</p> : (
            <>
              <section className={`today ${(view.today.action ?? 'none').toLowerCase()}`} aria-label="Latest decision">
                <p className="today-label">{view.today.date.length > 10 ? `${who}'s call after the ${view.today.date.slice(11)} bar (${view.today.date.slice(0, 10)})` : `${who}'s call after the close on ${view.today.date}`}</p>
                <p className="today-call">{view.today.action ? CALL[view.today.action] : 'Not decided'}</p>
                <p className="today-line">{todayLine(view)}</p>
                {view.today.reason && <p className="today-reason">{view.today.reason}</p>}
                {latest?.risk_plan && (view.today.action === 'BUY' || position(view).startsWith('Holding')) && (
                  <p className="today-reason">Stop-loss ₹{latest.risk_plan.stop} ({latest.risk_plan.stop_pct}%) · target ₹{latest.risk_plan.target} (+{latest.risk_plan.target_pct}%)</p>
                )}
              </section>
              <p className="position">{position(view)}</p>

              {market.live && (
                <section className="live-quote" aria-label="Live price" aria-live="polite">
                  <p className="today-label">
                    <span className={`live-dot ${market.quote?.session_open ? 'on' : ''}`} aria-hidden="true" />
                    {market.quote?.session_open ? 'Market open' : 'Market closed'} · {view.account.symbol}
                  </p>
                  {market.quote ? (
                    <>
                      <p className="live-price num">
                        ₹{market.quote.price.toFixed(2)}{' '}
                        {market.quote.change_pct !== null && <span className={market.quote.change_pct > 0 ? 'pos' : market.quote.change_pct < 0 ? 'neg' : ''}>{market.quote.change_pct > 0 ? '▲' : market.quote.change_pct < 0 ? '▼' : ''} {fmtPct(market.quote.change_pct)}</span>}
                      </p>
                      <p className="field-note">Last trade {market.quote.time ? market.quote.time.slice(11, 16) + ' IST, ' + market.quote.time.slice(0, 10) : 'time unknown'}. Yahoo Finance, about 15 minutes delayed. Updates every minute.</p>
                    </>
                  ) : <p className="field-note">{market.qErr ?? 'Fetching the live price…'}</p>}
                </section>
              )}

              {status && (status.rate_limited || status.loop.last_error) && (
                <p className="field-note warn" role="status">
                  {status.rate_limited ? `Yahoo Finance is limiting requests (${status.calls_last_hour} calls in the last hour). Live prices resume in about ${status.retry_in_s} s.`
                    : `Last live update problem: ${status.loop.last_error}`}
                </p>
              )}

              <div className="move">
                <h3>Move forward</h3>
                <p className="field-note">{view.data_note}</p>
                {isNewsAgent && (
                  <label className="confirm">
                    <input type="checkbox" checked={auto} onChange={e => { setAuto(e.target.checked); writeAuto(view.account.id, e.target.checked) }} />
                    <span>Decide new bars automatically while this page is open, with the AI you connected
                      (about {CALLS[view.agent.kind] * ({ '1d': 1, '15m': 25, '30m': 13 }[view.interval ?? '1d'] ?? 1)} AI calls per trading day; free tiers may refuse some).
                      {status?.loop.background_ai ? ' The server\'s own free AI also decides them when this page is closed.' : ''}</span>
                  </label>
                )}
                {isAI && view.pending_days.length > 0 && (
                  <button className="btn primary block" onClick={decide} disabled={running}>Ask the agent to decide {view.pending_days.length} day{view.pending_days.length > 1 ? 's' : ''}</button>
                )}
                {view.account.synthetic ? (
                  <button className="btn cta block" disabled={busy || running} onClick={() => act(() => api.saPaperNextDay(view.account.id))}>Next trading day</button>
                ) : view.can_refresh ? (
                  <button className="btn cta block" disabled={busy || running} onClick={() => act(() => api.saPaperRefresh(view.account.id))}>Fetch the latest prices</button>
                ) : null}
              </div>
              {live && running && <JobProgress job={live} label="The agent is deciding" note="About 30 seconds to 10 minutes per day, depending on the agent." />}

              <footer className="account-foot">
                <DownloadCode agentId={view.agent.id} symbol={view.account.symbol?.replace(/\.NS$/, '') ?? 'INFY'} />
                <button className="link-btn danger" onClick={remove}>Delete this account</button>
              </footer>
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
