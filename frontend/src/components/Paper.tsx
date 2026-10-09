import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Job, PaperAccount, PaperView } from '../types'
import { fmtMoney, fmtPct } from '../lib/tree'
import { DecisionLog, DownloadCode, errText, JobProgress, useJob } from './AgentBits'
import { ResultDetail } from './Results'

const CALL = { BUY: 'Buy', SELL: 'Sell', HOLD: 'Hold' } as const

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

function todayLine(v: PaperView) {
  const a = v.today.action
  if (!a) return 'The agent has not decided the latest day yet.'
  if (a === 'HOLD') return 'No trade: keep the account as it is.'
  return a === 'BUY' ? "It would buy at the next trading day's opening price." : "It would sell at the next trading day's opening price."
}

export function Paper({ accountId, onSelect, onTest }: { accountId?: string; onSelect: (id: string) => void; onTest: () => void }) {
  const [accounts, setAccounts] = useState<PaperAccount[] | null>(null)
  const [view, setView] = useState<PaperView | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [job, setJob] = useState<Job | null>(null)

  const refreshList = () => api.saPaperList().then(setAccounts).catch(e => setErr(errText(e)))
  useEffect(() => { refreshList() }, [])

  useEffect(() => {
    setView(null); setErr(null); setJob(null)
    if (accountId) api.saPaper(accountId).then(setView).catch(e => setErr(errText(e)))
  }, [accountId])

  // open the newest account when none is chosen
  useEffect(() => { if (!accountId && accounts?.length) onSelect(accounts[0].id) }, [accountId, accounts]) // eslint-disable-line react-hooks/exhaustive-deps

  const live = useJob(job, j => { if (j.status === 'done' && view) api.saPaper(view.account.id).then(setView); if (j.status === 'error') setErr(j.error) })
  const running = live?.status === 'running'

  const act = async (fn: () => Promise<PaperView>) => {
    setBusy(true); setErr(null)
    try { setView(await fn()) } catch (e) { setErr(errText(e)) } finally { setBusy(false) }
  }
  const decide = async () => {
    if (!view) return
    const slow = view.agent.kind === 'ta-original'
    if (slow && !confirm(`The original TradingAgents needs about 10 minutes per trading day on the local AI (${view.pending_days.length} day${view.pending_days.length > 1 ? 's' : ''} pending). Start now?`)) return
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
          <p className="lede">A paper account follows a bot forward with virtual money, one trading day at a time, so you can see how it behaves on days it has not seen.</p>
        </header>
        <div className="empty">
          <p>No paper accounts yet. Test a bot first; if the verdict looks promising, start a paper account from there.</p>
          <button className="btn primary" onClick={onTest}>Test a bot</button>
        </div>
      </div>
    )
  }

  const m = view?.result.metrics
  const isAI = view && view.agent.kind !== 'rules'

  return (
    <div className="page wide">
      <header className="page-head">
        <h1>Paper accounts</h1>
        <p className="lede">Each account follows one bot with virtual money from the day it was opened. Move it forward a day at a time and read what the bot did and why.</p>
      </header>
      <div className="paper-layout">
        <nav className="account-list" aria-label="Paper accounts">
          <ul>
            {(accounts ?? []).map(a => (
              <li key={a.id}>
                <button className={a.id === accountId ? 'on' : ''} aria-current={a.id === accountId ? 'page' : undefined} onClick={() => onSelect(a.id)}>
                  <b>{a.name}</b>
                  <span className="sub">Opened {a.start_date} with {fmtMoney(a.capital)}{a.synthetic ? ', synthetic prices' : ''}</span>
                </button>
              </li>
            ))}
          </ul>
          <button className="btn quiet" onClick={onTest}>Open another from Test a bot</button>
        </nav>

        <div className="account">
          {err && <p className="error-text" role="alert">{err}</p>}
          {!view || !m ? <p className="field-note">{accountId ? 'Loading the account…' : 'Choose an account.'}</p> : (
            <>
              <div className="account-head">
                <h2>{view.account.name}</h2>
                <p className="sub">Opened {view.account.start_date} with {fmtMoney(view.account.capital)}. Prices up to {view.latest_date}.</p>
              </div>

              <section className={`today ${(view.today.action ?? 'none').toLowerCase()}`} aria-label="Latest decision">
                <p className="today-label">Bot's call after the close on {view.today.date}</p>
                <p className="today-call">{view.today.action ? CALL[view.today.action] : 'Not decided yet'}</p>
                <p>{todayLine(view)}</p>
                {view.today.reason && <p className="today-reason">{view.today.reason}</p>}
              </section>

              <section className="move" aria-label="Move the account forward">
                <div>
                  <h3>Move forward</h3>
                  <p className="field-note">{view.data_note}</p>
                </div>
                <div className="move-actions">
                  {isAI && view.pending_days.length > 0 && (
                    <button className="btn primary" onClick={decide} disabled={running}>Ask the agent to decide {view.pending_days.length} day{view.pending_days.length > 1 ? 's' : ''}</button>
                  )}
                  {view.account.synthetic ? (
                    <button className="btn primary" disabled={busy || running} onClick={() => act(() => api.saPaperNextDay(view.account.id))}>Next trading day</button>
                  ) : view.can_refresh ? (
                    <button className="btn primary" disabled={busy || running} onClick={() => act(() => api.saPaperRefresh(view.account.id))}>Fetch the latest prices</button>
                  ) : null}
                </div>
              </section>
              {live && running && <JobProgress job={live} label="The agent is deciding" note="About 30 seconds to 10 minutes per day, depending on the agent." />}

              <section aria-label="Account summary">
                <p className="position">{position(view)}</p>
                <dl className="facts compact">
                  <div className="fact"><dt>Account value</dt><dd className="fact-value">{fmtMoney(m.end_equity)}</dd><dd className="fact-note">Started at {fmtMoney(m.start_equity)}</dd></div>
                  <div className="fact"><dt>Return so far</dt><dd className={`fact-value ${m.total_return_pct > 0 ? 'pos' : m.total_return_pct < 0 ? 'neg' : ''}`}>{fmtPct(m.total_return_pct)}</dd><dd className="fact-note">Holding the stock: {fmtPct(m.buy_hold_return_pct)}</dd></div>
                  <div className="fact"><dt>Completed trades</dt><dd className="fact-value">{m.trades}</dd><dd className="fact-note">{m.win_rate_pct === null ? 'None closed yet' : `${m.win_rate_pct.toFixed(0)}% made money`}</dd></div>
                  <div className="fact"><dt>Trading days followed</dt><dd className="fact-value">{m.bars}</dd><dd className="fact-note">{m.first_date} to {m.last_date}</dd></div>
                </dl>
              </section>

              <ResultDetail result={view.result} />

              {view.decisions.length > 0 && (
                <section className="sub-section">
                  <h3>Logbook</h3>
                  <DecisionLog decisions={[...view.decisions].reverse()} />
                </section>
              )}

              <footer className="account-foot">
                <DownloadCode agentId={view.agent.id} symbol={view.account.symbol?.replace(/\.NS$/, '') ?? 'INFY'} />
                <button className="link-btn danger" onClick={remove}>Delete this account</button>
              </footer>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
