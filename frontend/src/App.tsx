import { useEffect, useState } from 'react'
import { api } from './api'
import type { Health, Proposal } from './types'
import { Agent } from './components/Agent'
import { AiConnect } from './components/AiConnect'
import { Build } from './components/Build'
import { BotBrain } from './components/BotBrain'
import { Challenge } from './components/Challenge'
import { Dashboard } from './components/Dashboard'
import { Review } from './components/Review'
import { SignIn } from './components/SignIn'
import { AuthContext, type Me } from './lib/auth'
import { More } from './components/More'
import { IconBolt, IconLedger, IconMoon, IconOverview, IconSpark, IconSun, IconUser, Logo } from './components/Icons'
import { Overview } from './components/Overview'
import { Palette } from './components/Palette'
import { useQuotes } from './lib/quotes'
import { Paper } from './components/Paper'
import { TestBot } from './components/TestBot'
import { Workspace } from './components/Workspace'
import { getAi, onAiChange } from './lib/aiSettings'
import { nseStatus, totals, usePortfolio } from './lib/portfolio'

type Route =
  | { page: 'dashboard' }
  | { page: 'bot' }
  | { page: 'review' }
  | { page: 'more' }
  | { page: 'overview' }
  | { page: 'race'; id?: string }
  | { page: 'agent'; symbol?: string }
  | { page: 'test'; bot?: string }
  | { page: 'build' }
  | { page: 'strategy'; id: string }
  | { page: 'paper'; id?: string }

