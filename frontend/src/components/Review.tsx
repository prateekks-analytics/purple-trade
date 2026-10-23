import { useEffect, useState } from 'react'
import { api } from '../api'
import type { CoachReport, JournalEntry, JournalItem, ReportCard } from '../types'
import { errText } from './AgentBits'

const longDay = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })
const rupees = (x: number | null | undefined) => x == null ? '—' : `₹${Math.round(Math.abs(x)).toLocaleString('en-IN')}`
const signedRupees = (x: number | null | undefined) => x == null ? '—' : `${x < 0 ? '−' : '+'}${rupees(x)}`
const pctText = (x: number | null | undefined) => x == null ? '—' : `${x > 0 ? '+' : x < 0 ? '−' : ''}${Math.abs(x).toFixed(2)}%`
const tone = (x: number | null | undefined) => x == null || x === 0 ? '' : x > 0 ? 'pos' : 'neg'

const GRADE: Record<string, string> = { strong: 'Strong', average: 'Average', weak: 'Weak' }
const TRUST: Record<string, string> = { more: 'Trust more', same: 'Keep as is', less: 'Trust less' }
const HELPED: Record<string, string> = { yes: 'Helped', no: 'Did not help', 'too early': 'Too early to tell' }

function Numbers({ r }: { r: CoachReport }) {
  const n = r.numbers
  const cards = [
    { label: 'The bot today', value: signedRupees(n.company_rupees), sub: pctText(n.desk_pct), t: tone(n.desk_pct) },
    { label: 'NIFTY 50 today', value: pctText(n.nifty_pct), sub: 'the market', t: tone(n.nifty_pct) },
    { label: 'Old bot today', value: pctText(n.twin_pct), sub: 'for comparison', t: tone(n.twin_pct) },
    { label: 'Since the start', value: pctText(n.company_since_start_pct), sub: `NIFTY ${pctText(n.nifty_since_start_pct)}`, t: tone(n.company_since_start_pct) },
  ]
  return (
    <div className="rv-numbers">
      {cards.map(c => <div key={c.label}><span>{c.label}</span><b className={c.t}>{c.value}</b><small>{c.sub}</small></div>)}
    </div>
  )
}

function Costs({ r }: { r: CoachReport }) {
  const d = r.costs.day
  if (!d) return null
  const gain = r.numbers.company_rupees ?? 0
  const share = gain > 0 ? Math.round((d.total / gain) * 100) : null
  return (
    <section className="rv-box rv-costs" aria-label="Taxes and charges">
      <h3>Taxes and charges a real trader would pay</h3>
      <p className="rv-big">{rupees(d.total)} <small>today{share != null ? ` · about ${share}% of the day's gain` : ''}</small></p>
      <ul>
        <li>Charges on buying and selling: <b>{rupees(d.charges_total)}</b> (mostly the securities transaction tax, {rupees(d.charges.stt)})</li>
        <li>Income tax on the profit it booked: <b>{rupees(d.tax)}</b></li>
        <li>It bought and sold {rupees(d.turnover)} of shares in total, {rupees(d.intraday_value)} of it bought and sold on the same day.</li>
        <li>Since the start: {rupees(r.costs.since_start?.total)}. Moving ₹1 lakh from one stock to another costs about {rupees(r.costs.switch_pct * 1000)}.</li>
      </ul>
      {r.costs.note && <p className="rv-note">{r.costs.note}</p>}
      <p className="sub">Shown separately: the returns above are not reduced by these amounts.</p>
    </section>
  )
}

