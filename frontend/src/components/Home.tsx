import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { Health, Proposal, StrategySummary, SuperAgentInfo, Template } from '../types'

const EXAMPLES = [
  { label: 'RSI 10 → 90', text: 'Buy when RSI is 10 and sell when RSI goes above 90' },
  { label: '20-day SMA dip, 1% exit', text: 'Buy when the share drops below its 20-day moving average; sell after 2 days, or at 1% profit, or 1% stop loss' },
  { label: 'EMA 10/50 cross, 7% stop', text: 'Buy when 10-day EMA crosses above 50-day EMA; exit when it crosses back below or on a 7% loss' },
]
const KIND = { 'ta-original': 'Original AI agents', 'ai-team': 'AI agent team', rules: 'Rule bot', research: 'Research crew' } as const
const SHOWN = 6

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
  const [showAll, setShowAll] = useState(false)

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
        <h1>Describe a trading idea</h1>
        <p className="lede">Plain words in, exact rules out — tested on NSE daily prices.</p>
        <div className="idea-box">
          <textarea rows={3} value={idea} onChange={e => setIdea(e.target.value)} aria-label="Your trading idea"
            placeholder="e.g. Buy when the close is above the 200-day SMA and RSI(14) is under 40; take profit at 6%, stop at 3%"
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); start(idea) } }} />
          <div className="idea-row">
            <span className={`ai-pill ${aiReady ? 'on' : 'off'}`} title={health?.ai.detail}>
              <i aria-hidden /> {health ? (aiReady ? `AI: ${health.ai.model} (local, free)` : 'AI offline — manual rules only') : 'Checking AI…'}
            </span>
            <div className="idea-actions">
              <input ref={agentRef} type="file" hidden aria-label="File to convert into rules"
                accept=".py,.pine,.js,.ts,.mq4,.mq5,.mql,.cs,.java,.r,.ipynb,.txt,.md,.json,.csv,.tsv,.xlsx,.xlsm,.docx,.pdf"
                onChange={e => uploadAgent(e.target.files?.[0])} />
              <button className="btn ghost" onClick={() => agentRef.current?.click()} disabled={Boolean(uploading)}
                title="Bot or agent code (Python, Pine Script, JS, MQL…), notes, Excel, CSV, Word, PDF or a Purple .json. Read and converted into editable rules — never run.">
                {uploading ? 'Reading…' : 'Upload file'}
              </button>
              <button className="btn" onClick={() => start(idea)} disabled={busy || !idea.trim()}>{busy ? 'Opening…' : 'Build it →'}</button>
            </div>
          </div>
        </div>
        {uploading && <p className="muted small upload-note">Converting {uploading} into rules — this can take up to a minute. Files are read, never run.</p>}
        <div className="examples">
          <span className="muted small">Try</span>
          {EXAMPLES.map(x => <button key={x.label} className="example" title={x.text} onClick={() => setIdea(x.text)}>{x.label}</button>)}
        </div>
        {err && <p className="error-text" role="alert">{err}</p>}
      </section>

      <div className="home-cols">
        <section className="library" aria-labelledby="lib-h">
          <h2 id="lib-h">Your strategies</h2>
          {list === null ? <p className="muted">Loading…</p> : list.length === 0 ? (
            <p className="muted small">Nothing yet. Your strategies, versions and results will be listed here.</p>
          ) : (
            <ul className="strategy-list">
              {(showAll ? list : list.slice(0, SHOWN)).map(s => (
                <li key={s.id}>
                  <button className="strategy-row" onClick={() => onOpen(s.id)}>
                    <b>{s.name}</b>
                    <span className="muted small">{s.versions ? `${s.versions} version${s.versions > 1 ? 's' : ''}` : 'draft'} · {new Date(s.updated_at).toLocaleDateString()}</span>
                  </button>
                  <button className="icon-btn" aria-label={`Delete ${s.name}`} title="Delete" onClick={() => remove(s)}>×</button>
                </li>
              ))}
              {list.length > SHOWN && (
                <li><button className="strategy-more" onClick={() => setShowAll(v => !v)}>{showAll ? 'Show fewer' : `Show all ${list.length}`}</button></li>
              )}
            </ul>
          )}
          {templates.length > 0 && (
            <p className="starters-inline">
              <span className="muted small">Or start from an example:</span>
              {templates.map(t => <button key={t.id} className="chip" title={t.blurb} onClick={() => fromTemplate(t.id)}>{t.title}</button>)}
            </p>
          )}
        </section>

        {featured.length > 0 && (
          <section className="featured" aria-labelledby="featured-h">
            <h2 id="featured-h">Featured agents</h2>
            <ul className="feat-list">
              {featured.map(a => (
                <li key={a.id}>
                  <button className={`feat-row kind-${a.kind}`} onClick={() => onSuper(a.id)} title={a.tagline}>
                    <b>{a.title}</b>
                    <span>{KIND[a.kind]}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
      <footer className="home-foot">Research tool for your own analysis. Backtests are estimates and not investment advice. No orders are placed.</footer>
    </div>
  )
}
