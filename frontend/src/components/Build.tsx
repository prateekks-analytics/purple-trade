import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Health, Proposal, StrategySummary, Template } from '../types'
import { errText } from './AgentBits'

const EXAMPLES = [
  'Buy when RSI is 10 and sell when RSI goes above 90',
  'Buy when the share drops below its 20-day moving average; sell after 2 days, or at 1% profit, or 1% stop loss',
  'Buy when the 10-day EMA crosses above the 50-day EMA; sell when it crosses back below or on a 7% loss',
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
    <div className="page">
      <header className="page-head">
        <h1>Build your own</h1>
        <p className="lede">Describe a trading idea in plain words, or upload a file that describes one. You get exact buy and sell rules that you can read, edit and test. Nothing you upload is ever run.</p>
      </header>

      <section className="compose" aria-label="Describe an idea">
        <label htmlFor="idea" className="label">Your idea</label>
        <textarea id="idea" rows={3} value={idea} onChange={e => setIdea(e.target.value)}
          placeholder="Buy when the close is above the 200-day average and RSI(14) is under 40; take profit at 6%, stop at 3%"
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); start(idea) } }} />
        <div className="compose-row">
          <p className="field-note">
            <span className={`status-dot ${aiReady ? 'on' : 'off'}`} aria-hidden />
            {health ? (aiReady ? `Drafted by ${health.ai.model} on this computer. Free.` : 'The local AI is offline: you can still write rules by hand.') : 'Checking the local AI…'}
          </p>
          <div className="compose-actions">
            <input ref={fileRef} type="file" hidden aria-label="File to turn into rules"
              accept=".py,.pine,.js,.ts,.mq4,.mq5,.mql,.cs,.java,.r,.ipynb,.txt,.md,.json,.csv,.tsv,.xlsx,.xlsm,.docx,.pdf"
              onChange={e => upload(e.target.files?.[0])} />
            <button className="btn quiet" onClick={() => fileRef.current?.click()} disabled={Boolean(uploading)}
              title="Bot code (Python, Pine Script, JavaScript, MQL), notes, Excel, Word, PDF or a Purple .json file">
              {uploading ? 'Reading the file…' : 'Upload a file'}
            </button>
            <button className="btn primary" onClick={() => start(idea)} disabled={busy || !idea.trim()}>{busy ? 'Opening…' : 'Draft the rules'}</button>
          </div>
        </div>
        {uploading && <p className="field-note">Turning {uploading} into rules. This can take up to a minute.</p>}
        <div className="examples">
          <span className="field-note">Examples:</span>
          {EXAMPLES.map(x => <button key={x} className="example" onClick={() => setIdea(x)}>{x}</button>)}
        </div>
        {err && <p className="error-text" role="alert">{err}</p>}
      </section>

      <section className="library" aria-labelledby="lib-h">
        <h2 id="lib-h">Your strategies</h2>
        {list === null ? <p className="field-note">Loading…</p> : list.length === 0 ? (
          <p className="field-note">None yet. Strategies you draft appear here with their saved versions.</p>
        ) : (
          <table className="strategy-table">
            <thead><tr><th scope="col">Name</th><th scope="col">Status</th><th scope="col">Last changed</th><th scope="col"><span className="visually-hidden">Actions</span></th></tr></thead>
            <tbody>
              {list.map(s => (
                <tr key={s.id}>
                  <td><button className="link-btn strong" onClick={() => onOpen(s.id)}>{s.name}</button></td>
                  <td className="sub">{s.versions ? `${s.versions} saved version${s.versions > 1 ? 's' : ''}` : 'Draft, not saved'}</td>
                  <td className="sub">{new Date(s.updated_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</td>
                  <td className="r row-actions">
                    <button className="btn quiet sm" onClick={() => onOpen(s.id)} aria-label={`Open ${s.name}`}>Open</button>
                    {s.versions > 0 && <button className="btn quiet sm" onClick={() => test(s)}>Test latest version</button>}
                    <button className="link-btn danger" onClick={() => remove(s)} aria-label={`Delete ${s.name}`}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {templates.length > 0 && (
          <p className="starters">
            <span className="field-note">Or start from a ready-made rule set:</span>
            {templates.map(t => (
              <button key={t.id} className="example" title={t.blurb}
                onClick={async () => { const s = await api.createStrategy('Untitled strategy', t.id); onOpen(s.id) }}>{t.title}</button>
            ))}
          </p>
        )}
      </section>
    </div>
  )
}
