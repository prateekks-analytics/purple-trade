import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { ChallengeCard, ChallengeWeek, CoachResult, Health, Job, Race, Strategy, SuperAgentInfo } from '../types'
import { fmtMoney } from '../lib/tree'
import { openAiConnect } from '../lib/aiSettings'
import { errText, useJob } from './AgentBits'
import { BotBadge, POPULAR } from './Desk'
import { IconSpark } from './Icons'
import { LineChart } from './LineChart'

/** The bot being worked on: a catalog / saved bot (agent_id) or an AI-improved one not saved yet (strategy). */
interface Pick { title: string; agent_id?: string; strategy?: Strategy }

const ahead = (v: number) => `${fmtMoney(Math.abs(v))} ${v >= 0 ? 'ahead' : 'behind'}`
const botName = (title: string) => title.replace(/ \(version \d+\)$/, '')
const day = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })

export function Challenge({ health, raceId, onRace }: { health: Health | null; raceId?: string; onRace: (id?: string) => void }) {
  if (raceId) return <RaceView id={raceId} onBack={() => onRace()} />
  return <Lab health={health} onRace={onRace} />
}

function Lab({ health, onRace }: { health: Health | null; onRace: (id: string) => void }) {
  const [bots, setBots] = useState<SuperAgentInfo[]>([])
  const [bot, setBot] = useState<Pick | null>(null)
  const [symbol, setSymbol] = useState('RELIANCE')
  const [card, setCard] = useState<ChallengeCard | null>(null)
  const [busy, setBusy] = useState<'' | 'replay' | 'coach' | 'race' | 'keep'>('')
  const [error, setError] = useState('')
  const [hint, setHint] = useState('')
  const [job, setJob] = useState<Job<CoachResult> | null>(null)
  const [coach, setCoach] = useState<CoachResult | null>(null)
  const [races, setRaces] = useState<Race[] | null>(null)
  const live = useJob(job, j => {
    setBusy('')
    if (j.status === 'done' && j.result) setCoach(j.result)
    else if (j.status === 'error') setError(j.error ?? 'The AI coach stopped.')
  })

  useEffect(() => {
    api.saAgents().then(all => {
      const rules = all.filter(a => a.kind === 'rules' && !a.hidden)
      setBots(rules)
      setBot(b => b ?? (rules[0] ? { title: rules[0].title, agent_id: rules[0].id } : null))
    }).catch(e => setError(errText(e)))
    api.races().then(setRaces).catch(() => setRaces([]))
  }, [])

  const replay = async (b = bot, sym = symbol) => {
    if (!b || !sym.trim()) return
    setBusy('replay'); setError(''); setCoach(null); setJob(null)
    try { setCard(await api.replay(b.agent_id ? { agent_id: b.agent_id } : { strategy: b.strategy }, sym.trim())) }
    catch (e) { setError(errText(e)); setCard(null) }
    finally { setBusy('') }
  }

  const improve = async () => {
    if (!bot || !card) return
    if (!health?.ai.available) { openAiConnect(); return }
    setBusy('coach'); setError(''); setCoach(null)
    try { setJob((await api.coach(bot.agent_id ? { agent_id: bot.agent_id } : { strategy: bot.strategy }, symbol, hint)).job) }
    catch (e) { setError(errText(e)); setBusy('') }
  }

  const useImproved = () => {
    if (!coach?.after) return
    const name = bot?.title.replace(/ \(AI coached.*$/, '') ?? 'My bot'
    setBot({ title: `${name} (AI coached)`, strategy: { ...coach.after.strategy, name: `${name} (AI coached)`.slice(0, 120) } })
    setCard(coach.after); setCoach(null); setJob(null); setHint('')
  }

  const race = async () => {
    if (!bot) return
    setBusy('race'); setError('')
    try {
      let id = bot.agent_id
      if (!id && bot.strategy) id = (await api.keepBot(bot.strategy, bot.title)).agent_id
      const r = await api.startRace(id!, symbol.trim())
      window.dispatchEvent(new Event('purple:data'))
      onRace(r.id)
    } catch (e) { setError(errText(e)); setBusy('') }
  }

  const stock = symbol.trim().toUpperCase().replace(/\.NS$/, '')
  const step = coach || job ? 2 : card ? 2 : 1

  return (
    <div className="page wide beat">
      <header className="beat-head">
        <p className="kicker">Beat the market</p>
        <h1 className="hero-title">Can your bot stay ahead of NIFTY 50 for a week?</h1>
        <ol className="beat-steps" aria-label="Steps">
          <li className={step >= 1 ? 'on' : ''}><b>1</b> Replay past weeks</li>
          <li className={step >= 2 ? 'on' : ''}><b>2</b> Improve it with AI</li>
          <li><b>3</b> Race it live for 7 days</li>
        </ol>
      </header>

      {races && races.length > 0 && (
        <section aria-labelledby="races-h">
          <h2 id="races-h" className="section-title">Your races</h2>
          <div className="race-rail">{races.map(r => <RaceCard key={r.id} race={r} onOpen={() => onRace(r.id)} />)}</div>
        </section>
      )}

      <section className="panel beat-pick" aria-labelledby="pick-h">
        <h2 id="pick-h" className="panel-title">Pick a bot and a stock</h2>
        <div className="bot-pills" role="radiogroup" aria-label="Bot">
          {bots.map(b => (
            <button key={b.id} type="button" role="radio" aria-checked={bot?.agent_id === b.id}
              className={`bot-pill ${bot?.agent_id === b.id ? 'on' : ''}`}
              onClick={() => { const p = { title: b.title, agent_id: b.id }; setBot(p); if (card) replay(p) }}>
              <BotBadge id={b.id} size="sm" /><span>{b.title}</span>
            </button>
          ))}
          {bot?.strategy && <span className="bot-pill on coached"><IconSpark /><span>{bot.title}</span></span>}
        </div>
        <form className="beat-stock" onSubmit={e => { e.preventDefault(); replay() }}>
          <label htmlFor="beat-symbol">Stock</label>
          <input id="beat-symbol" value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} autoComplete="off" spellCheck={false} />
          <div className="chips" role="group" aria-label="Popular stocks">
            {POPULAR.map(p => <button key={p} type="button" className={`chip ${stock === p ? 'on' : ''}`} onClick={() => { setSymbol(p); if (card) replay(bot, p) }}>{p}</button>)}
          </div>
          <button className="btn glow lg" disabled={!bot || !symbol.trim() || busy !== ''}>
            {busy === 'replay' ? 'Replaying…' : card ? 'Replay again' : 'Replay the last 24 weeks'}
          </button>
        </form>
        {error && <p className="hero-error" role="alert">{error}</p>}
      </section>

      {card && <Scorecard card={card} title={bot?.title ?? ''} />}

      {card && !coach && (
        <section className="panel beat-next" aria-label="Next step">
          <div className="beat-next-col">
            <h2 className="panel-title"><IconSpark /> Improve it with the AI coach</h2>
            <p className="sub">The coach studies the losing weeks, changes the rules, replays them and tries again, three times. It keeps a change only if it wins more weeks.</p>
            <input className="beat-hint" placeholder="Optional: tell the coach what to try, e.g. cut losses faster" value={hint}
              onChange={e => setHint(e.target.value)} maxLength={400} disabled={busy === 'coach'} aria-label="Instruction for the AI coach" />
            <button className="btn primary" onClick={improve} disabled={busy !== ''}>
              {busy === 'coach' ? 'Coaching…' : health?.ai.available ? 'Improve with AI' : 'Connect an AI to improve'}
            </button>
            {live && live.status === 'running' && <CoachProgress job={live} />}
          </div>
          <div className="beat-next-col">
            <h2 className="panel-title">Race it live for 7 trading days</h2>
            <p className="sub">₹1,00,000 of paper money on {stock || 'the stock'} against the same amount in NIFTY 50, on real prices. It decides after each close and trades at the next open.</p>
            <button className="btn" onClick={race} disabled={busy !== ''}>{busy === 'race' ? 'Starting…' : 'Start the 7-day race'}</button>
          </div>
        </section>
      )}

      {coach && <CoachCard coach={coach} onUse={useImproved} onRetry={() => { setCoach(null); improve() }} onDrop={() => { setCoach(null); setJob(null) }} />}
    </div>
  )
}

