import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { BacktestResult, Dataset, Health, Proposal, Review, Strategy, StrategyDoc } from '../types'
import { blankStrategy, crossesToCompare } from '../lib/tree'
import { Chat, type LiveProposal } from './Chat'
import { GraphView } from './GraphView'
import { RuleEditor } from './RuleEditor'
import { DataPicker, Results } from './Results'

let proposalKey = 0

export function Workspace({ id, initialIdea, initialProposal, health, onBack, onRenamed }: {
  id: string; initialIdea?: string; initialProposal?: Proposal; health: Health | null; onBack: () => void; onRenamed: () => void
}) {
  const [doc, setDoc] = useState<StrategyDoc | null>(null)
  const [draft, setDraft] = useState<Strategy | null>(null)
  const [review, setReview] = useState<Review | null>(null)
  const [saveState, setSaveState] = useState<'idle' | 'pending' | 'saving' | 'saved' | 'error'>('idle')
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [proposals, setProposals] = useState<LiveProposal[]>(() =>
    initialProposal ? [{ ...initialProposal, key: ++proposalKey, status: 'pending', base: null }] : [])
  const [showSource, setShowSource] = useState(Boolean(initialProposal))
  const [chatBusy, setChatBusy] = useState(false)
  const [chatText, setChatText] = useState('')
  const [view, setView] = useState<'rules' | 'graph'>('rules')
  const [versionId, setVersionId] = useState<string | null>(null)
  const [versionBody, setVersionBody] = useState<Strategy | null>(null)
  const [toast, setToast] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const editSeq = useRef(0)
  const runSeq = useRef(0)
  const sentInitial = useRef(false)
  const reviewRef = useRef<Review | null>(null)
  reviewRef.current = review

  const aiReady = Boolean(health?.ai.available)

  // ---------- load ----------
  useEffect(() => {
    let alive = true
    Promise.all([api.getStrategy(id), api.datasets()]).then(([d, ds]) => {
      if (!alive) return
      setDoc(d); setDraft(d.draft); setReview(d.review); setDatasets(ds)
      const lastId = safeGet(`purple.dataset.${id}`)
      setDatasetId(ds.find(x => x.id === lastId)?.id ?? ds[0]?.id ?? null)
    }).catch(e => setLoadError(e instanceof ApiError ? e.message : String(e)))
    return () => { alive = false }
  }, [id])

  // ---------- backtest ----------
  const runTest = useCallback(async (vid: string | null) => {
    if (!datasetId) return
    const seq = ++runSeq.current
    setRunning(true); setRunError(null)
    try {
      const r = await api.backtest(id, datasetId, vid ?? undefined)
      if (seq === runSeq.current) setResult(r)
    } catch (e) {
      if (seq === runSeq.current) {
        setResult(null)
        setRunError(e instanceof ApiError ? (e.details.length ? e.details.join(' ') : e.message) : String(e))
      }
    } finally {
      if (seq === runSeq.current) setRunning(false)
    }
  }, [id, datasetId])

  const testable = (r: Review | null) =>
    Boolean(r?.valid_shape && r.validation && r.validation.errors.every(e => e.includes('open question')))

  // ---------- autosave + autotest on every edit ----------
  useEffect(() => {
    if (!draft || !doc || draft === doc.draft) return
    const seq = ++editSeq.current
    setSaveState('pending')
    const t = setTimeout(async () => {
      setSaveState('saving')
      try {
        const d = await api.saveDraft(id, draft)
        if (seq !== editSeq.current) return
        setDoc(prev => (prev ? { ...d, draft } : d))
        setReview(d.review)
        setSaveState('saved')
        if (d.review?.strategy?.name !== doc.name) onRenamed()
        if (!versionId && testable(d.review)) runTest(null)
      } catch (e) {
        if (seq !== editSeq.current) return
        setSaveState('error')
        setToast({ kind: 'err', text: e instanceof ApiError ? (e.details[0] ?? e.message) : String(e) })
      }
    }, 450)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft])

  // initial / dataset change test
  useEffect(() => {
    if (!datasetId) return
    if (versionId) runTest(versionId)
    else if (testable(review)) runTest(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, versionId, review === null])

  // ---------- AI ----------
  const send = useCallback(async (text: string) => {
    setChatBusy(true); setChatText('')
    setDoc(d => (d ? { ...d, chat: [...d.chat, { role: 'user', content: text }] } : d))
    try {
      const p = await api.propose(id, text)
      const live: LiveProposal = { ...p, key: ++proposalKey, status: 'pending', base: reviewRef.current }
      setDoc(d => (d ? { ...d, chat: [...d.chat, { role: 'assistant', content: assistantText(p) }] } : d))
      setProposals(ps => [...ps.map(x => (x.status === 'pending' ? { ...x, status: 'discarded' as const } : x)), live])
    } catch (e) {
      setDoc(d => (d ? { ...d, chat: [...d.chat, { role: 'assistant', content: `⚠ ${e instanceof ApiError ? e.message : String(e)}` }] } : d))
    } finally {
      setChatBusy(false)
    }
  }, [id])

  useEffect(() => {
    if (doc && initialIdea && !sentInitial.current && doc.chat.length === 0 && aiReady) {
      sentInitial.current = true
      send(initialIdea)
    }
  }, [doc, initialIdea, aiReady, send])

  const edit = (s: Strategy) => { setVersionId(null); setVersionBody(null); setDraft(s) }

  const apply = (p: LiveProposal, transform?: (s: Strategy) => Strategy) => {
    if (!p.strategy) return
    edit(transform ? transform(p.strategy) : p.strategy)
    setProposals(ps => ps.map(x => (x.key === p.key ? { ...x, status: 'applied' } : x)))
  }

  // ---------- versions ----------
  const saveVersion = async () => {
    try {
      const d = await api.approve(id)
      setDoc(prev => (prev ? { ...d, draft: prev.draft } : d))
      setToast({ kind: 'ok', text: `Saved as version ${d.versions[0].number}. It can't be changed; keep editing to make the next one.` })
    } catch (e) {
      setToast({ kind: 'err', text: e instanceof ApiError ? (e.details.join(' ') || e.message) : String(e) })
    }
  }

  const pickVersion = async (vid: string) => {
    if (!vid) { setVersionId(null); setVersionBody(null); if (testable(review)) runTest(null); return }
    const v = await api.getVersion(vid)
    setVersionBody(v.body); setVersionId(vid)
  }

  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(null), 6000); return () => clearTimeout(t) } }, [toast])

  if (loadError) return <div className="page-error">{loadError} <button className="link-btn" onClick={onBack}>Back</button></div>
  if (!doc) return <div className="page-loading">Loading…</div>

  const shown = versionBody ?? draft
  const v = review?.validation
  const questions = draft?.questions ?? []
  const blockers = v?.errors ?? []
  const latest = doc.versions[0]
  const matchesLatest = latest && review?.hash === latest.hash
  const canSave = Boolean(draft && v?.ok && !matchesLatest && saveState !== 'pending' && saveState !== 'saving')
  const saveHint = !draft ? 'Create rules first'
    : questions.length ? `Answer or dismiss ${questions.length} question${questions.length > 1 ? 's' : ''} first`
    : blockers.length ? blockers[0]
    : matchesLatest ? `Same as version ${latest.number}`
    : ''

  const setQuestions = (qs: string[]) => draft && edit({ ...draft, questions: qs })

  const download = async () => {
    try {
      const payload = await api.exportStrategy(id, versionId)
      const label = versionId ? `v${doc.versions.find(x => x.id === versionId)?.number}` : 'draft'
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `${(payload.strategy.name || 'strategy').replace(/[^\w-]+/g, '_')}-${label}.purple.json`
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) {
      setToast({ kind: 'err', text: e instanceof ApiError ? e.message : String(e) })
    }
  }

  return (
    <div className="workspace">
      <Chat messages={doc.chat} proposals={proposals} busy={chatBusy}
        aiReady={aiReady} aiDetail={health?.ai.detail ?? 'checking…'}
        draftText={chatText} setDraftText={setChatText} onSend={send}
        onApply={p => apply(p)}
        onFixCrosses={p => apply(p, s => ({ ...s, entry: crossesToCompare(s.entry), exit: crossesToCompare(s.exit) }))}
        onDiscard={p => setProposals(ps => ps.map(x => (x.key === p.key ? { ...x, status: 'discarded' } : x)))} />

      <main className="canvas">
        <div className="canvas-head">
          <button className="link-btn back" onClick={onBack} aria-label="All strategies">← Strategies</button>
          {draft ? (
            <input className="title-input" value={draft.name} aria-label="Strategy name" maxLength={120}
              onChange={e => edit({ ...draft, name: e.target.value })} />
          ) : <h1 className="title-input">{doc.name}</h1>}
          <span className={`save-state ${saveState}`}>
            {versionId ? 'Viewing a saved version (read-only)'
              : saveState === 'pending' || saveState === 'saving' ? 'Saving…'
              : saveState === 'error' ? 'Not saved'
              : draft ? 'Draft auto-saved' : ''}
          </span>
          <div className="head-right">
            {doc.versions.length > 0 && (
              <select className="version-select" aria-label="Version" value={versionId ?? ''} onChange={e => pickVersion(e.target.value)}>
                <option value="">Draft (editing)</option>
                {doc.versions.map(x => <option key={x.id} value={x.id}>Version {x.number} · {x.created_at.slice(0, 10)}</option>)}
              </select>
            )}
            {shown && <button className="btn ghost sm" onClick={download} title="Download these rules as a Purple .json file (re-uploadable)">Download JSON</button>}
            {versionId && versionBody ? (
              <button className="btn ghost sm" onClick={() => edit({ ...versionBody, questions: [] })}>Edit from this version</button>
            ) : (
              <button className="btn sm" onClick={saveVersion} disabled={!canSave} title={saveHint || 'Freeze these rules as a version'}>
                Save version{doc.versions.length ? ` ${doc.versions.length + 1}` : ''}
              </button>
            )}
          </div>
        </div>
        {!versionId && saveHint && draft && !matchesLatest && <div className="save-hint">{saveHint}</div>}

        {doc.source && (
          <details className="source-panel" open={showSource} onToggle={e => setShowSource((e.target as HTMLDetailsElement).open)}>
            <summary>
              Uploaded agent: <b>{doc.source.filename}</b>
              <span className="muted small"> · {doc.source.kind === 'code' ? 'translated by AI — compare with the rules below' : 'imported exactly'} · never executed</span>
            </summary>
            <pre><code>{doc.source.content}</code></pre>
          </details>
        )}

        {!shown ? (
          <div className="no-rules">
            <h2>No rules yet</h2>
            <p>Describe your idea in the conversation, or start from an empty rule set.</p>
            <button className="btn" onClick={() => edit(blankStrategy(doc.name))}>Start with empty rules</button>
          </div>
        ) : (
          <>
            {!versionId && questions.length > 0 && (
              <div className="questions" role="region" aria-label="Open questions">
                {questions.map((q, i) => (
                  <div className="question" key={i}>
                    <span className="q-icon" aria-hidden>?</span>
                    <span className="q-text">{q}</span>
                    <button className="link-btn" onClick={() => setChatText(`About "${q}": `)}>Answer</button>
                    <button className="link-btn muted" onClick={() => setQuestions(questions.filter((_, j) => j !== i))}>Dismiss</button>
                  </div>
                ))}
              </div>
            )}
            {!versionId && v && v.errors.filter(e => !e.includes('open question')).map((e, i) => <div key={i} className="alert err">✕ {e}</div>)}
            {!versionId && v && v.warnings.map((w, i) => <div key={i} className="alert warn">⚠ {w}</div>)}
            {!versionId && review && !review.valid_shape && review.shape_errors?.map((e, i) => <div key={i} className="alert err">✕ {e}</div>)}

            <div className="view-toggle" role="tablist" aria-label="Rules view">
              <button role="tab" aria-selected={view === 'rules'} className={view === 'rules' ? 'on' : ''} onClick={() => setView('rules')}>Rules</button>
              <button role="tab" aria-selected={view === 'graph'} className={view === 'graph' ? 'on' : ''} onClick={() => setView('graph')}>Flow diagram</button>
            </div>

            {view === 'rules' ? (
              <fieldset className="rules" disabled={Boolean(versionId)}>
                <RuleEditor side="entry" value={shown.entry} onChange={entry => edit({ ...shown, entry })} />
                <RuleEditor side="exit" value={shown.exit} onChange={exit => edit({ ...shown, exit })} />
                <div className="settings">
                  <label>Capital ₹<input type="number" min={1000} step={1000} value={shown.initial_capital}
                    onChange={e => edit({ ...shown, initial_capital: Math.max(1000, Number(e.target.value) || 1000) })} /></label>
                  <label>Per trade<input type="number" min={1} max={100} value={shown.sizing.value}
                    onChange={e => edit({ ...shown, sizing: { ...shown.sizing, value: Math.min(100, Math.max(1, Number(e.target.value) || 1)) } })} />% of equity</label>
                  <label>Fee<input type="number" min={0} max={500} step={0.5} value={shown.costs.fee_bps}
                    onChange={e => edit({ ...shown, costs: { ...shown.costs, fee_bps: Math.max(0, Number(e.target.value) || 0) } })} />bps</label>
                  <label>Slippage<input type="number" min={0} max={500} step={0.5} value={shown.costs.slippage_bps}
                    onChange={e => edit({ ...shown, costs: { ...shown.costs, slippage_bps: Math.max(0, Number(e.target.value) || 0) } })} />bps</label>
                </div>
                {review?.describe && !versionId && <p className="execution">{review.describe.execution}</p>}
              </fieldset>
            ) : <GraphView strategy={shown} />}

            <section className="test-section" aria-label="Backtest results">
              <div className="test-head">
                <h2>Results {result && <span className={`badge ${result.mode === 'approved' ? 'ok' : ''}`}>{result.mode === 'approved' ? `version ${doc.versions.find(x => x.id === versionId)?.number ?? ''}` : 'draft'}</span>}</h2>
                <DataPicker datasets={datasets} value={datasetId}
                  onChange={d => { setDatasetId(d); safeSet(`purple.dataset.${id}`, d) }}
                  onUploaded={d => { setDatasets(ds => [d, ...ds.filter(x => x.id !== d.id)]); setDatasetId(d.id); safeSet(`purple.dataset.${id}`, d.id) }} />
              </div>
              <Results result={result} running={running} error={runError} />
            </section>
          </>
        )}
      </main>
      {toast && <div className={`toast ${toast.kind}`} role="status">{toast.text}</div>}
    </div>
  )
}

function assistantText(p: { ok: boolean; notes: string; error: string | null; questions: string[]; strategy: unknown }) {
  if (!p.ok) return p.error ?? 'Something went wrong.'
  const lines = [p.notes || (p.strategy ? 'Here are the rules I understood.' : 'I need a bit more detail first.')]
  return lines.join('\n')
}

function safeGet(k: string) { try { return localStorage.getItem(k) } catch { return null } }
function safeSet(k: string, v: string) { try { localStorage.setItem(k, v) } catch { /* storage unavailable */ } }
