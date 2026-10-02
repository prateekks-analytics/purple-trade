import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { Health, Proposal, StrategySummary, SuperAgentInfo, Template } from '../types'

const EXAMPLES = [
  'Buy when RSI is 10 and sell when RSI goes above 90',
  'Buy when the share drops below its 20-day moving average; sell after 2 days, or at 1% profit, or 1% stop loss',
  'Buy when 10-day EMA crosses above 50-day EMA; exit when it crosses back below or on a 7% loss',
]

export function Home({ health, onOpen, onSuper }: {
  health: Health | null; onOpen: (id: string, idea?: string, proposal?: Proposal) => void; onSuper: (agentId?: string) => void
}) {
  const [idea, setIdea] = useState('')
  const [featured, setFeatured] = useState<SuperAgentInfo[]>([])
  useEffect(() => { api.saAgents().then(a => setFeatured(a.filter(x => x.available))).catch(() => {}) }, [])
  const [list, setList] = useState<StrategySummary[] | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const aiReady = Boolean(health?.ai.available)
  const agentRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState<string | null>(null)

  const uploadAgent = async (file: File | undefined) => {
    if (!file) return
    setErr(null)
    setUploading(file.name)
    try {
      const r = await api.importAgent(file)
      onOpen(r.strategy.id, undefined, r.proposal ?? undefined)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
      setUploading(null)
    } finally {
      if (agentRef.current) agentRef.current.value = ''
    }
  }

  const refresh = () => api.listStrategies().then(setList).catch(e => setErr(e instanceof ApiError ? e.message : String(e)))
  useEffect(() => { refresh(); api.templates().then(setTemplates).catch(() => {}) }, [])

  const start = async (text: string) => {
    const t = text.trim()
    if (!t || busy) return
    setBusy(true); setErr(null)
    try {
      const name = t.length > 48 ? t.slice(0, 45).trimEnd() + '…' : t
      const s = await api.createStrategy(name)
      onOpen(s.id, aiReady ? t : undefined)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e)); setBusy(false)
    }
  }

  const fromTemplate = async (tid: string) => {
    const s = await api.createStrategy('Untitled strategy', tid)
    onOpen(s.id)
  }

  const remove = async (s: StrategySummary) => {
    if (!confirm(`Delete "${s.name}" and all its versions and results? This cannot be undone.`)) return
    await api.deleteStrategy(s.id)
    refresh()
  }

  return (
    <div className="home">
      <section className="hero">
        <h1>Describe a trading idea. See exactly what it does.</h1>
        <p className="lede">Write it the way you'd say it. Purple Trade turns it into precise rules you can read and edit, then tests them on NSE daily prices right away.</p>
        <div className="idea-box">
          <textarea rows={3} value={idea} onChange={e => setIdea(e.target.value)} aria-label="Your trading idea"
            placeholder="e.g. Buy when the close is above the 200-day SMA and RSI(14) is under 40; take profit at 6%, stop at 3%"
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); start(idea) } }} />
          <div className="idea-row">
            <span className={`ai-pill ${aiReady ? 'on' : 'off'}`} title={health?.ai.detail}>
              <i aria-hidden /> {health ? (aiReady ? `AI: ${health.ai.model} (local, free)` : 'AI offline — manual rules only') : 'Checking AI…'}
            </span>
            <button className="btn" onClick={() => start(idea)} disabled={busy || !idea.trim()}>{busy ? 'Opening…' : 'Build it →'}</button>
          </div>
        </div>
        <div className="agent-upload">
          <input ref={agentRef} type="file" hidden aria-label="Agent file"
            accept=".json,.py,.pine,.txt,.md,.js,.ts,.mq4,.mq5,.mql,.cs,.java,.r,.ipynb"
            onChange={e => uploadAgent(e.target.files?.[0])} />
          <button className="btn ghost" onClick={() => agentRef.current?.click()} disabled={Boolean(uploading)}>
            {uploading ? `Translating ${uploading}…` : '⇪ Upload an agent'}
          </button>
          <span className="muted small">
            {uploading ? "Reading the bot's logic into rules — this can take up to a minute."
              : 'Already have a bot? Upload its code (Python, Pine Script, JS, MQL…) or a Purple .json. It is read and converted into editable rules — never run.'}
          </span>
        </div>
        <div className="examples">
          <span className="muted small">Try:</span>
          {EXAMPLES.map(x => <button key={x} className="example" onClick={() => setIdea(x)}>{x}</button>)}
        </div>
        {err && <p className="error-text" role="alert">{err}</p>}
      </section>

      {featured.length > 0 && (
        <section className="featured" aria-labelledby="featured-h">
          <div className="featured-head">
            <h2 id="featured-h">Featured bots</h2>
            <button className="super-btn" onClick={() => onSuper()}>⚡ Open Trading SuperAgent</button>
          </div>
          <p className="muted small">From the TradingAgents project (Tauric Research). Pick one to backtest, paper trade and deploy it in SuperAgent.</p>
          <div className="featured-grid">
            {featured.map((a, i) => (
              <button key={a.id} className={`feat ${a.kind} ${i === 0 ? 'hero-feat' : ''}`} onClick={() => onSuper(a.id)}>
                <span className="feat-kind">{a.kind === 'ai-team' ? 'AI agent team' : 'Rule bot'}</span>
                <b>{a.title}</b>
                <span>{a.tagline}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {templates.length > 0 && (
        <section className="starters">
          <h2>Or start from a working example</h2>
          <div className="starter-grid">
            {templates.map(t => (
              <button key={t.id} className="starter" onClick={() => fromTemplate(t.id)}>
                <b>{t.title}</b>
                <span>{t.blurb}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="library">
        <h2>Your strategies</h2>
        {list === null ? <p className="muted">Loading…</p> : list.length === 0 ? (
          <p className="muted">Nothing yet. Your strategies, versions and results will be listed here.</p>
        ) : (
          <ul className="strategy-list">
            {list.map(s => (
              <li key={s.id}>
                <button className="strategy-row" onClick={() => onOpen(s.id)}>
                  <b>{s.name}</b>
                  <span className="muted small">{s.versions ? `${s.versions} saved version${s.versions > 1 ? 's' : ''}` : 'draft'} · edited {new Date(s.updated_at).toLocaleString()}</span>
                </button>
                <button className="icon-btn" aria-label={`Delete ${s.name}`} title="Delete" onClick={() => remove(s)}>×</button>
              </li>
            ))}
          </ul>
        )}
      </section>
      <footer className="home-foot">Research tool for your own analysis. Backtests are estimates and not investment advice. No orders are placed.</footer>
    </div>
  )
}