function parseRoute(): Route {
  const h = location.hash
  let m = h.match(/^#\/s\/([\w-]+)/)
  if (m) return { page: 'strategy', id: m[1] }
  if (h.startsWith('#/build')) return { page: 'build' }
  if (h.startsWith('#/bot')) return { page: 'bot' }
  if (h.startsWith('#/review')) return { page: 'review' }
  if (h.startsWith('#/more')) return { page: 'more' }
  if (h.startsWith('#/classic')) return { page: 'overview' }
  m = h.match(/^#\/race(?:\/([\w-]+))?/)
  if (m) return { page: 'race', id: m[1] }
  m = h.match(/^#\/agent(?:\/([\w&.^-]+))?/)
  if (m) return { page: 'agent', symbol: m[1] }
  if (/^#\/test\/(purple-agent|tradingagents|news-pulse|crew-nse)/.test(h)) return { page: 'agent' }
  m = h.match(/^#\/paper(?:\/([\w-]+))?/)
  if (m) return { page: 'paper', id: m[1] }
  m = h.match(/^#\/test(?:\/([\w:-]+))?/)
  if (m) return { page: 'test', bot: m[1] }
  return { page: 'dashboard' }
}

const INDICES = [{ sym: '^NSEI', label: 'NIFTY 50' }, { sym: '^BSESN', label: 'SENSEX' }]

const IconMore = () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><rect x="4" y="4" width="6" height="6" rx="1.5" /><rect x="14" y="4" width="6" height="6" rx="1.5" /><rect x="4" y="14" width="6" height="6" rx="1.5" /><rect x="14" y="14" width="6" height="6" rx="1.5" /></svg>

const SECTIONS = [
  { page: 'dashboard', hash: '#/', label: 'Dashboard', short: 'Dashboard', icon: <IconOverview />, group: '' },
  { page: 'bot', hash: '#/bot', label: 'How the bot thinks', short: 'Bot', icon: <IconBolt />, group: '' },
  { page: 'review', hash: '#/review', label: 'Daily review', short: 'Review', icon: <IconLedger />, group: '' },
  { page: 'more', hash: '#/more', label: 'More tools', short: 'More', icon: <IconMore />, group: '' },
] as const

function initialTheme(): 'light' | 'dark' {
  try { const t = localStorage.getItem('purple.theme'); if (t === 'light' || t === 'dark') return t } catch { /* ignore */ }
  return 'light'
}

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  useEffect(() => {
    const load = () => api.authMe().then(setMe).catch(() =>
      setMe({ accounts: false, signed_in: true, name: null, role: 'owner', seats_left: 0 }))
    load()
    window.addEventListener('purple:signin', load)
    return () => window.removeEventListener('purple:signin', load)
  }, [])
  if (!me) return <p className="page-loading">Loading…</p>
  if (me.accounts && !me.signed_in) return <SignIn me={me} onDone={setMe} />
  return <AuthContext.Provider value={me}><Shell me={me} onSignOut={() => api.authLogout().then(setMe)} /></AuthContext.Provider>
}

function Shell({ me, onSignOut }: { me: Me; onSignOut: () => void }) {
  const [route, setRoute] = useState<Route>(parseRoute())
  const [idea, setIdea] = useState<string | undefined>()
  const [imported, setImported] = useState<Proposal | undefined>()
  const [health, setHealth] = useState<Health | null>(null)
  const [aiOpen, setAiOpen] = useState(false)
  const [aiVersion, setAiVersion] = useState(0)
  const [theme, setTheme] = useState(initialTheme)
  const [, setTick] = useState(0)
  const [palette, setPalette] = useState(false)
  const idx = useQuotes(INDICES.map(i => i.sym))
  const market = nseStatus()

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('purple.theme', theme) } catch { /* ignore */ }
  }, [theme])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target as HTMLElement)?.tagName ?? '')
      if ((e.key === 'k' && (e.ctrlKey || e.metaKey)) || (e.key === '/' && !typing)) { e.preventDefault(); setPalette(true) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    const onHash = () => { setRoute(parseRoute()); scrollTo(0, 0) }
    const onData = () => setTick(t => t + 1)
    window.addEventListener('hashchange', onHash)
    window.addEventListener('purple:data', onData)
    return () => { window.removeEventListener('hashchange', onHash); window.removeEventListener('purple:data', onData) }
  }, [])

  useEffect(() => {
    let first = true
    const check = () => api.health().then(h => {
      setHealth(h)
      // First visit with no AI available: ask for a key once (rule bots and backtests work without one).
      if (first && !h.ai.available && !getAi()) {
        try { if (!sessionStorage.getItem('purple.ai.asked')) { sessionStorage.setItem('purple.ai.asked', '1'); setAiOpen(true) } } catch { setAiOpen(true) }
      }
      first = false
    }).catch(() =>
      setHealth({ ok: false, ai: { provider: '-', model: '-', available: false, detail: 'Server unreachable.' } }))
    check()
    const t = setInterval(check, 30000)
    const off = onAiChange(() => { check(); setAiVersion(v => v + 1) })
    const show = () => setAiOpen(true)
    window.addEventListener('purple:connect-ai', show)
    return () => { clearInterval(t); off(); window.removeEventListener('purple:connect-ai', show) }
  }, [])

  const go = (hash: string) => { if (location.hash !== hash) location.hash = hash; else setRoute(parseRoute()) }
  const open = (sid: string, initial?: string, proposal?: Proposal) => { setIdea(initial); setImported(proposal); go(`#/s/${sid}`) }
  const section = route.page === 'dashboard' || route.page === 'bot' || route.page === 'review' ? route.page : 'more'
  const ai = getAi()

  useEffect(() => {
    document.title = `${SECTIONS.find(s => s.page === section)?.label ?? 'Purple Trade'} – Purple Trade`
  }, [section])

  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <aside className="sidebar" aria-label="Main navigation">
        <a className="brand" href="#/" aria-label="Purple Trade home"><Logo /><span>Purple Trade</span></a>
        <nav className="side-nav">
          {SECTIONS.map(s => [
            s.group && <span key={`g-${s.page}`} className="side-group">{s.group}</span>,
            <a key={s.page} href={s.hash} title={s.label} className={`${section === s.page ? 'on' : ''}`} aria-current={section === s.page ? 'page' : undefined}>
              {s.icon}<span>{s.label}</span>
            </a>,
          ])}
        </nav>
        <div className="side-foot">
          <button className={`side-ai ${health?.ai.available ? 'on' : 'off'}`} onClick={() => setAiOpen(true)} title={health?.ai.detail}>
            <i className="side-ai-dot" aria-hidden="true" />
            <span>{health?.ai.available
              ? <>AI connected<small>{ai ? ai.model : health.ai.model}</small></>
              : <>Connect an AI<small>Free with Google Gemini</small></>}</span>
          </button>
          <button className="side-theme" onClick={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>
            {theme === 'dark' ? <IconSun /> : <IconMoon />}<span>{theme === 'dark' ? 'Light theme' : 'Dark theme'}</span>
          </button>
          {me.accounts && (
            <button className="side-theme" onClick={onSignOut} title={`Signed in as ${me.name}`}>
              <IconUser /><span>{me.role === 'owner' ? 'Owner' : me.name} · Sign out</span>
            </button>
          )}
          <p className="side-note">Virtual money only. No real orders.</p>
        </div>
      </aside>

      <nav className="tabbar" aria-label="Sections">
        {SECTIONS.map(s => (
          <a key={s.page} href={s.hash} className={`${section === s.page ? 'on' : ''}`} aria-current={section === s.page ? 'page' : undefined}>
            {s.icon}<span>{s.short}</span>
          </a>
        ))}
      </nav>

      <div className="main-col">
        <header className="bar">
          <a className="bar-brand" href="#/" aria-label="Purple Trade home"><Logo size={26} /><span>Purple Trade</span></a>
          <div className="indices" aria-label="Market indices">
            {INDICES.map(i => {
              const q = idx[i.sym]
              const c = q?.change_pct
              return (
                <span key={i.sym} className="index">
                  <span className="index-name">{i.label}</span>
                  <b className="num">{q ? q.price.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}</b>
                  {c != null && <span className={`num ${c > 0 ? 'pos' : c < 0 ? 'neg' : ''}`}>{c > 0 ? '+' : ''}{c.toFixed(2)}%</span>}
                </span>
              )
            })}
          </div>
          <button className="search-btn" onClick={() => setPalette(true)} aria-label="Search stocks, bots and pages (Ctrl+K)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
            <span>Search eg: infy, golden cross</span><kbd>Ctrl K</kbd>
          </button>
          <span className={`market ${market.open ? 'open' : 'closed'}`} title="Regular NSE session, Monday to Friday 09:15–15:30 IST. Holidays not checked.">
            <i aria-hidden /><span>{market.label}<span className="market-time">, {market.time}</span></span>
          </span>
          <button className={`bar-ai ${health?.ai.available ? 'on' : 'off'}`} onClick={() => setAiOpen(true)} aria-label={health?.ai.available ? 'AI connected. Change AI' : 'Connect an AI'}>
            <IconSpark />
          </button>
        </header>
        <Palette open={palette} onClose={() => setPalette(false)} onTheme={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))} onConnectAi={() => setAiOpen(true)} />
        <AiConnect key={aiOpen ? 'open' : 'closed'} open={aiOpen} hosted={Boolean(health?.hosted)} onClose={() => setAiOpen(false)} />
        {me.role === 'member' && (
          <p className="hosted-note">You are viewing the owner's bot: you can watch it and read its reviews, but not change it. Your own bots and paper accounts are under More, private to you. For AI features, connect your own free AI key.</p>
        )}
        {health?.hosted && (
          <p className="hosted-note">Shared online demo: strategies and paper accounts saved here are visible to other visitors and are wiped when the server restarts. For private use, download the Windows app.</p>
        )}
        <main id="main" className="main" tabIndex={-1}>
          {route.page === 'dashboard' ? (
            <Dashboard />
          ) : route.page === 'bot' ? (
            <BotBrain />
          ) : route.page === 'review' ? (
            <Review />
          ) : route.page === 'more' ? (
            <More />
          ) : route.page === 'strategy' ? (
            <Workspace key={`${route.id}-${aiVersion}`} id={route.id} initialIdea={idea} initialProposal={imported} health={health}
              onBack={() => { setIdea(undefined); setImported(undefined); go('#/build') }} onRenamed={() => {}}
              onTest={vid => go(`#/test/version:${vid}`)} />
          ) : route.page === 'race' ? (
            <Challenge key={aiVersion} health={health} raceId={route.id} onRace={id => go(id ? `#/race/${id}` : '#/race')} />
          ) : route.page === 'agent' ? (
            <Agent key={`${aiVersion}-${route.symbol ?? ''}`} health={health} initialSymbol={route.symbol} onPaperCreated={id => go(`#/paper/${id}`)} />
          ) : route.page === 'build' ? (
            <Build key={aiVersion} health={health} onOpen={open} onTest={bot => go(`#/test/${bot}`)} />
          ) : route.page === 'paper' ? (
            <Paper accountId={route.id} onSelect={id => go(`#/paper/${id}`)} />
          ) : route.page === 'test' ? (
            <TestBot key={`${route.bot ?? 'none'}-${aiVersion}`} initialBot={route.bot}
              onPaperCreated={id => go(`#/paper/${id}`)} onBuild={() => go('#/build')} />
          ) : (
            <Classic onAsk={sym => go(`#/agent/${sym}`)} aiReady={Boolean(health?.ai.available)} />
          )}
        </main>
      </div>
    </div>
  )
}

/** The earlier home page (watchlist, ask-the-agent hero, rule-bot leaderboard), now under More. */
function Classic(props: { onAsk: (symbol: string) => void; aiReady: boolean }) {
  const portfolio = usePortfolio('classic')
  return <Overview portfolio={portfolio} total={totals(portfolio)} {...props} />
}
