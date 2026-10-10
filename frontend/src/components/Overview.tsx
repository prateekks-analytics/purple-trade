import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { BacktestResult, Dataset, SuperAgentInfo } from '../types'
import type { Holding } from '../lib/portfolio'
import { fmtMoney, fmtPct } from '../lib/tree'
import { LineChart } from './LineChart'
import { Spark } from './Charts'

interface Board { bot: SuperAgentInfo; result: BacktestResult | null }

const CALL = { BUY: 'Buy', SELL: 'Sell', HOLD: 'Hold' } as const

export function Overview({ portfolio, total }: {
  portfolio: Holding[] | null
  total: { value: number; start: number; change: number; changePct: number; day: number } | null
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

  return (
    <div className="page wide">
      <header className="page-head row">
        <div>
          <h1>Overview</h1>
          <p className="lede">Your paper accounts and how the built-in bots have done on recent prices.</p>
        </div>
        <div className="head-actions">
          <a className="btn" href="#/build">Build a strategy</a>
          <a className="btn primary" href="#/test">Test a bot</a>
        </div>
      </header>

      <div className="grid-2">
        <section className="panel equity-panel" aria-labelledby="eq-h">
          <div className="panel-head">
            <div>
              <h2 id="eq-h" className="panel-title">Paper equity</h2>
              <p className="big-num">{total ? fmtMoney(total.value) : '—'}</p>
              {total && portfolio && portfolio.length > 0 && (
                <p className={`delta ${total.change >= 0 ? 'pos' : 'neg'}`}>
                  {total.change >= 0 ? '▲' : '▼'} {fmtMoney(Math.abs(total.change))} ({fmtPct(total.changePct)}) since the accounts opened
                  <span className="sub"> · last day {total.day >= 0 ? '+' : '−'}{fmtMoney(Math.abs(total.day))}</span>
                </p>
              )}
            </div>
          </div>
          {combined ? (
            <LineChart dates={combined.dates} series={[{ key: 'eq', label: 'Paper equity', color: 'var(--series-1)', values: combined.values }]}
              area height={220} ariaLabel="Combined value of all paper accounts" format={v => fmtMoney(v)} />
          ) : (
            <div className="empty-chart">
              <p>{portfolio === null ? 'Loading accounts…' : portfolio.length ? 'The chart starts after the accounts move forward a day.' : 'No paper accounts yet. Test a bot, then follow it with virtual money.'}</p>
              {portfolio !== null && !portfolio.length && <a className="btn primary" href="#/test">Test a bot</a>}
            </div>
          )}
        </section>

        <section className="panel" aria-labelledby="acc-h">
          <div className="panel-head">
            <h2 id="acc-h" className="panel-title">Paper accounts</h2>
            <a className="link-btn" href="#/paper">View all</a>
          </div>
          {!portfolio?.length ? <p className="field-note">{portfolio === null ? 'Loading…' : 'None yet.'}</p> : (
            <ul className="acct-list">
              {portfolio.map(({ account, view }) => {
                const m = view?.result.metrics
                return (
                  <li key={account.id}>
                    <a href={`#/paper/${account.id}`}>
                      <span className="acct-name"><b>{account.name}</b><span className="sub">Since {account.start_date}</span></span>
                      <Spark values={view?.result.equity.map(e => e.equity) ?? []} width={72} height={26} label={`${account.name} value trend`} />
                      <span className="acct-num">
                        <b className="num">{m ? fmtMoney(m.end_equity) : '—'}</b>
                        <span className={`num small ${m && m.total_return_pct > 0 ? 'pos' : m && m.total_return_pct < 0 ? 'neg' : ''}`}>{m ? fmtPct(m.total_return_pct) : ''}</span>
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

      <section className="panel" aria-labelledby="lb-h">
        <div className="panel-head">
          <div>
            <h2 id="lb-h" className="panel-title">Bot leaderboard</h2>
            <p className="field-note">Rule bots replayed on {stock || '…'}{dataset ? ` (${dataset.first_date} to ${dataset.last_date})` : ''}, with fees and slippage. Holding the stock returned {holdBH === undefined ? '…' : fmtPct(holdBH)}.</p>
          </div>
          {datasets.length > 1 && (
            <label className="inline-select">
              <span>Prices</span>
              <select value={dataset?.id ?? ''} onChange={e => setDataset(datasets.find(d => d.id === e.target.value) ?? null)}>
                {datasets.map(d => <option key={d.id} value={d.id}>{d.synthetic ? 'Sample stock (synthetic)' : (d.symbol ?? d.name)}</option>)}
              </select>
            </label>
          )}
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th scope="col">#</th><th scope="col">Bot</th><th scope="col">Account value</th><th scope="col" className="r">Return</th>
                <th scope="col" className="r">vs holding</th><th scope="col" className="r">Worst fall</th><th scope="col" className="r">Trades</th><th scope="col"><span className="visually-hidden">Action</span></th></tr>
            </thead>
            <tbody>
              {board === null ? <tr><td colSpan={8} className="field-note">Running the bots…</td></tr> : board.map(({ bot, result }, i) => {
                const m = result?.metrics
                const vs = m ? m.total_return_pct - m.buy_hold_return_pct : null
                return (
                  <tr key={bot.id}>
                    <td className="rank">{i + 1}</td>
                    <td><b>{bot.title}</b><div className="sub clamp">Buys when {bot.describe?.entry}</div></td>
                    <td><Spark values={result?.equity.map(e => e.equity) ?? []} label={`${bot.title} account value`} /></td>
                    <td className={`r num ${m && m.total_return_pct > 0 ? 'pos' : m && m.total_return_pct < 0 ? 'neg' : ''}`}>{m ? fmtPct(m.total_return_pct) : '—'}</td>
                    <td className={`r num ${vs !== null && vs > 0 ? 'pos' : vs !== null && vs < 0 ? 'neg' : ''}`}>{vs === null ? '—' : `${vs >= 0 ? '+' : ''}${vs.toFixed(1)} pts`}</td>
                    <td className="r num">{m ? fmtPct(m.max_drawdown_pct) : '—'}</td>
                    <td className="r num">{m?.trades ?? '—'}</td>
                    <td className="r"><a className="btn sm" href={`#/test/${bot.id}`}>Test</a></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="fineprint">Past results on one stock. They do not predict future returns. Not investment advice.</p>
      </section>
    </div>
  )
}
