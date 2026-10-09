import { useEffect, useState } from 'react'
import { api } from './api'
import type { Health, Proposal } from './types'
import { Build } from './components/Build'
import { Paper } from './components/Paper'
import { TestBot } from './components/TestBot'
import { Workspace } from './components/Workspace'

type Route =
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
  return { page: 'test', bot: m?.[1] }
}

const SECTIONS = [
  { page: 'test', hash: '#/test', label: 'Test a bot' },
  { page: 'build', hash: '#/build', label: 'Build your own' },
  { page: 'paper', hash: '#/paper', label: 'Paper accounts' },
] as const

export default function App() {
  const [route, setRoute] = useState<Route>(parseRoute())
  const [idea, setIdea] = useState<string | undefined>()
  const [imported, setImported] = useState<Proposal | undefined>()
  const [health, setHealth] = useState<Health | null>(null)

  useEffect(() => {
    const onHash = () => { setRoute(parseRoute()); scrollTo(0, 0) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    const check = () => api.health().then(setHealth).catch(() =>
      setHealth({ ok: false, ai: { provider: '-', model: '-', available: false, detail: 'Server unreachable.' } }))
    check()
    const t = setInterval(check, 30000)
    return () => clearInterval(t)
  }, [])

  const go = (hash: string) => { if (location.hash !== hash) location.hash = hash; else setRoute(parseRoute()) }
  const open = (sid: string, initial?: string, proposal?: Proposal) => { setIdea(initial); setImported(proposal); go(`#/s/${sid}`) }
  const section = route.page === 'strategy' ? 'build' : route.page

  useEffect(() => {
    document.title = `${SECTIONS.find(s => s.page === section)?.label ?? 'Purple Trade'} – Purple Trade`
  }, [section])

  return (
    <div className="app">
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <a className="brand" href="#/test" aria-label="Purple Trade home">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="7" fill="var(--accent)" /><path d="M7 22l6-7 4 3 8-9" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          <span>Purple Trade</span>
        </a>
        <nav className="sections" aria-label="Sections">
          {SECTIONS.map(s => (
            <a key={s.page} href={s.hash} className={section === s.page ? 'on' : ''} aria-current={section === s.page ? 'page' : undefined}>{s.label}</a>
          ))}
        </nav>
        <span className="scope" title={health?.ai.detail}>NSE daily prices, research only</span>
      </header>
      <main id="main" className="main" tabIndex={-1}>
        {route.page === 'strategy' ? (
          <Workspace key={route.id} id={route.id} initialIdea={idea} initialProposal={imported} health={health}
            onBack={() => { setIdea(undefined); setImported(undefined); go('#/build') }} onRenamed={() => {}}
            onTest={vid => go(`#/test/version:${vid}`)} />
        ) : route.page === 'build' ? (
          <Build health={health} onOpen={open} onTest={bot => go(`#/test/${bot}`)} />
        ) : route.page === 'paper' ? (
          <Paper accountId={route.id} onSelect={id => go(`#/paper/${id}`)} onTest={() => go('#/test')} />
        ) : (
          <TestBot key={route.bot ?? 'none'} health={health} initialBot={route.bot}
            onPaperCreated={id => go(`#/paper/${id}`)} onBuild={() => go('#/build')} />
        )}
      </main>
      {route.page !== 'strategy' && (
        <footer className="site-foot">
          Purple Trade is a research and paper-trading tool. It places no real orders. Backtests are estimates of past behaviour, not investment advice.
        </footer>
      )}
    </div>
  )
}
