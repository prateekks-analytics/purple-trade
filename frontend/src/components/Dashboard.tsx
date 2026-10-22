import { useMemo, useState } from 'react'
import { api } from '../api'
import type { DeskView } from '../types'
import { fmtMoney } from '../lib/tree'
import { useQuotes } from '../lib/quotes'
import { nseStatus } from '../lib/portfolio'
import { errText } from './AgentBits'
import { AgentMark, PortfolioChart, clock, dayLabel, decidedAt, pct, signed, useBacktest, useDesk, when } from './DeskBits'

const AMOUNTS = [100000, 500000, 1000000]
const SPANS = [{ days: 7, label: '7 days' }, { days: 30, label: '30 days' }, { days: 0, label: 'Until I stop' }]

export function Dashboard() {
  const { view, setView, error } = useDesk()
  const [fresh, setFresh] = useState(false)
  if (!view) return <div className="page wide"><p className="page-loading">{error || 'Loading your bot…'}</p></div>
  return view.bot && !fresh
    ? <Running view={view} setView={setView} onNew={() => setFresh(true)} />
    : <Launch onStarted={v => { setFresh(false); setView(v) }} />
}

function Launch({ onStarted }: { onStarted: (v: DeskView) => void }) {
  const [amount, setAmount] = useState(500000)
  const [days, setDays] = useState(7)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const { bt } = useBacktest()
  const start = async () => {
    setBusy(true); setError('')
    try { onStarted(await api.deskStart(amount, days)) } catch (e) { setError(errText(e)); setBusy(false) }
  }
  return (
    <div className="page wide dash">
      <section className="launch glass" aria-labelledby="launch-h">
        <div className="launch-copy">
          <p className="kicker">Purple Desk · AI trading bot</p>
          <h1 id="launch-h" className="launch-title">Five AI agents. One portfolio. <span className="grad">Beat NIFTY 50.</span></h1>
          <p className="launch-sub">Every 30 minutes the agents debate, the winner's plan is traded on 10 large NSE stocks with paper money, and the bot learns from the results.</p>
          <div className="launch-form">
            <label className="amount-field">
              <span>Starting money</span>
              <span className="amount-input"><b>₹</b><input inputMode="numeric" value={amount.toLocaleString('en-IN')}
                onChange={e => setAmount(Number(e.target.value.replace(/\D/g, '')) || 0)} aria-label="Starting money in rupees" /></span>
            </label>
            <div className="seg" role="group" aria-label="Quick amounts">
              {AMOUNTS.map(a => <button key={a} type="button" className={amount === a ? 'on' : ''} onClick={() => setAmount(a)}>{fmtMoney(a)}</button>)}
            </div>
            <div className="seg" role="radiogroup" aria-label="How long">
              {SPANS.map(s => <button key={s.days} type="button" role="radio" aria-checked={days === s.days} className={days === s.days ? 'on' : ''} onClick={() => setDays(s.days)}>{s.label}</button>)}
            </div>
            <button className="btn glow lg" onClick={start} disabled={busy || amount < 10000}>{busy ? 'Starting…' : 'Start the bot'}</button>
            {error && <p className="hero-error" role="alert">{error}</p>}
          </div>
        </div>
        <div className="launch-proof">
          <p className="kicker">Replayed on the last {bt ? '40' : '…'} trading days</p>
          {bt ? (
            <>
              <p className="proof-line"><b className={bt.edge >= 0 ? 'pos' : 'neg'}>{signed(bt.edge)}</b> {bt.edge >= 0 ? 'ahead of' : 'behind'} NIFTY 50 on ₹5 lakh</p>
              <PortfolioChart series={bt.series} height={170} label="Bot (replay)" />
              <p className="field-note">Bot {pct(bt.return_pct)} · NIFTY 50 {pct(bt.market_pct)} · ahead in {bt.weeks_beat} of {bt.weeks.length} weeks. Past replay without AI; not a promise.</p>
            </>
          ) : <div className="proof-skeleton" aria-hidden="true" />}
        </div>
      </section>
    </div>
  )
}