function Scorecard({ card, title }: { card: ChallengeCard; title: string }) {
  const s = card.summary
  const best = useMemo(() => [...card.weeks].sort((a, b) => b.edge_rupees - a.edge_rupees)[0], [card])
  const worst = useMemo(() => [...card.weeks].sort((a, b) => a.edge_rupees - b.edge_rupees)[0], [card])
  const good = s.beat * 2 > s.weeks && s.beat > (s.cash_beat ?? 0) && (s.idle_weeks ?? 0) * 2 <= s.weeks
  return (
    <section className={`panel score ${good ? 'good' : 'bad'}`} aria-labelledby="score-h">
      <div className="score-main">
        <p className="kicker">{title} on {card.symbol.replace(/\.NS$/, '')}, last {s.weeks} weeks</p>
        <h2 id="score-h" className="score-line">Beat the market in <b className="num">{s.beat}</b> of {s.weeks} weeks</h2>
        <p className="score-verdict">{s.verdict}</p>
        <ul className="score-facts">
          <li><span>Average week vs {card.market}</span><b className={`num ${s.avg_edge >= 0 ? 'pos' : 'neg'}`}>{ahead(s.avg_edge)}</b></li>
          <li><span>Just holding cash would have won</span><b className="num">{s.cash_beat ?? 0} weeks</b></li>
          <li><span>Weeks it never bought</span><b className="num">{s.idle_weeks ?? 0}</b></li>
        </ul>
      </div>
      <div className="score-weeks">
        <WeekStrip weeks={card.weeks} />
        <p className="field-note">Each square is one week of {card.week_sessions} trading days starting with ₹1,00,000. Green: ahead of {card.market}.
          {best && worst && ` Best ${day(best.start)}: ${ahead(best.edge_rupees)}. Worst ${day(worst.start)}: ${ahead(worst.edge_rupees)}.`}</p>
        <details className="score-rules">
          <summary>The rules</summary>
          <p><b>Buy</b> when {card.describe.entry}</p>
          <p><b>Sell</b> when {card.describe.exit}</p>
        </details>
      </div>
    </section>
  )
}

