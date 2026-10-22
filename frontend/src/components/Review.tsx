import { useEffect, useState } from 'react'
import { api } from '../api'
import type { JournalEntry, JournalItem } from '../types'
import { errText } from './AgentBits'

/** Journal labels shown up front, in this order, with friendlier names; anything else goes under "More detail". */
const MAIN: [string, string, string][] = [
  ['good calls', 'What went well', 'good'],
  ['mistakes', 'What went wrong', 'bad'],
  ['playbook', 'Rule changes', 'rule'],
  ['watch next', 'Watch tomorrow', 'watch'],
]

const longDay = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })

function ReviewCard({ e, first }: { e: JournalEntry; first: boolean }) {
  const find = (key: string) => e.items.find(i => i.label.toLowerCase() === key)
  const result = find('result')
  const rest = e.items.filter(i => i !== result && !MAIN.some(([k]) => k === i.label.toLowerCase()))
  const extra: JournalItem[] = e.summary && result ? [result, ...rest] : rest
  return (
    <article className="panel review-card" aria-labelledby={`rv-${e.day}`}>
      <header className="review-head">
        <h2 id={`rv-${e.day}`} className="panel-title">{longDay(e.day)}</h2>
        {first && <span className="badge ok">Latest</span>}
      </header>
      <p className="review-summary">{e.summary ?? result?.text ?? 'The coach wrote no summary for this day.'}</p>
      <dl className="review-items">
        {MAIN.map(([key, label, tone]) => {
          const it = find(key)
          return it ? (
            <div key={key} className={`review-item ${tone}`}>
              <dt>{label}</dt>
              <dd>{it.text}</dd>
            </div>
          ) : null
        })}
      </dl>
      {extra.length > 0 && (
        <details className="review-more">
          <summary>More detail</summary>
          <dl>
            {extra.map(i => <div key={i.label}><dt>{i.label}</dt><dd>{i.text}</dd></div>)}
          </dl>
        </details>
      )}
    </article>
  )
}

/** Daily review: after each trading day Claude reviews the bot and writes a short note; newest first. */
export function Review() {
  const [entries, setEntries] = useState<JournalEntry[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api.deskJournal().then(r => setEntries(r.entries)).catch(e => setError(errText(e)))
  }, [])

  return (
    <div className="page wide review">
      <header className="brain-head">
        <p className="kicker">Daily review</p>
        <h1 className="launch-title">What the coach saw <span className="grad">each day.</span></h1>
        <p className="launch-sub">After every trading day Claude reads each decision the bot made, notes what went well and what went wrong, and changes the bot's rules when there is evidence. The rules themselves are under <a href="#/bot">How the bot thinks</a>.</p>
      </header>
      {error && <p className="pad error-text" role="alert">{error}</p>}
      {entries === null && !error && <p className="pad sub">Loading reviews…</p>}
      {entries?.length === 0 && (
        <section className="panel"><p className="pad">No reviews yet. After each trading day (around 16:30 IST) the coach writes a short note here.</p></section>
      )}
      {entries && entries.length > 0 && (
        <div className="review-list">
          {entries.map((e, i) => <ReviewCard key={`${e.day}-${e.date}`} e={e} first={i === 0} />)}
        </div>
      )}
    </div>
  )
}