/** On crash days: what buying back after a bounce would have made (tracked, not traded), and the running tally. */
function GuardTest({ r, all }: { r: CoachReport; all: CoachReport[] }) {
  const g = r.guard_test
  if (!g) return null
  const days = all.filter(x => x.guard_test && x.day <= r.day)
  const total = days.reduce((s, x) => s + (x.guard_test?.extra_rupees ?? 0), 0)
  const wins = days.filter(x => (x.guard_test?.extra_rupees ?? 0) > 0).length
  return (
    <section className="rv-box" aria-label="Crash-day test">
      <h3>Crash day: would buying back have paid?</h3>
      <p>The crash guard sold {rupees(g.sold_value)} of shares at {g.sold_at} and the bot stayed in cash.{' '}
        {g.bought_back_at
          ? <>Buying the same shares back at {g.bought_back_at}, once the market had bounced {g.rebound_pct.toFixed(1)}% from its low, would have
            {g.extra_rupees >= 0 ? <> made <b className="pos">{rupees(g.extra_rupees)} more</b></> : <> lost <b className="neg">{rupees(g.extra_rupees)}</b></>} by the close.</>
          : <>The market never bounced {g.rebound_pct.toFixed(1)}% from its low, so there would have been no buy-back.</>}
      </p>
      <p className="sub">Tracked, not traded. Crash days so far: {days.length} of 5 · buy-back better on {wins} · total {signedRupees(total)}. After 5 crash days the coach recommends whether to build it.</p>
    </section>
  )
}

function Card({ c }: { c: ReportCard }) {
  return (
    <tr>
      <th scope="row"><span className="rv-name">{c.name}</span><small>{c.team}</small></th>
      <td className={`num ${tone(c.today_pct)}`} data-label="Today">{pctText(c.today_pct)}</td>
      <td className={`num ${tone(c.since_start_pct)}`} data-label="Since start">{pctText(c.since_start_pct)}</td>
      <td className="num" data-label="Trades">{c.trades_today}<small>{c.costs_today ? ` · ${rupees(c.costs_today)}` : ''}</small></td>
      <td>{c.grade ? <span className={`rv-grade g-${c.grade}`}>{GRADE[c.grade]}</span> : <span className="sub">—</span>}
        {c.trust && <small className="rv-trust">{TRUST[c.trust]}</small>}</td>
      <td className="rv-why">{c.why}</td>
    </tr>
  )
}

