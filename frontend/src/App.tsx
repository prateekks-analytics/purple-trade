import { useEffect, useState } from 'react'
import { api } from './api'
import type { Health } from './types'
import { Home } from './components/Home'
import { Workspace } from './components/Workspace'

function routeId() {
  const m = location.hash.match(/^#\/s\/([\w-]+)/)
  return m ? m[1] : null
}

export default function App() {
  const [id, setId] = useState<string | null>(routeId())
  const [idea, setIdea] = useState<string | undefined>()
  const [health, setHealth] = useState<Health | null>(null)
  const [, bump] = useState(0)

  useEffect(() => {
    const onHash = () => { setId(routeId()); setIdea(undefined) }
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

  const open = (sid: string, initial?: string) => {
    setIdea(initial)
    history.pushState(null, '', `#/s/${sid}`)
    setId(sid)
  }
  const home = () => { history.pushState(null, '', '#/'); setId(null); setIdea(undefined) }

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={home} aria-label="Purple Trade home">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="8" fill="var(--accent)" /><path d="M8 21l5-6 4 3 7-9" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          Purple Trade
        </button>
        <span className="tag">NSE · daily · research</span>
      </header>
      {id
        ? <Workspace key={id} id={id} initialIdea={idea} health={health} onBack={home} onRenamed={() => bump(x => x + 1)} />
        : <Home health={health} onOpen={open} />}
    </div>
  )
}
