import { useEffect, useState } from 'react'
import { api } from '../api'
import { useMe } from '../lib/auth'
import { errText } from './AgentBits'
import { IconBuild, IconFlag, IconOverview, IconPaper, IconSpark, IconTest } from './Icons'

type Friend = { id: string; name: string; created_at: string; strategies: number; paper: number }

/** Owner only: the friends who signed up, with a way to remove an account. */
function Friends() {
  const [data, setData] = useState<{ users: Friend[]; max: number } | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api.authUsers().then(setData).catch(e => setError(errText(e))) }, [])
  const remove = async (f: Friend) => {
    if (!confirm(`Remove ${f.name}'s account? They are signed out and their saved bots are hidden.`)) return
    try { setData(await api.authRemove(f.id)) } catch (e) { setError(errText(e)) }
  }
  return (
    <section className="panel friends" aria-labelledby="friends-h">
      <div className="panel-head">
        <h2 id="friends-h" className="panel-title">Friends' accounts</h2>
        {data && <span className="sub">{data.users.length} of {data.max} places used</span>}
      </div>
      <p className="pad sub">Friends sign up on the sign-in page while places are left. They can watch your bot and read its reviews, and use these tools privately with their own free AI key. They cannot change your bot.</p>
      {error && <p className="pad error-text" role="alert">{error}</p>}
      {data && (data.users.length ? (
        <ul className="friend-list">
          {data.users.map(f => (
            <li key={f.id}>
              <span><b>{f.name}</b><span className="sub">joined {new Date(f.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })} · {f.strategies} bot{f.strategies === 1 ? '' : 's'} · {f.paper} paper account{f.paper === 1 ? '' : 's'}</span></span>
              <button className="btn sm quiet" onClick={() => remove(f)}>Remove</button>
            </li>
          ))}
        </ul>
      ) : <p className="pad">No friends have signed up yet.</p>)}
    </section>
  )
}

const TOOLS = [
  { hash: '#/agent', icon: <IconSpark />, title: 'Ask the agent', sub: 'Research one stock: buy, hold or sell with a stop-loss.' },
  { hash: '#/test', icon: <IconTest />, title: 'Test a rule bot', sub: 'Backtest fixed indicator rules on one stock.' },
  { hash: '#/build', icon: <IconBuild />, title: 'Build a rule bot', sub: 'Turn an idea in plain words into exact rules.' },
  { hash: '#/race', icon: <IconFlag />, title: 'Beat the market (single stock)', sub: 'Replay a rule bot week by week and race it for 7 days.' },
  { hash: '#/paper', icon: <IconPaper />, title: 'Paper accounts', sub: 'Older single-stock paper accounts.' },
  { hash: '#/classic', icon: <IconOverview />, title: 'Watchlist & classic home', sub: 'Watchlist, stock ideas and rule-bot leaderboard.' },
]

export function More() {
  const me = useMe()
  return (
    <div className="page more">
      <header>
        <p className="kicker">More tools</p>
        <h1 className="section-title">Extras</h1>
        <p className="sub">The bot on the Dashboard is the main thing. These single-stock tools are here when you want them.</p>
      </header>
      <div className="more-grid">
        {TOOLS.map(t => (
          <a key={t.hash} className="more-card glass" href={t.hash}>
            <span className="more-icon" aria-hidden="true">{t.icon}</span>
            <span><b>{t.title}</b><span className="sub">{t.sub}</span></span>
          </a>
        ))}
      </div>
      {me?.accounts && me.role === 'owner' && <Friends />}
    </div>
  )
}