function WeekStrip({ weeks }: { weeks: ChallengeWeek[] }) {
  return (
    <>
      <ol className="week-strip" aria-label="Week by week">
        {weeks.map(w => {
          const label = `${day(w.start)} to ${day(w.end)}: bot ${w.bot_pct >= 0 ? '+' : ''}${w.bot_pct}%, market ${w.market_pct >= 0 ? '+' : ''}${w.market_pct}%, ${ahead(w.edge_rupees)}${w.in_market ? '' : ' (stayed in cash)'}`
          return <li key={w.start} className={`${w.beat ? 'win' : 'loss'} ${w.in_market ? '' : 'idle'}`} title={label} aria-label={label} />
        })}
      </ol>
      <p className="week-key" aria-hidden="true"><span><i className="win" />Ahead</span><span><i />Behind</span><span><i className="idle" />Dashed: stayed in cash</span></p>
    </>
  )
}

function CoachProgress({ job }: { job: Job<CoachResult> }) {
  return (
    <ul className="coach-feed" aria-live="polite">
      {job.log.slice(-4).map((l, i) => <li key={i} className={l.kind}>{l.text}</li>)}
      <li className="sub">Try {Math.min(job.done + 1, job.total)} of {job.total}…</li>
    </ul>
  )
}

function CoachCard({ coach, onUse, onRetry, onDrop }: { coach: CoachResult; onUse: () => void; onRetry: () => void; onDrop: () => void }) {
  const a = coach.after, b = coach.before
  const last = coach.tries.find(t => a && t.beat === a.learn.beat && t.unseen_beat === a.unseen.beat) ?? coach.tries[coach.tries.length - 1]
  return (
    <section className="panel coach" aria-labelledby="coach-h">
      <h2 id="coach-h" className="panel-title"><IconSpark /> {a ? 'The AI coach found a better version' : 'No change beat the original'}</h2>
      {a ? (
        <>
          <p className="coach-change">“{last?.change}”</p>
          <div className="coach-compare">
            <div><span>Before</span><b className="num">{b.summary.beat} of {b.summary.weeks}</b><small>weeks ahead</small></div>
            <span className="coach-arrow" aria-hidden="true">→</span>
            <div className="after"><span>After</span><b className="num">{a.summary.beat} of {a.summary.weeks}</b><small>weeks ahead</small></div>
          </div>
          <p className={`coach-check ${a.unseen.beat >= b.unseen.beat ? 'pos' : 'neg'}`}>
            {a.unseen.beat > b.unseen.beat
              ? `Also better on the ${a.unseen.weeks} newest weeks the coach never saw (${b.unseen.beat} → ${a.unseen.beat}).`
              : a.unseen.beat === b.unseen.beat
                ? `No worse on the ${a.unseen.weeks} newest weeks the coach never saw (${a.unseen.beat} of ${a.unseen.weeks} either way).`
                : `Warning: worse on the ${a.unseen.weeks} newest weeks the coach never saw (${b.unseen.beat} → ${a.unseen.beat}). It may only fit the past.`}
          </p>
          <WeekStrip weeks={a.weeks} />
          <details className="score-rules"><summary>New rules</summary><p><b>Buy</b> when {a.describe.entry}</p><p><b>Sell</b> when {a.describe.exit}</p></details>
        </>
      ) : (
        <ul className="coach-feed">{coach.tries.map((t, i) => <li key={i}>{t.change} → {t.beat} of {t.weeks} weeks</li>)}</ul>
      )}
      <div className="hero-actions">
        {a && <button className="btn glow" onClick={onUse}>Use the improved bot</button>}
        <button className="btn" onClick={onRetry}>Try again</button>
        <button className="btn quiet" onClick={onDrop}>Keep the original</button>
      </div>
    </section>
  )
}

