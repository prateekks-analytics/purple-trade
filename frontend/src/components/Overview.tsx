import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { BacktestResult, Dataset, SuperAgentInfo } from '../types'
import type { Holding } from '../lib/portfolio'
import { fmtMoney, fmtPct } from '../lib/tree'
import { LineChart } from './LineChart'
import { Spark } from './Charts'
import { isAgentAccount } from './Paper'
import { AskSentence, BotBadge, DeskRow, POPULAR } from './Desk'
import { IconSpark } from './Icons'
import { Watchlist } from './Watchlist'
import { isDone } from '../lib/quotes'
import { openAiConnect } from '../lib/aiSettings'

interface Board { bot: SuperAgentInfo; result: BacktestResult | null }

const CALL = { BUY: 'Buy', SELL: 'Sell', HOLD: 'Hold' } as const

export function Overview({ portfolio, total, onAsk, aiReady }: {
  portfolio: Holding[] | null
  total: { value: number; start: number; change: number; changePct: number; day: number } | null
  onAsk: (symbol: string) => void
  aiReady: boolean
}) {
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [board, setBoard] = useState<Board[] | null>(null)

  useEffect(() => {
    api.datasets().then(ds => { setDatasets(ds); setDataset(ds.find(d => !d.synthetic) ?? ds[0] ?? null) }).catch(() => setBoard([]))
  }, [])

  // Leaderboard: every rule bot replayed on the chosen prices (instant, no AI).
  useEffect(() => {
    if (!dataset) return
    let alive = true
    setBoard(null)
    api.saAgents().then(async agents => {
      const bots = agents.filter(a => a.kind === 'rules')
      const results = await Promise.all(bots.map(b => api.saRun(b.id, dataset.id, 5, []).then(r => (r.kind === 'rules' ? r.result : null)).catch(() => null)))
      // Rank by return; bots that never traded go last (a flat 0% is no result, not a good one).
      const score = (r: BacktestResult | null) => (!r ? -2e9 : r.trades.length === 0 ? -1e9 : r.metrics.total_return_pct)
      if (alive) setBoard(bots.map((bot, i) => ({ bot, result: results[i] })).sort((a, b) => score(b.result) - score(a.result)))
    }).catch(() => alive && setBoard([]))
    return () => { alive = false }
  }, [dataset])

  // Combined paper equity by date (each account carried forward on days it has no row).
  const combined = useMemo(() => {
    if (!portfolio?.length) return null
    const series = portfolio.filter(h => h.view).map(h => new Map(h.view!.result.equity.map(e => [e.date, e.equity])))
    const dates = [...new Set(series.flatMap(s => [...s.keys()]))].sort()
    if (dates.length < 2) return null
    const last = series.map(() => 0)
    const values = dates.map(d => series.reduce((sum, s, i) => { const v = s.get(d); if (v !== undefined) last[i] = v; return sum + (last[i] || 0) }, 0))
    return { dates, values }
  }, [portfolio])

  const holdBH = board?.[0]?.result?.metrics.buy_hold_return_pct
  const stock = dataset ? (dataset.synthetic ? 'Sample stock' : (dataset.symbol ?? dataset.name).replace(/\.NS$/, '')) : ''

  const [ask, setAsk] = useState('RELIANCE')
  const podium = board?.filter(b => b.result && b.result.trades.length > 0).slice(0, 3) ?? []
  const rest = board?.filter(b => !podium.includes(b)) ?? []
  const tone = (v: number | null | undefined) => (v == null ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : '')

  return (
    <div className="page wide home">
      <div className="home-grid">
      <Watchlist />
      <div className="home-main">
      <header className="greet">
        <h1>{greeting()}</h1>
        <p className="sub">{new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })}</p>
      </header>

      <a className="beat-banner" href="#/race">
        <span className="beat-banner-copy">
          <span className="kicker">Main goal</span>
          <b>Build a bot that stays ahead of NIFTY 50 for a week</b>
          <span className="sub">Replay past weeks, let the AI coach improve it, then race it live for 7 trading days.</span>
        </span>
        <span className="btn glow">Start</span>
      </a>

      <section className="hero" aria-label="Ask the AI agent about a stock">
        <div className="hero-copy">
          <AskSentence value={ask} onChange={setAsk} onSubmit={() => ask && onAsk(ask)} id="hero-symbol" />
          <div className="chips hero-chips" role="group" aria-label="Popular stocks">
            {POPULAR.map(p => <button key={p} type="button" className={`chip ${ask === p ? 'on' : ''}`} onClick={() => setAsk(p)}>{p}</button>)}
          </div>
          <div className="hero-actions">
            <button className="btn glow lg" onClick={() => ask && onAsk(ask)} disabled={!ask}><IconSpark /> Ask the agent</button>
            <span className="hero-note">Buy, hold or sell, with a stop-loss. About a minute.</span>
          </div>
        </div>
        <div className="hero-desk">
          <DeskRow />
          <p className="hero-desk-note">Six analysts check charts, news, trader chatter and financials, then argue it out.</p>
        </div>
      </section>

      <Checklist aiReady={aiReady} hasPaper={Boolean(portfolio?.length)} />

      <div className="path-grid">
        <a className="path-card bots" href="#/test">
          <span className="path-art" aria-hidden="true">
            <svg viewBox="0 0 160 70" width="100%" height="70" preserveAspectRatio="xMidYMid meet">
              {[18, 30, 24, 38, 33, 46, 40, 52, 47, 58].map((h, i) => (
                <rect key={i} x={6 + i * 15} y={66 - h} width="9" height={Math.max(8, h * 0.45)} rx="2" className={i % 3 === 1 ? 'down' : 'up'} />
              ))}
              <path d="M10 52 L55 38 L95 28 L150 8" className="trace" />
            </svg>
          </span>
          <span className="path-title">Test a rule bot</span>
          <span className="path-sub">Fixed rules, no AI. Every trade on past prices in a second.</span>
        </a>
        <a className="path-card build" href="#/build">
          <span className="path-art" aria-hidden="true">
            <span className="mini-rule"><i className="b">Buy</i> RSI(14) &lt; 30</span>
            <span className="mini-rule"><i className="s">Sell</i> RSI(14) &gt; 70</span>
          </span>
          <span className="path-title">Build your own bot</span>
          <span className="path-sub">Type an idea in plain words. Get exact rules you can edit.</span>
        </a>
        <a className="path-card paper" href="#/paper">
          <span className="path-art" aria-hidden="true">
            <b className="path-money num">{total ? fmtMoney(total.value) : '₹1,00,000'}</b>
            <span className="path-money-sub">virtual money</span>
          </span>
          <span className="path-title">Practise with paper money</span>
          <span className="path-sub">Follow the agent or a bot on live prices. No real orders.</span>
        </a>
      </div>

      <div className="grid-2">
        <section className="panel equity-panel" aria-labelledby="eq-h">
          <div className="panel-head">
            <div>
              <h2 id="eq-h" className="panel-title">Your paper money</h2>
              <p className="big-num">{total ? fmtMoney(total.value) : '—'}</p>
              {total && portfolio && portfolio.length > 0 && (
                <p className={`delta ${total.change >= 0 ? 'pos' : 'neg'}`}>
                  <span className="delta-pill">{total.change >= 0 ? '▲' : '▼'} {fmtMoney(Math.abs(total.change))} ({fmtPct(total.changePct)})</span>
                  <span className="sub">since opening, last day {total.day >= 0 ? '+' : '−'}{fmtMoney(Math.abs(total.day))}</span>
                </p>
              )}
            </div>
          </div>
          {combined ? (
            <LineChart dates={combined.dates} series={[{ key: 'eq', label: 'Paper money', color: 'var(--series-1)', values: combined.values }]}
              area height={220} ariaLabel="Combined value of all paper accounts" format={v => fmtMoney(v)} />
          ) : (
            <div className="empty-chart">
              <p>{portfolio === null ? 'Loading accounts…' : portfolio.length ? 'The chart starts once the accounts move forward a day.' : 'No paper accounts yet.'}</p>
              {portfolio !== null && !portfolio.length && <a className="btn primary" href="#/agent">Ask the agent</a>}
            </div>
          )}
        </section>

        <section className="panel" aria-labelledby="acc-h">
          <div className="panel-head">
            <h2 id="acc-h" className="panel-title">Accounts</h2>
            <a className="link-btn" href="#/paper">See all</a>
          </div>
          {!portfolio?.length ? <p className="field-note pad-x">{portfolio === null ? 'Loading…' : 'None yet.'}</p> : (
            <ul className="acct-list">
              {portfolio.map(({ account, view }) => {
                const m = view?.result.metrics
                const agent = isAgentAccount(account)
                return (
                  <li key={account.id}>
                    <a href={`#/paper/${account.id}`}>
                      {agent ? <span className="bot-badge md look-violet" aria-hidden="true"><IconSpark /></span> : <BotBadge id={account.agent_id} />}
                      <span className="acct-name"><b>{account.name}</b><span className="sub">{agent ? 'AI agent' : 'Rule bot'}, since {account.start_date}</span></span>
                      <span className="acct-num">
                        <b className="num">{m ? fmtMoney(m.end_equity) : '—'}</b>
                        <span className={`num small ${tone(m?.total_return_pct)}`}>{m ? fmtPct(m.total_return_pct) : ''}</span>
                      </span>
                      {view?.today.action && <span className={`call ${view.today.action.toLowerCase()}`}>{CALL[view.today.action]}</span>}
                    </a>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      </div>

      <section className="board" aria-labelledby="lb-h">
        <div className="board-head">
          <div>
            <h2 id="lb-h" className="section-title">Top rule bots on {stock || '…'}</h2>
            <p className="field-note">{dataset ? `${dataset.first_date} to ${dataset.last_date}, after fees. ` : ''}Just holding the stock: <b className={tone(holdBH)}>{holdBH === undefined ? '…' : fmtPct(holdBH)}</b></p>
          </div>
          {datasets.length > 1 && (
            <label className="inline-select">
              <span>Stock</span>
              <select value={dataset?.id ?? ''} onChange={e => setDataset(datasets.find(d => d.id === e.target.value) ?? null)}>
                {datasets.map(d => <option key={d.id} value={d.id}>{d.synthetic ? 'Sample stock (synthetic)' : (d.symbol ?? d.name)}</option>)}
              </select>
            </label>
          )}
        </div>
        {board === null ? <p className="field-note">Running the bots…</p> : (
          <>
            {podium.length > 0 && (
              <ol className="podium">
                {podium.map(({ bot, result }, i) => {
                  const m = result!.metrics
                  const vs = m.total_return_pct - m.buy_hold_return_pct
                  return (
                    <li key={bot.id} className={`podium-card rank-${i + 1}`}>
                      <a href={`#/test/${bot.id}`} aria-label={`Number ${i + 1}, ${bot.title}: ${fmtPct(m.total_return_pct)}. Test this bot`}>
                        <span className="podium-top"><BotBadge id={bot.id} size="lg" /><span className="podium-rank">#{i + 1}</span></span>
                        <span className="podium-name">{bot.title}</span>
                        <span className={`podium-ret num ${tone(m.total_return_pct)}`}>{fmtPct(m.total_return_pct)}</span>
                        <Spark values={result!.equity.map(e => e.equity)} width={240} height={40} label={`${bot.title} account value`} />
                        <span className="podium-meta">
                          <span className={tone(vs)}>{vs >= 0 ? '+' : ''}{vs.toFixed(1)} pts vs holding</span>
                          <span>{m.trades} trades</span>
                        </span>
                      </a>
                    </li>
                  )
                })}
              </ol>
            )}
            {rest.length > 0 && (
              <ul className="board-rest">
                {rest.map(({ bot, result }) => {
                  const m = result?.metrics
                  return (
                    <li key={bot.id}>
                      <a href={`#/test/${bot.id}`}>
                        <BotBadge id={bot.id} size="sm" />
                        <b>{bot.title}</b>
                        <span className={`num ${result?.trades.length ? tone(m?.total_return_pct) : 'muted'}`}>{!m ? '—' : result!.trades.length ? fmtPct(m.total_return_pct) : 'No trades'}</span>
                      </a>
                    </li>
                  )
                })}
              </ul>
            )}
          </>
        )}
        <p className="fineprint">Past results on one stock don't predict future returns. Not investment advice.</p>
      </section>
      </div>
      </div>
    </div>
  )
}

function greeting() {
  const h = Number(new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', hour12: false }).format(new Date()))
  return h < 5 ? 'Up late?' : h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

/** Alpaca-style first-run checklist, built from real state; hidden once done or dismissed. */
function Checklist({ aiReady, hasPaper }: { aiReady: boolean; hasPaper: boolean }) {
  const [, force] = useState(0)
  const [hidden, setHidden] = useState(() => { try { return localStorage.getItem('purple.checklist.hidden') === '1' } catch { return false } })
  useEffect(() => { const f = () => force(x => x + 1); window.addEventListener('purple:done', f); return () => window.removeEventListener('purple:done', f) }, [])
  const steps = [
    { id: 'ai', label: 'Connect a free AI', done: aiReady, act: <button className="btn sm" onClick={openAiConnect}>Connect</button> },
    { id: 'agent', label: 'Get your first call', done: isDone('agent'), act: <a className="btn sm" href="#/agent">Ask</a> },
    { id: 'test', label: 'Test a rule bot', done: isDone('test'), act: <a className="btn sm" href="#/test">Test</a> },
    { id: 'paper', label: 'Start a paper account', done: hasPaper, act: <a className="btn sm" href="#/paper">Open</a> },
  ]
  const n = steps.filter(x => x.done).length
  if (hidden || n === steps.length) return null
  return (
    <section className="checklist panel" aria-labelledby="ck-h">
      <div className="ck-head">
        <div>
          <h2 id="ck-h" className="panel-title">Get started</h2>
          <p className="sub">{n} of {steps.length} done</p>
        </div>
        <button className="link-btn muted" onClick={() => { setHidden(true); try { localStorage.setItem('purple.checklist.hidden', '1') } catch { /* ignore */ } }}>Hide</button>
      </div>
      <div className="ck-bar" role="progressbar" aria-valuemin={0} aria-valuemax={steps.length} aria-valuenow={n} aria-label="Getting started progress"><i style={{ width: `${(n / steps.length) * 100}%` }} /></div>
      <ol className="ck-steps">
        {steps.map(x => (
          <li key={x.id} className={x.done ? 'done' : ''}>
            <span className="ck-tick" aria-hidden="true">{x.done ? '✓' : ''}</span>
            <span className="ck-label">{x.label}{x.done && <span className="visually-hidden"> (done)</span>}</span>
            {!x.done && x.act}
          </li>
        ))}
      </ol>
    </section>
  )
}
