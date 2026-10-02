import { useEffect, useState } from 'react'
import { api } from './api'
import type { Health, Proposal } from './types'
import { Home } from './components/Home'
import { SuperAgent } from './components/SuperAgent'
import { Warp } from './components/Warp'
import { Workspace } from './components/Workspace'

type Route = { page: 'home' } | { page: 'strategy'; id: string } | { page: 'super'; agent?: string }

function parseRoute(): Route {
  const s = location.hash.match(/^#\/s\/([\w-]+)/)
  if (s) return { page: 'strategy', id: s[1] }
  const a = location.hash.match(/^#\/super(?:\/([\w:-]+))?/)
  if (a) return { page: 'super', agent: a[1] }
  return { page: 'home' }
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseRoute())
  const [idea, setIdea] = useState<string | undefined>()
  const [imported, setImported] = useState<Proposal | undefined>()
  const [health, setHealth] = useState<Health | null>(null)
  const [warp, setWarp] = useState<string | null | undefined>(undefined) // undefined = no warp; else target agent
  const [, bump] = useState(0)

  useEffect(() => {
    const onHash = () => { setRoute(parseRoute()); setIdea(undefined); setImported(undefined) }
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

  const superMode = route.page === 'super'
  useEffect(() => {
    if (superMode) document.documentElement.dataset.mode = 'super'
    else delete document.documentElement.dataset.mode
  }, [superMode])

  const go = (hash: string, r: Route) => { history.pushState(null, '', hash); setRoute(r); scrollTo(0, 0) }
  const open = (sid: string, initial?: string, proposal?: Proposal) => {
    setIdea(initial)
    setImported(proposal)
    go(`#/s/${sid}`, { page: 'strategy', id: sid })
  }
  const home = () => { setIdea(undefined); setImported(undefined); go('#/', { page: 'home' }) }
  const enterSuper = (agent?: string) => setWarp(agent ?? null)
  const warpDone = () => {
    if (warp === undefined) return
    setWarp(undefined)
    go(warp ? `#/super/${warp}` : '#/super', { page: 'super', agent: warp ?? undefined })
  }

  return (
    <div className="app">
      {warp !== undefined && <Warp onDone={warpDone} />}
      <header className="topbar">
        <button className="brand" onClick={home} aria-label="Purple Trade home">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="8" fill="var(--accent)" /><path d="M8 21l5-6 4 3 7-9" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          Purple Trade
        </button>
        <span className="tag">{superMode ? 'SUPERAGENT MODE' : 'NSE · daily · research'}</span>
        {!superMode && <button className="super-btn" onClick={() => enterSuper()}>⚡ Trading SuperAgent</button>}
      </header>
      {route.page === 'strategy'
        ? <Workspace key={route.id} id={route.id} initialIdea={idea} initialProposal={imported} health={health} onBack={home} onRenamed={() => bump(x => x + 1)} />
        : route.page === 'super'
          ? <SuperAgent key={route.agent ?? 'none'} health={health} initialAgent={route.agent} onExit={home} />
          : <Home health={health} onOpen={open} onSuper={enterSuper} />}
    </div>
  )
}
