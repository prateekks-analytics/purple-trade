import { useState } from 'react'
import { api } from '../api'
import type { CoachRule } from '../types'
import { errText } from './AgentBits'
import { useReadOnly } from '../lib/auth'
import { AgentMark, PortfolioChart, dayLabel, decidedAt, pct, signed, useBacktest, useDesk, when } from './DeskBits'

/** Rules Claude wrote after reviewing past days; the chief reads them before every decision. */
function CoachNotes({ rules, onChange }: { rules: CoachRule[]; onChange: () => void }) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const readOnly = useReadOnly()
  const remove = async (r: CoachRule) => {
    if (!confirm(`Remove coach rule ${r.id}? The bot stops reading it at its next decision.`)) return
    setBusy(r.id)
    setError('')
    try { await api.coachRetire(r.id); onChange() } catch (e) { setError(errText(e)) } finally { setBusy('') }
  }
  return (
    <section className="panel" aria-labelledby="coach-h">
      <div className="panel-head"><h2 id="coach-h" className="panel-title">Coach notes</h2><span className="sub">{rules.length ? `${rules.length} rule${rules.length > 1 ? 's' : ''} the chief reads` : ''}</span></div>
      {rules.length ? (
        <ul className="coach-rules">
          {rules.map(r => {
            const s = r.score
            const f = s?.followed
            return (
              <li key={r.id}>
                <div className="coach-rule-top">
                  <span className="coach-id">{r.id}</span>
                  <p>{r.text}</p>
                  {!readOnly && <button className="btn sm quiet" onClick={() => remove(r)} disabled={busy !== ''} aria-label={`Remove rule ${r.id}`}>{busy === r.id ? 'Removing…' : 'Remove'}</button>}
                </div>
                <p className="sub">Added {dayLabel(r.added)}{r.status === 'trial' ? ' · on trial' : ''} · {r.why}</p>
                {s && f && (
                  <p className="coach-score">
                    <span className={`coach-verdict v-${s.verdict.replace(/ /g, '-')}`}>{s.verdict === 'too early' ? 'Too early to tell' : s.verdict === 'no clear effect' ? 'No clear effect' : s.verdict === 'helping' ? 'Helping' : 'Hurting'}</span>
                    {f.n ? <>Followed {f.n}× on {f.days} day{f.days === 1 ? '' : 's'}: {f.edge_pct == null ? '—' : pct(f.edge_pct)} vs NIFTY over the next 90 min{s.not_followed.n && s.not_followed.edge_pct != null ? <> (without it {pct(s.not_followed.edge_pct)})</> : null}</> : 'Not followed yet.'}
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      ) : <p className="pad">No coach notes yet. After a trading day Claude reviews every decision and writes a few rules here; the chief reads them every 30 minutes.</p>}
      {error && <p className="pad error-text" role="alert">{error}</p>}
    </section>
  )
}

/** How the bot thinks: its agents, the latest debates, the news mood, what it learned, and the replay. */
export function BotBrain() {
  const { view, reload } = useDesk()
  const { bt, error: btError } = useBacktest(40, view?.capital ?? 500000)
  const [open, setOpen] = useState(0)
  const decisions = view?.decisions ?? []
  const mood = view?.mood

  return (
    <div className="page wide brain">
      <header className="brain-head">
        <p className="kicker">How the bot thinks</p>
        <h1 className="launch-title">A company of analysts. <span className="grad">One manager decides.</span></h1>
        <p className="launch-sub">Every 30 minutes thirteen analysts, from price action to fundamentals, news, social chatter and risk-takers, each propose a portfolio. The AI manager hears them all and builds one portfolio, often combining several ideas. In a market uptrend the momentum core takes over.</p>
      </header>

      {[...new Set((view?.agents ?? []).map(a => a.team ?? 'Analysts'))].map(team => (
      <section key={team} className="team" aria-label={team}>
        <h2 className="team-title">{team}</h2>
        <div className="agent-grid">
        {(view?.agents ?? []).filter(a => (a.team ?? 'Analysts') === team).map(a => {
          const pick = Object.keys(a.proposal ?? {})
          return (
            <article key={a.id} className="agent-card glass">
              <div className="agent-top"><AgentMark id={a.id} size="lg" /><h2>{a.name}</h2></div>
              <p className="sub">{a.style}</p>
              <div className="agent-stats">
                <span><small>Last 2 days</small><b className={`num ${(a.record_pct ?? 0) >= 0 ? 'pos' : 'neg'}`}>{a.record_pct == null ? '—' : pct(a.record_pct)}</b></span>
                <span><small>Led decisions</small><b className="num">{a.wins ?? 0}</b></span>
              </div>
              <p className="agent-pick">{view?.bot ? (pick.length ? <>Wants <b>{pick.join(', ')}</b></> : 'Wants cash') : ''}</p>
            </article>
          )
        })}
        </div>
      </section>
      ))}

      <div className="dash-grid">
        <section className="panel" aria-labelledby="deb-h">
          <div className="panel-head"><h2 id="deb-h" className="panel-title">Debates</h2><span className="sub">{decisions.length ? `${decisions.length} recent` : ''}</span></div>
          {decisions.length ? (
            <ol className="debate-list">
              {decisions.slice(0, 12).map((d, i) => (
                <li key={d.time} className={open === i ? 'open' : ''}>
                  <button className="debate-row" onClick={() => setOpen(open === i ? -1 : i)} aria-expanded={open === i}>
                    <AgentMark id={d.winner} size="sm" /><b>{d.winner_name}</b><span className="sub">{decidedAt(d.time)}</span>
                    <span className="debate-tg">{Object.keys(d.targets).join(', ') || 'cash'}</span>
                  </button>
                  {open === i && (
                    <div className="debate-body">
                      <p>{d.reason}</p>
                      {d.debate.length > 0 && (
                        <ul className="cases">
                          {d.debate.map(c => <li key={c.agent} className={c.agent === d.winner ? 'won' : ''}><AgentMark id={c.agent} size="sm" /><span><b>{c.name}:</b> {c.case}</span></li>)}
                        </ul>
                      )}
                      <p className="field-note">{d.by === 'record' ? 'Decided by track record (no AI answered).' : `Judged by ${d.by}.`}{d.uses && d.uses.length > 1 ? ` Used ideas from ${d.uses.join(', ')}.` : ''}{d.rules_used?.length ? ` Followed coach ${d.rules_used.length > 1 ? 'rules' : 'rule'} ${d.rules_used.join(', ')}.` : ''}</p>
                    </div>
                  )}
                </li>
              ))}
            </ol>
          ) : <p className="pad">{view?.bot ? 'The first debate is running.' : 'Start the bot on the Dashboard to see its debates here.'}</p>}
        </section>

        <div className="stack">
          <section className="panel" aria-labelledby="mood-h">
            <div className="panel-head"><h2 id="mood-h" className="panel-title">News & social mood</h2>{mood && <span className="sub">{decidedAt(mood.time)}</span>}</div>
            {mood ? (
              <ul className="mood-list">
                {Object.entries(mood.scores).sort((a, b) => b[1].score - a[1].score).map(([s, m]) => (
                  <li key={s} title={m.why}>
                    <b>{s}</b>
                    <span className="mood-bar" aria-hidden="true"><i className={m.score >= 0 ? 'up' : 'down'} style={{ width: `${Math.abs(m.score) * 50}%`, [m.score >= 0 ? 'left' : 'right']: '50%' }} /></span>
                    <span className="mood-why">{m.why}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="pad">Read every two hours from Google News and Reddit while the bot runs.</p>}
          </section>
          <section className="panel" aria-labelledby="learn-h">
            <div className="panel-head"><h2 id="learn-h" className="panel-title">What it learned</h2></div>
            {view?.lessons?.length
              ? <ul className="lessons">{view.lessons.map((l, i) => <li key={i}>{l}</li>)}</ul>
              : <p className="pad">After each trading day the AI reviews the results and writes lessons the chief uses the next day.</p>}
          </section>
          <CoachNotes rules={view?.coach?.rules ?? []} onChange={reload} />
        </div>
      </div>

      <section className="panel" aria-labelledby="bt-h">
        <div className="panel-head">
          <div>
            <h2 id="bt-h" className="panel-title">Backtest: the last 40 trading days</h2>
            {bt && <p className="sub">{when(bt.from)} to {when(bt.to)} · {bt.trades} trades · {bt.note}</p>}
          </div>
        </div>
        {bt ? (
          <div className="bt-body">
            <div className="bt-stats">
              <span><small>Bot</small><b className={`num ${bt.return_pct >= 0 ? 'pos' : 'neg'}`}>{pct(bt.return_pct)}</b></span>
              <span><small>NIFTY 50</small><b className={`num ${bt.market_pct >= 0 ? 'pos' : 'neg'}`}>{pct(bt.market_pct)}</b></span>
              <span><small>Difference on {bt.capital >= 100000 ? `₹${(bt.capital / 100000).toLocaleString('en-IN')} lakh` : 'start'}</small><b className={`num ${bt.edge >= 0 ? 'pos' : 'neg'}`}>{signed(bt.edge)}</b></span>
              <span><small>7-day windows ahead</small><b className="num">{bt.weeks_beat} of {bt.weeks.length}</b></span>
            </div>
            <PortfolioChart series={bt.series} height={240} label="Bot (replay)" />
            <div className="bt-agents">
              {bt.agents.map(a => <span key={a.id}><AgentMark id={a.id} size="sm" />{a.name}<b className={`num ${a.return_pct >= 0 ? 'pos' : 'neg'}`}>{pct(a.return_pct)}</b><small>picked {a.picked}×</small></span>)}
            </div>
          </div>
        ) : <p className="pad">{btError || 'Replaying the last 40 trading days…'}</p>}
      </section>
    </div>
  )
}