function Running({ view, setView, onNew }: { view: DeskView; setView: (v: DeskView) => void; onNew: () => void }) {
  const bot = view.bot!
  const holdings = view.holdings ?? []
  const quotes = useQuotes(holdings.map(h => h.symbol))
  const nse = nseStatus()
  const live = nse.open && holdings.length > 0 && holdings.every(h => quotes[h.symbol])
  const value = live ? (view.cash ?? 0) + holdings.reduce((s, h) => s + h.qty * (quotes[h.symbol]?.price ?? h.price), 0) : view.value!
  const cap = view.capital!
  const series = view.series ?? []
  const mkt = series.length ? series[series.length - 1].market : cap
  const edge = value - mkt
  const latest = view.decisions?.[0]
  const [busy, setBusy] = useState('')
  const running = bot.status === 'running'
  const today = useMemo(() => {
    const day = series.length ? series[series.length - 1].time.slice(0, 10) : ''
    const first = series.find(s => s.time.startsWith(day))
    const prev = series[series.indexOf(first!) - 1]
    return prev ? value - prev.value : 0
  }, [series, value])

  const act = async (what: 'stop' | 'decide') => {
    setBusy(what)
    try { setView(what === 'stop' ? await api.deskStop() : await api.deskDecide()) } catch { /* shown on next refresh */ }
    setBusy('')
  }

  return (
    <div className="page wide dash">
      <section className="dash-top" aria-label="Portfolio">
        <div className="value-card glass">
          <p className="kicker">Portfolio value {live && <span className="live-tag">Live</span>}</p>
          <p className="value-big num">{fmtMoney(value)}</p>
          <p className="value-sub">
            <span className={`num ${value >= cap ? 'pos' : 'neg'}`}>{signed(value - cap)} ({pct((value / cap - 1) * 100)})</span>
            <span className="sub"> since start · today <span className={`num ${today >= 0 ? 'pos' : 'neg'}`}>{signed(today)}</span></span>
          </p>
        </div>
        <div className={`edge-card glass ${edge >= 0 ? 'ahead' : 'behind'}`}>
          <p className="kicker">Against NIFTY 50</p>
          <p className="edge-big num">{signed(edge)}</p>
          <p className="sub">{edge >= 0 ? 'ahead of' : 'behind'} the same money in NIFTY 50 ({pct(view.market_pct ?? 0)})</p>
        </div>
        <div className="status-card glass">
          <p className={`bot-state ${running ? 'on' : ''}`}><i aria-hidden="true" />{running ? (nse.open ? 'Trading' : 'Waiting for market') : bot.status === 'finished' ? 'Finished' : 'Stopped'}</p>
          <p className="sub">{bot.days ? `Day ${Math.min(view.day ?? 0, bot.days)} of ${bot.days}` : `Day ${view.day ?? 0}`} · {fmtMoney(cap)} start</p>
          {running && view.next_decision && <p className="sub">Next decision {view.next_decision} IST</p>}
          {view.guard?.length ? <p className="guard-note" role="status">Crash guard, {view.guard[view.guard.length - 1].time}: {view.guard[view.guard.length - 1].reason}</p> : <p className="sub">Crash guard on: checks every minute</p>}
          {running && !view.ai && <p className="warn-note">No AI connected on the server: the bot follows the best track record.</p>}
          <div className="status-actions">
            {running && <button className="btn sm quiet" onClick={() => act('decide')} disabled={busy !== ''}>{busy === 'decide' ? 'Deciding…' : 'Decide now'}</button>}
            {running && <button className="btn sm quiet" onClick={() => act('stop')} disabled={busy !== ''}>Stop</button>}
            {!running && <button className="btn sm" onClick={onNew}>Start a new bot</button>}
          </div>
        </div>
      </section>

      <section className="panel chart-card" aria-labelledby="perf-h">
        <div className="panel-head">
          <h2 id="perf-h" className="panel-title">Performance</h2>
          <span className="sub">Every 30 minutes since {when(bot.start_time)} · ▲ bought ▼ sold</span>
        </div>
        {series.length > 1
          ? <PortfolioChart series={series} trades={view.trades} height={300} />
          : <p className="empty-chart">The chart fills in as the market moves. First trades go in at the next market open.</p>}
      </section>

      <div className="dash-grid">
        <section className="panel decision-card" aria-labelledby="dec-h">
          <div className="panel-head">
            <h2 id="dec-h" className="panel-title">Latest decision</h2>
            {latest && <span className="sub">{decidedAt(latest.time)}</span>}
          </div>
          {latest ? (
            <div className="decision-body">
              <p className="winner"><AgentMark id={latest.winner} size="lg" /><span><b>{latest.winner_name}</b> won the debate{latest.confidence != null && <span className="sub"> · {latest.confidence}% sure</span>}</span></p>
              <p className="reason">{latest.reason}</p>
              <div className="target-chips">
                {Object.keys(latest.targets).length
                  ? Object.entries(latest.targets).map(([s, w]) => <span key={s} className="tchip">{s}<b>{Math.round(w * 100)}%</b></span>)
                  : <span className="tchip cash">All cash</span>}
              </div>
              <a className="link-btn" href="#/bot">See the full debate →</a>
            </div>
          ) : <p className="pad">The first debate is running. It takes up to a minute.</p>}
        </section>

        <section className="panel" aria-labelledby="hold-h">
          <div className="panel-head"><h2 id="hold-h" className="panel-title">Holdings</h2><span className="sub">Cash {fmtMoney(view.cash ?? 0)}</span></div>
          {holdings.length ? (
            <ul className="hold-list">
              {holdings.map(h => {
                const px = live ? quotes[h.symbol]?.price ?? h.price : h.price
                const gain = h.avg ? (px / h.avg - 1) * 100 : 0
                return (
                  <li key={h.symbol}>
                    <span className="hold-sym"><b>{h.symbol}</b><span className="sub">{h.qty} shares{h.avg ? ` · avg ${fmtMoney(h.avg)}` : ''}</span></span>
                    <span className="hold-num"><b className="num">{fmtMoney(h.qty * px)}</b><span className={`num small ${gain >= 0 ? 'pos' : 'neg'}`}>{pct(gain)}</span></span>
                  </li>
                )
              })}
            </ul>
          ) : <p className="pad">All in cash right now.</p>}
        </section>
      </div>

      <section className="panel" aria-labelledby="tr-h">
        <div className="panel-head"><h2 id="tr-h" className="panel-title">Trades</h2><span className="sub">{view.trades?.length ?? 0} so far</span></div>
        {view.trades?.length ? (
          <div className="trade-table" role="table" aria-label="Trades, newest first">
            {view.trades.slice(0, 30).map((t, i) => (
              <div key={i} role="row" className="trade-row">
                <span role="cell" className="t-time">{dayLabel(t.time)} <b>{clock(t.time)}</b></span>
                <span role="cell"><span className={`side ${t.side.toLowerCase()}`}>{t.side === 'BUY' ? 'Bought' : 'Sold'}</span></span>
                <span role="cell" className="t-sym"><b>{t.symbol}</b> × {t.qty}</span>
                <span role="cell" className="num">{fmtMoney(t.price)}</span>
                <span role="cell" className="num t-val">{fmtMoney(t.value)}</span>
                <span role="cell" className="t-why">{t.why && <><AgentMark id={t.why} size="sm" />{AGENT_NAMES[t.why] ?? t.why}</>}</span>
              </div>
            ))}
          </div>
        ) : <p className="pad">No trades yet. Orders fill at the open of the next 30-minute bar.</p>}
      </section>
      <p className="field-note foot-note">Paper money only. Prices from Yahoo Finance, unofficial. Fees and slippage included; exchange holidays not checked.{view.last_error ? ` Last issue: ${view.last_error}` : ''}</p>
    </div>
  )
}

export const AGENT_NAMES: Record<string, string> = { momentum: 'Momentum', trend: 'Trend rider', dip: 'Dip buyer', news: 'News & social', guard: 'Risk guard' }
