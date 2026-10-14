import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Health, Proposal, StrategySummary, Template } from '../types'
import { errText } from './AgentBits'
import { openAiConnect } from '../lib/aiSettings'
import { BotBadge } from './Desk'
import { IconPlay, IconSpark, IconUpload, IconUser } from './Icons'

const EXAMPLES = [
  { label: 'RSI 10 in, 90 out', text: 'Buy when RSI is 10 and sell when RSI goes above 90' },
  { label: 'Dip below the 20-day average', text: 'Buy when the share drops below its 20-day moving average; sell after 2 days, or at 1% profit, or 1% stop loss' },
  { label: 'EMA 10 / 50 crossover', text: 'Buy when the 10-day EMA crosses above the 50-day EMA; sell when it crosses back below or on a 7% loss' },
]

export function Build({ health, onOpen, onTest }: {
  health: Health | null; onOpen: (id: string, idea?: string, proposal?: Proposal) => void; onTest: (botId: string) => void
}) {
  const [idea, setIdea] = useState('')
  const [list, setList] = useState<StrategySummary[] | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const aiReady = Boolean(health?.ai.available)

  const refresh = () => api.listStrategies().then(setList).catch(e => setErr(errText(e)))
  useEffect(() => { refresh(); api.templates().then(setTemplates).catch(() => {}) }, [])

  const start = async (text: string) => {
    const t = text.trim()
    if (!t || busy) return
    setBusy(true); setErr(null)
    try {
      const s = await api.createStrategy(t.length > 48 ? t.slice(0, 45).trimEnd() + '…' : t)
      onOpen(s.id, aiReady ? t : undefined)
    } catch (e) { setErr(errText(e)); setBusy(false) }
  }

  const upload = async (file: File | undefined) => {
    if (!file) return
    setErr(null); setUploading(file.name)
    try {
      const r = await api.importAgent(file)
      onOpen(r.strategy.id, undefined, r.proposal ?? undefined)
    } catch (e) { setErr(errText(e)); setUploading(null) } finally { if (fileRef.current) fileRef.current.value = '' }
  }

  const test = async (s: StrategySummary) => {
    try { const d = await api.getStrategy(s.id); onTest(`version:${d.versions[0].id}`) } catch (e) { setErr(errText(e)) }
  }

  const remove = async (s: StrategySummary) => {
    if (!confirm(`Delete "${s.name}" with all its versions and results? This cannot be undone.`)) return
    await api.deleteStrategy(s.id)
    refresh()
  }

  return (
    <div className="page wide build-page">
      <section className="hero hero-build" aria-labelledby="build-h">
        <h1 id="build-h" className="hero-title">Describe a trading idea. Get a bot.</h1>
        <div className="compose">
          <label htmlFor="idea" className="visually-hidden">Your idea</label>
          <textarea id="idea" rows={3} value={idea} onChange={e => setIdea(e.target.value)}
            placeholder="Buy when the close is above the 200-day average and RSI(14) is under 40; take profit at 6%, stop at 3%"
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); start(idea) } }} />
          <div className="compose-row">
            <p className="compose-ai">
              <span className={`status-dot ${aiReady ? 'on' : 'off'}`} aria-hidden />
              {health ? (aiReady ? `Drafted by ${health.ai.model}${health.ai.provider === 'gemini' ? ' (your idea is sent to Google)' : ''}` : 'No AI yet: you can still write rules by hand.') : 'Checking the AI…'}
              {health && !aiReady && <> <button className="link-btn on-dark" onClick={openAiConnect}>Connect an AI</button></>}
            </p>
            <div className="compose-actions">
              <input ref={fileRef} type="file" hidden aria-label="File to turn into rules"
                accept=".py,.pine,.js,.ts,.mq4,.mq5,.mql,.cs,.java,.r,.ipynb,.txt,.md,.json,.csv,.tsv,.xlsx,.xlsm,.docx,.pdf"
                onChange={e => upload(e.target.files?.[0])} />
              <button className="btn ghost-dark" onClick={() => fileRef.current?.click()} disabled={Boolean(uploading)}
                title="Bot code (Python, Pine Script, JavaScript, MQL), notes, Excel, Word, PDF or a Purple .json file. Nothing is run.">
                <IconUpload /> {uploading ? 'Reading the file…' : 'Upload a file'}
              </button>
              <button className="btn glow" onClick={() => aiReady ? start(idea) : openAiConnect()} disabled={busy || !idea.trim()}><IconSpark /> {busy ? 'Opening…' : 'Draft the rules'}</button>
            </div>
          </div>
        </div>
        {uploading && <p className="hero-note">Turning {uploading} into rules. This can take up to a minute.</p>}
        <div className="chips hero-chips" aria-label="Examples">
          {EXAMPLES.map(x => <button key={x.label} className="chip" title={x.text} onClick={() => setIdea(x.text)}>{x.label}</button>)}
        </div>
        {err && <p className="hero-error" role="alert">{err}</p>}
      </section>

      {templates.length > 0 && (
        <section className="library" aria-labelledby="tpl-h">
          <h2 id="tpl-h" className="section-title">Or start from a ready-made rule set</h2>
          <div className="tpl-grid">
            {templates.map(t => (
              <button key={t.id} className="tpl-card"
                onClick={async () => { const s = await api.createStrategy('Untitled strategy', t.id); onOpen(s.id) }}>
                <BotBadge id={t.id} />
                <b>{t.title}</b>
                <span>{t.blurb}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="library" aria-labelledby="lib-h">
        <h2 id="lib-h" className="section-title">Your bots</h2>
        {list === null ? <p className="field-note">Loading…</p> : list.length === 0 ? (
          <p className="field-note">None yet. Bots you draft show up here.</p>
        ) : (
          <ul className="mine-grid">
            {list.map(s => (
              <li key={s.id} className="mine-card">
                <button className="mine-open" onClick={() => onOpen(s.id)} aria-label={`Open ${s.name}`}>
                  <span className="bot-badge md look-violet" aria-hidden="true"><IconUser /></span>
                  <b>{s.name}</b>
                  <span className={`badge ${s.versions ? 'ok' : ''}`}>{s.versions ? `${s.versions} version${s.versions > 1 ? 's' : ''}` : 'Draft'}</span>
                  <span className="sub">Changed {new Date(s.updated_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
                </button>
                <div className="mine-actions">
                  {s.versions > 0 && <button className="btn sm" onClick={() => test(s)}><IconPlay /> Test</button>}
                  <button className="link-btn danger" onClick={() => remove(s)} aria-label={`Delete ${s.name}`}>Delete</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
