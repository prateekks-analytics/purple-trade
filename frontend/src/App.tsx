import { useEffect, useState } from 'react'
import { api } from './api'
import type { Health, Proposal } from './types'
import { AiConnect } from './components/AiConnect'
import { Build } from './components/Build'
import { IconBuild, IconMoon, IconOverview, IconPaper, IconSpark, IconSun, IconTest, Logo } from './components/Icons'
import { Overview } from './components/Overview'
import { Paper } from './components/Paper'
import { TestBot } from './components/TestBot'
import { Workspace } from './components/Workspace'
import { getAi, onAiChange } from './lib/aiSettings'
import { nseStatus, totals, usePortfolio } from './lib/portfolio'
import { fmtMoney, fmtPct } from './lib/tree'

type Route =
  | { page: 'overview' }
  | { page: 'test'; bot?: string }
  | { page: 'build' }
  | { page: 'strategy'; id: string }
  | { page: 'paper'; id?: string }

function parseRoute(): Route {
  const h = location.hash
  let m = h.match(/^#\/s\/([\w-]+)/)
  if (m) return { page: 'strategy', id: m[1] }
  if (h.startsWith('#/build')) return { page: 'build' }
  m = h.match(/^#\/paper(?:\/([\w-]+))?/)
  if (m) return { page: 'paper', id: m[1] }
  m = h.match(/^#\/test(?:\/([\w:-]+))?/)
  if (m) return { page: 'test', bot: m[1] }
  return { page: 'overview' }
}

const SECTIONS = [
  { page: 'overview', hash: '#/', label: 'Overview', icon: <IconOverview /> },
  { page: 'test', hash: '#/test', label: 'Test a bot', icon: <IconTest /> },
  { page: 'build', hash: '#/build', label: 'Build your own', icon: <IconBuild /> },
  { page: 'paper', hash: '#/paper', label: 'Paper accounts', icon: <IconPaper /> },
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
  const portfolio = usePortfolio(`${route.page}-${tick}`)
  const sum = totals(portfolio)
  const market = nseStatus()

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('purple.theme', theme) } catch { /* ignore */ }
  }, [theme])

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
        <a className="brand" href="#/" aria-label="Purple Trade overview"><Logo /><span>Purple Trade</span></a>
        <nav className="side-nav">
          {SECTIONS.map(s => (
            <a key={s.page} href={s.hash} className={section === s.page ? 'on' : ''} aria-current={section === s.page ? 'page' : undefined}>
              {s.icon}<span>{s.label}</span>
            </a>
          ))}
        </nav>
        <div className="side-foot">
          <button className={`side-ai ${health?.ai.available ? 'on' : 'off'}`} onClick={() => setAiOpen(true)} title={health?.ai.detail}>
            <IconSpark />
            <span>{health?.ai.available
              ? <>AI connected<small>{ai ? `${ai.provider} · ${ai.model}` : `${health.ai.provider} · ${health.ai.model}`}</small></>
              : <>Connect an AI<small>For ideas and AI agents</small></>}</span>
          </button>
          <button className="side-theme" onClick={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>
            {theme === 'dark' ? <IconSun /> : <IconMoon />}<span>{theme === 'dark' ? 'Light theme' : 'Dark theme'}</span>
          </button>
          <p className="side-note">Research and paper trading only. No real orders.</p>
        </div>
      </aside>

      <div className="main-col">
        <header className="bar">
          <div className="bar-stat">
            <span className="bar-label">Paper equity</span>
            <b className="num">{sum ? fmtMoney(sum.value) : '—'}</b>
          </div>
          <div className="bar-stat">
            <span className="bar-label">Total P&amp;L</span>
            <b className={`num ${sum && sum.change > 0 ? 'pos' : sum && sum.change < 0 ? 'neg' : ''}`}>
              {sum ? `${sum.change >= 0 ? '+' : '−'}${fmtMoney(Math.abs(sum.change))} (${fmtPct(sum.changePct)})` : '—'}</b>
          </div>
          <div className="bar-stat">
            <span className="bar-label">Accounts</span>
            <b className="num">{portfolio ? portfolio.length : '—'}</b>
          </div>
          <span className={`market ${market.open ? 'open' : 'closed'}`} title="Regular NSE session, Monday to Friday 09:15–15:30 IST. Holidays not checked.">
            <i aria-hidden />{market.label}, {market.time}
          </span>
        </header>
        <AiConnect key={aiOpen ? 'open' : 'closed'} open={aiOpen} hosted={Boolean(health?.hosted)} onClose={() => setAiOpen(false)} />
        {health?.hosted && (
          <p className="hosted-note">Shared online demo: strategies and paper accounts saved here are visible to other visitors and are wiped when the server restarts. For private use, download the Windows app.</p>
        )}
        <main id="main" className="main" tabIndex={-1}>
          {route.page === 'strategy' ? (
            <Workspace key={`${route.id}-${aiVersion}`} id={route.id} initialIdea={idea} initialProposal={imported} health={health}
              onBack={() => { setIdea(undefined); setImported(undefined); go('#/build') }} onRenamed={() => {}}
              onTest={vid => go(`#/test/version:${vid}`)} />
          ) : route.page === 'build' ? (
            <Build key={aiVersion} health={health} onOpen={open} onTest={bot => go(`#/test/${bot}`)} />
          ) : route.page === 'paper' ? (
            <Paper accountId={route.id} onSelect={id => go(`#/paper/${id}`)} onTest={() => go('#/test')} />
          ) : route.page === 'test' ? (
            <TestBot key={`${route.bot ?? 'none'}-${aiVersion}`} initialBot={route.bot}
              onPaperCreated={id => go(`#/paper/${id}`)} onBuild={() => go('#/build')} />
          ) : (
            <Overview portfolio={portfolio} total={sum} />
          )}
        </main>
      </div>
    </div>
  )
}
