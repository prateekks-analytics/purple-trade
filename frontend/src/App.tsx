import { useEffect, useState } from 'react'
import { api } from './api'
import type { Health, Proposal } from './types'
import { Agent } from './components/Agent'
import { AiConnect } from './components/AiConnect'
import { Build } from './components/Build'
import { Challenge } from './components/Challenge'
import { IconBuild, IconFlag, IconMoon, IconOverview, IconPaper, IconSpark, IconSun, IconTest, Logo } from './components/Icons'
import { Overview } from './components/Overview'
import { Palette } from './components/Palette'
import { useQuotes } from './lib/quotes'
import { Paper } from './components/Paper'
import { TestBot } from './components/TestBot'
import { Workspace } from './components/Workspace'
import { getAi, onAiChange } from './lib/aiSettings'
import { nseStatus, totals, usePortfolio } from './lib/portfolio'
import { fmtMoney, fmtPct } from './lib/tree'

type Route =
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
  m = h.match(/^#\/race(?:\/([\w-]+))?/)
  if (m) return { page: 'race', id: m[1] }
  m = h.match(/^#\/agent(?:\/([\w&.^-]+))?/)
  if (m) return { page: 'agent', symbol: m[1] }
  if (/^#\/test\/(purple-agent|tradingagents|news-pulse|crew-nse)/.test(h)) return { page: 'agent' }
  m = h.match(/^#\/paper(?:\/([\w-]+))?/)
  if (m) return { page: 'paper', id: m[1] }
  m = h.match(/^#\/test(?:\/([\w:-]+))?/)
  if (m) return { page: 'test', bot: m[1] }
  return { page: 'overview' }
}

const INDICES = [{ sym: '^NSEI', label: 'NIFTY 50' }, { sym: '^BSESN', label: 'SENSEX' }]

const SECTIONS = [
  { page: 'overview', hash: '#/', label: 'Home', short: 'Home', icon: <IconOverview />, group: '' },
  { page: 'race', hash: '#/race', label: 'Beat the market', short: 'Race', icon: <IconFlag />, group: 'Main goal' },
  { page: 'agent', hash: '#/agent', label: 'Ask the agent', short: 'Agent', icon: <IconSpark />, group: 'AI agent' },
  { page: 'test', hash: '#/test', label: 'Test a bot', short: 'Bots', icon: <IconTest />, group: 'Rule bots' },
  { page: 'build', hash: '#/build', label: 'Build a bot', short: 'Build', icon: <IconBuild />, group: '' },
  { page: 'paper', hash: '#/paper', label: 'Paper accounts', short: 'Paper', icon: <IconPaper />, group: 'Practice' },
] as const

function initialTheme(): 'light' | 'dark' {
  try { const t = localStorage.getItem('purple.theme'); if (t === 'light' || t === 'dark') return t } catch { /* ignore */ }
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseRoute())
  const [idea, setIdea] = useState<string | undefined>()
  const [imported, setImported] = useState<Proposal | undefined>()
  const [health, setHealth] = useState<Health | null>(null)
  const [aiOpen, setAiOpen] = useState(false)
  const [aiVersion, setAiVersion] = useState(0)
  const [theme, setTheme] = useState(initialTheme)
  const [tick, setTick] = useState(0)
  const [palette, setPalette] = useState(false)
  const idx = useQuotes(INDICES.map(i => i.sym))
  const portfolio = usePortfolio(`${route.page}-${tick}`)
  const sum = totals(portfolio)
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
  const section = route.page === 'strategy' ? 'build' : route.page
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
            <a key={s.page} href={s.hash} title={s.label} className={`${section === s.page ? 'on' : ''} ${s.page === 'agent' ? 'hot' : ''}`} aria-current={section === s.page ? 'page' : undefined}>
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
          <p className="side-note">Virtual money only. No real orders.</p>
        </div>
      </aside>

      <nav className="tabbar" aria-label="Sections">
        {SECTIONS.map(s => (
          <a key={s.page} href={s.hash} className={`${section === s.page ? 'on' : ''} ${s.page === 'agent' ? 'hot' : ''}`} aria-current={section === s.page ? 'page' : undefined}>
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
          <a className="wallet" href="#/paper" title="All paper accounts together">
            <span className="wallet-label">Paper money</span>
            <b className="num">{sum ? fmtMoney(sum.value) : '—'}</b>
            <span className={`wallet-chg num ${sum && sum.change > 0 ? 'pos' : sum && sum.change < 0 ? 'neg' : ''}`}>
              {sum ? `${sum.change >= 0 ? '+' : '−'}${fmtMoney(Math.abs(sum.change))} (${fmtPct(sum.changePct)})` : ''}</span>
            <span className="wallet-count">{portfolio ? `${portfolio.length} account${portfolio.length === 1 ? '' : 's'}` : ''}</span>
          </a>
          <span className={`market ${market.open ? 'open' : 'closed'}`} title="Regular NSE session, Monday to Friday 09:15–15:30 IST. Holidays not checked.">
            <i aria-hidden /><span>{market.label}<span className="market-time">, {market.time}</span></span>
          </span>
          <button className={`bar-ai ${health?.ai.available ? 'on' : 'off'}`} onClick={() => setAiOpen(true)} aria-label={health?.ai.available ? 'AI connected. Change AI' : 'Connect an AI'}>
            <IconSpark />
          </button>
        </header>
        <Palette open={palette} onClose={() => setPalette(false)} onTheme={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))} onConnectAi={() => setAiOpen(true)} />
        <AiConnect key={aiOpen ? 'open' : 'closed'} open={aiOpen} hosted={Boolean(health?.hosted)} onClose={() => setAiOpen(false)} />
        {health?.hosted && (
          <p className="hosted-note">Shared online demo: strategies and paper accounts saved here are visible to other visitors and are wiped when the server restarts. For private use, download the Windows app.</p>
        )}
        <main id="main" className="main" tabIndex={-1}>
          {route.page === 'strategy' ? (
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
            <Overview portfolio={portfolio} total={sum} onAsk={sym => go(`#/agent/${sym}`)} aiReady={Boolean(health?.ai.available)} />
          )}
        </main>
      </div>
    </div>
  )
}