function RaceCard({ race, onOpen }: { race: Race; onOpen: () => void }) {
  const e = race.edge ?? 0
  return (
    <button className={`race-card ${race.day === 0 ? '' : e >= 0 ? 'win' : 'loss'}`} onClick={onOpen}>
      <span className="race-card-top"><BotBadge id={race.agent.id} size="sm" /><b>{botName(race.agent.title)}</b></span>
      <span className="sub">{race.symbol.replace(/\.NS$/, '')} vs NIFTY 50 · {race.finished ? 'finished' : `day ${race.day} of ${race.days}`}</span>
      <DayDots race={race} />
      <span className={`race-card-edge num ${race.day === 0 ? '' : e >= 0 ? 'pos' : 'neg'}`}>{race.day === 0 ? 'Starts next open' : ahead(e)}</span>
    </button>
  )
}

function DayDots({ race }: { race: Race }) {
  return (
    <span className="day-dots" aria-hidden="true">
      {Array.from({ length: race.days }, (_, i) => {
        const p = race.series[i + 1]
        const cls = !p ? '' : p.market == null ? 'done' : p.bot >= p.market ? 'win' : 'loss'
        return <i key={i} className={cls} />
      })}
    </span>
  )
}

function RaceView({ id, onBack }: { id: string; onBack: () => void }) {
  const [race, setRace] = useState<Race | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    const load = () => api.race(id, true).then(r => { if (alive) { setRace(r); setError('') } }).catch(e => alive && setError(errText(e)))
    load()
    const t = setInterval(() => { if (!document.hidden) load() }, 60_000)
    return () => { alive = false; clearInterval(t) }
  }, [id])

  if (error && !race) return <div className="page"><p className="page-error">{error}</p><button className="btn" onClick={onBack}>Back</button></div>
  if (!race) return <div className="page"><p className="page-loading">Loading the race…</p></div>
  const e = race.edge ?? 0
  const s = race.series.filter(p => p.market != null)
  const stock = race.symbol.replace(/\.NS$/, '')
  return (
    <div className="page wide beat">
      <button className="link-btn" onClick={onBack}>← All races</button>
      <section className={`panel race-hero ${race.day === 0 ? '' : e >= 0 ? 'good' : 'bad'}`} aria-labelledby="race-h">
        <p className="kicker">{botName(race.agent.title)} on {stock} vs NIFTY 50</p>
        <h1 id="race-h" className="score-line">{race.headline}</h1>
        <DayDots race={race} />
        <div className="race-sides">
          <div><span>Your bot</span><b className="num">{fmtMoney(race.bot_value)}</b></div>
          <div><span>NIFTY 50</span><b className="num">{race.market_value != null ? fmtMoney(race.market_value) : '—'}</b></div>
        </div>
        <p className="field-note">
          {race.live_at ? `Live, NSE prices as of ${new Date(race.live_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}. ` : 'At the last close. '}
          Both started with {fmtMoney(race.capital)} at the close on {day(race.start)}.
        </p>
      </section>

      {s.length > 1 && (
        <section className="panel" aria-label="Race chart">
          <LineChart dates={s.map(p => p.date)} height={240} format={v => fmtMoney(v)} baseline={race.capital} ariaLabel="Your bot against NIFTY 50"
            series={[{ key: 'bot', label: 'Your bot', color: 'var(--series-1)', values: s.map(p => p.bot) },
              { key: 'mkt', label: 'NIFTY 50', color: 'var(--series-2)', values: s.map(p => p.market as number), dashed: true }]} />
        </section>
      )}

      <section className="panel race-now" aria-labelledby="now-h">
        <h2 id="now-h" className="panel-title">What the bot is doing</h2>
        <p>{race.holding
          ? `Holding ${race.holding.qty} ${stock} shares, bought ${day(race.holding.since)} at ${fmtMoney(race.holding.price)}.`
          : `In cash, waiting for its buy rule.`}</p>
        {!race.finished && race.today.action && <p className="sub">After the {day(race.today.date)} close: {race.today.action === 'BUY' ? 'buys at the next open' : race.today.action === 'SELL' ? 'sells at the next open' : 'no change'}. {race.today.reason}</p>}
        {race.trades.length > 0 && (
          <ul className="race-trades">
            {race.trades.map(t => <li key={t.entry_date}>Bought {day(t.entry_date)}, sold {t.exit_date ? day(t.exit_date) : '—'}: <b className={t.pnl >= 0 ? 'pos' : 'neg'}>{t.pnl >= 0 ? '+' : '−'}{fmtMoney(Math.abs(t.pnl))}</b></li>)}
          </ul>
        )}
        <p className="field-note">Paper money only. Prices from Yahoo Finance (unofficial). Fees and slippage are included; exchange holidays are not checked.</p>
      </section>
    </div>
  )
}
