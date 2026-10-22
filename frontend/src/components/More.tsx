import { IconBuild, IconFlag, IconOverview, IconPaper, IconSpark, IconTest } from './Icons'

const TOOLS = [
  { hash: '#/agent', icon: <IconSpark />, title: 'Ask the agent', sub: 'Research one stock: buy, hold or sell with a stop-loss.' },
  { hash: '#/test', icon: <IconTest />, title: 'Test a rule bot', sub: 'Backtest fixed indicator rules on one stock.' },
  { hash: '#/build', icon: <IconBuild />, title: 'Build a rule bot', sub: 'Turn an idea in plain words into exact rules.' },
  { hash: '#/race', icon: <IconFlag />, title: 'Beat the market (single stock)', sub: 'Replay a rule bot week by week and race it for 7 days.' },
  { hash: '#/paper', icon: <IconPaper />, title: 'Paper accounts', sub: 'Older single-stock paper accounts.' },
  { hash: '#/classic', icon: <IconOverview />, title: 'Watchlist & classic home', sub: 'Watchlist, stock ideas and rule-bot leaderboard.' },
]

export function More() {
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
    </div>
  )
}
