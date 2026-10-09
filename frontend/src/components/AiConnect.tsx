import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { AiProvider } from '../types'
import { getAi, setAi } from '../lib/aiSettings'
import { errText } from './AgentBits'

// Sensible first choice from a provider's model list; the person can pick any other.
const PREFER: Record<string, RegExp[]> = {
  gemini: [/^gemini-\d+(\.\d+)?-flash$/, /flash/],
  groq: [/llama-3\.3-70b/, /gpt-oss-120b/, /llama/],
  openrouter: [/:free$/],
  openai: [/^gpt-\d+(\.\d+)?-mini$/, /^gpt-/],
  anthropic: [/sonnet/, /haiku/],
  ollama: [/qwen3/, /llama/],
}

function pickModel(p: AiProvider, models: string[]) {
  if (p.default_model && models.includes(p.default_model)) return p.default_model
  for (const re of PREFER[p.id] ?? []) {
    const hit = [...models].reverse().find(m => re.test(m))
    if (hit) return hit
  }
  return models[0] ?? ''
}

/** "Connect an AI": choose a provider, paste your own key, test it, pick a model. */
export function AiConnect({ open, onClose, hosted = false }: { open: boolean; onClose: () => void; hosted?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  const current = getAi()
  const [providers, setProviders] = useState<AiProvider[]>([])
  const [pid, setPid] = useState(current?.provider ?? 'gemini')
  const [key, setKey] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [model, setModel] = useState('')
  const [remember, setRemember] = useState(true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const p = providers.find(x => x.id === pid)

  // On the online demo, 'Ollama on this computer' would mean the server, not the visitor's computer.
  useEffect(() => { api.aiProviders().then(ps => setProviders(ps.filter(x => !(hosted && x.id === 'ollama')))).catch(e => setErr(errText(e))) }, [hosted])
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])
  useEffect(() => { setModels([]); setModel(''); setErr(null); setKey('') }, [pid])

  const test = async () => {
    if (!p) return
    setBusy(true); setErr(null); setModels([])
    try {
      const r = await api.aiTest(p.id, key.trim())
      setModels(r.models)
      setModel(pickModel(p, r.models))
    } catch (e) { setErr(errText(e)) } finally { setBusy(false) }
  }
  const save = () => { setAi({ provider: pid, model, key: key.trim() }, remember); onClose() }
  const disconnect = () => { setAi(null); onClose() }

  return (
    <dialog ref={ref} className="ai-dialog" onClose={onClose} aria-labelledby="ai-title">
      <form method="dialog" className="ai-form" onSubmit={e => e.preventDefault()}>
        <header className="ai-head">
          <h2 id="ai-title">Connect an AI</h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>×</button>
        </header>
        <p className="field-note">The AI drafts rules from your ideas and runs the AI agents. Backtests and rule bots work without it.
          Use your own key: it stays in this browser and is sent only with your own requests.</p>

        <fieldset className="ai-providers">
          <legend className="label">1. Choose a provider</legend>
          {providers.map(x => (
            <label key={x.id} className={`ai-provider ${pid === x.id ? 'on' : ''}`}>
              <input type="radio" name="ai-provider" checked={pid === x.id} onChange={() => setPid(x.id)} />
              <span><b>{x.label}</b><span className="sub ai-cost">{x.cost}</span></span>
            </label>
          ))}
        </fieldset>

        {p && (
          <div className="field">
            {p.needs_key ? (
              <>
                <label htmlFor="ai-key">2. Paste your {p.label} API key</label>
                <div className="field-row">
                  <input id="ai-key" type="password" autoComplete="off" spellCheck={false} value={key}
                    onChange={e => { setKey(e.target.value); setModels([]) }} placeholder="Paste key here" />
                  <button type="button" className="btn" onClick={test} disabled={busy || !key.trim()}>{busy ? 'Checking…' : 'Check key'}</button>
                </div>
                <p className="field-note">No key yet? <a href={p.key_url} target="_blank" rel="noreferrer">Get one from {p.label}</a> (opens in a new tab).</p>
              </>
            ) : (
              <>
                <span className="label">2. Check that Ollama is running</span>
                <div className="field-row"><button type="button" className="btn" onClick={test} disabled={busy}>{busy ? 'Checking…' : 'Check Ollama'}</button></div>
                <p className="field-note">Needs <a href={p.key_url} target="_blank" rel="noreferrer">Ollama</a> installed on this computer. No key, nothing leaves the computer.</p>
              </>
            )}
          </div>
        )}

        {models.length > 0 && (
          <div className="field">
            <label htmlFor="ai-model">3. Choose a model</label>
            <select id="ai-model" value={model} onChange={e => setModel(e.target.value)}>
              {models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            <p className="ok-text" role="status">Key works. {models.length} models available.</p>
            {p?.needs_key && (
              <label className="check-row"><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />
                Remember on this device (uncheck on a shared computer)</label>
            )}
          </div>
        )}
        {err && <p className="error-text" role="alert">{err}</p>}

        <footer className="ai-foot">
          {current && <button type="button" className="link-btn danger" onClick={disconnect}>Disconnect {current.provider}</button>}
          <span className="spacer" />
          <button type="button" className="btn quiet" onClick={onClose}>Cancel</button>
          <button type="button" className="btn primary" onClick={save} disabled={!model}>Connect</button>
        </footer>
      </form>
    </dialog>
  )
}