function ReportView({ r, first, all }: { r: CoachReport; first: boolean; all: CoachReport[] }) {
  const cards = [...r.cards].sort((a, b) => (b.today_pct ?? -99) - (a.today_pct ?? -99))
  return (
    <article className="panel review-card" aria-labelledby={`rv-${r.day}`}>
      <header className="review-head">
        <h2 id={`rv-${r.day}`} className="panel-title">{longDay(r.day)}</h2>
        {first && <span className="badge ok">Latest</span>}
      </header>
      <p className="review-summary">{r.headline}</p>
      <p className="rv-story">{r.story}</p>
      <Numbers r={r} />
      <Costs r={r} />
      <GuardTest r={r} all={all} />
      <section className="rv-box" aria-label="Report card">
        <h3>Report card</h3>
        <p className="sub">Each analyst runs its own paper portfolio on the same money. The coach's grade tells the manager whose ideas to lean on tomorrow.</p>
        <div className="rv-table-wrap">
          <table className="rv-table">
            <thead><tr><th scope="col">Analyst</th><th scope="col">Today</th><th scope="col">Since start</th><th scope="col">Trades · cost</th><th scope="col">Grade</th><th scope="col">Why</th></tr></thead>
            <tbody>{cards.map(c => <Card key={c.id} c={c} />)}</tbody>
          </table>
        </div>
      </section>
      {r.advice_check.length > 0 && (
        <section className="rv-box" aria-label="Is the advice working">
          <h3>Is yesterday's advice working?</h3>
          <ul className="rv-list">
            {r.advice_check.map(a => (
              <li key={a.rule}><span className={`rv-helped h-${a.helped.replace(' ', '-')}`}>{HELPED[a.helped]}</span>
                <span><b>Rule {a.rule}.</b> {a.followed}{a.note ? ` ${a.note}` : ''}</span></li>
            ))}
          </ul>
        </section>
      )}
      {r.rule_changes.length > 0 && (
        <section className="rv-box rule" aria-label="Rule changes">
          <h3>What the coach changed</h3>
          <ul className="rv-list plain">{r.rule_changes.map(x => <li key={x}>{x}</li>)}</ul>
        </section>
      )}
      {r.ideas.length > 0 && (
        <section className="rv-box" aria-label="Ideas to earn more">
          <h3>Ideas to earn more</h3>
          <ul className="rv-ideas">
            {r.ideas.map(i => (
              <li key={i.title}>
                <div><b>{i.title}</b><span className={`rv-who w-${i.who}`}>{i.who === 'coach' ? 'Coach is trying it' : 'Needs your OK'}</span></div>
                <p>{i.detail}</p>
                {i.expected && <p className="sub">Expected: {i.expected}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {r.watch && <p className="rv-watch"><b>Tomorrow the coach will check:</b> {r.watch}</p>}
    </article>
  )
}

/** Older days that only have a journal entry (before the full report existed). */
const MAIN: [string, string, string][] = [
  ['good calls', 'What went well', 'good'],
  ['mistakes', 'What went wrong', 'bad'],
  ['playbook', 'Rule changes', 'rule'],
  ['watch next', 'Watch tomorrow', 'watch'],
]

function JournalCard({ e, first }: { e: JournalEntry; first: boolean }) {
  const find = (key: string) => e.items.find(i => i.label.toLowerCase() === key)
  const result = find('result')
  const rest = e.items.filter(i => i !== result && !MAIN.some(([k]) => k === i.label.toLowerCase()))
  const extra: JournalItem[] = e.summary && result ? [result, ...rest] : rest
  return (
    <article className="panel review-card" aria-labelledby={`rv-${e.day}`}>
      <header className="review-head">
        <h2 id={`rv-${e.day}`} className="panel-title">{longDay(e.day)}</h2>
        {first ? <span className="badge ok">Latest</span> : <span className="sub">Short note</span>}
      </header>
      <p className="review-summary">{e.summary ?? result?.text ?? 'The coach wrote no summary for this day.'}</p>
      <dl className="review-items">
        {MAIN.map(([key, label, t]) => {
          const it = find(key)
          return it ? <div key={key} className={`review-item ${t}`}><dt>{label}</dt><dd>{it.text}</dd></div> : null
        })}
      </dl>
      {extra.length > 0 && (
        <details className="review-more">
          <summary>More detail</summary>
          <dl>{extra.map(i => <div key={i.label}><dt>{i.label}</dt><dd>{i.text}</dd></div>)}</dl>
        </details>
      )}
    </article>
  )
}

/** Daily review: after each trading day Claude reviews every bot and writes a report; newest first. */
export function Review() {
  const [data, setData] = useState<{ reports: CoachReport[]; entries: JournalEntry[] } | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api.deskJournal().then(setData).catch(e => setError(errText(e)))
  }, [])
  const reported = new Set((data?.reports ?? []).map(r => r.day))
  const items = [
    ...(data?.reports ?? []).map(r => ({ day: r.day, report: r as CoachReport | null, entry: null as JournalEntry | null })),
    ...(data?.entries ?? []).filter(e => !reported.has(e.day)).map(e => ({ day: e.day, report: null, entry: e })),
  ].sort((a, b) => b.day.localeCompare(a.day))

  return (
    <div className="page wide review">
      <header className="brain-head">
        <p className="kicker">Daily review</p>
        <h1 className="launch-title">What the coach saw <span className="grad">each day.</span></h1>
        <p className="launch-sub">After every trading day Claude reviews each bot, grades it, works out what the trading would really cost in taxes and charges, and changes the rules when there is evidence. The bot's manager reads this report before every decision. The rules themselves are under <a href="#/bot">How the bot thinks</a>.</p>
      </header>
      {error && <p className="pad error-text" role="alert">{error}</p>}
      {data === null && !error && <p className="pad sub">Loading reviews…</p>}
      {data && items.length === 0 && (
        <section className="panel"><p className="pad">No reviews yet. After each trading day (around 16:30 IST) the coach writes its report here.</p></section>
      )}
      {items.length > 0 && (
        <div className="review-list">
          {items.map((x, i) => x.report
            ? <ReportView key={`r-${x.day}`} r={x.report} first={i === 0} all={data?.reports ?? []} />
            : <JournalCard key={`j-${x.day}`} e={x.entry as JournalEntry} first={i === 0} />)}
        </div>
      )}
    </div>
  )
}
