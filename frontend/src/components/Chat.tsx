import { useEffect, useRef } from 'react'
import type { ChatMessage, Proposal, Review } from '../types'
import { lineDiff } from '../lib/tree'

export interface LiveProposal extends Proposal { key: number; status: 'pending' | 'applied' | 'discarded'; base: Review | null }

function ProposalCard({ p, onApply, onDiscard, onFixCrosses }: {
  p: LiveProposal
  onApply: () => void; onDiscard: () => void; onFixCrosses: () => void
}) {
  const d = p.review?.describe
  const current = p.base
  if (!p.ok) return <div className="proposal failed"><b>Could not build rules.</b> {p.error}</div>
  if (!p.strategy || !d) {
    return (
      <div className="proposal questions-only">
        <div className="proposal-head">Needs your input before any rules are drafted</div>
        <ul>{p.questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
      </div>
    )
  }
  const entryDiff = lineDiff(current?.describe?.entry_lines, d.entry_lines)
  const exitDiff = lineDiff(current?.describe?.exit_lines, d.exit_lines)
  const hasCurrent = Boolean(current?.describe)
  const crossWarn = p.fidelity.some(f => f.includes("'crosses'"))
  return (
    <div className={`proposal ${p.status}`}>
      <div className="proposal-head">
        {hasCurrent ? 'Proposed change' : 'Proposed rules'}
        <span className="muted"> · {p.model}{p.attempts > 1 ? ' · repaired once' : ''}</span>
      </div>
      <div className="proposal-rules">
        <div><span className="action-tag entry sm">▲ BUY</span>{d.entry_lines.map((l, i) => <div key={i} className="pl">{l}</div>)}</div>
        <div><span className="action-tag exit sm">▼ SELL</span>{d.exit_lines.map((l, i) => <div key={i} className="pl">{l}</div>)}</div>
      </div>
      {hasCurrent && (entryDiff.added.length + entryDiff.removed.length + exitDiff.added.length + exitDiff.removed.length > 0) && (
        <div className="diff">
          {[...entryDiff.removed, ...exitDiff.removed].map((l, i) => <div key={'r' + i} className="del">− {l}</div>)}
          {[...entryDiff.added, ...exitDiff.added].map((l, i) => <div key={'a' + i} className="add">+ {l}</div>)}
        </div>
      )}
      {p.fidelity.length > 0 && (
        <div className="checks">
          {p.fidelity.map((f, i) => <div key={i} className="check">⚠ {f}</div>)}
          {crossWarn && p.status === 'pending' && <button className="link-btn" onClick={onFixCrosses}>Use plain comparisons instead</button>}
        </div>
      )}
      {p.questions.length > 0 && (
        <div className="q-list">
          <div className="muted">Open questions (saved with the draft; answer before saving a version):</div>
          <ul>{p.questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
        </div>
      )}
      {p.review?.validation && !p.review.validation.ok && (
        <div className="checks">{p.review.validation.errors.filter(e => !e.includes('open question')).map((e, i) => <div key={i} className="check err">✕ {e}</div>)}</div>
      )}
      {p.status === 'pending' ? (
        <div className="proposal-actions">
          <button className="btn sm" onClick={onApply}>Apply</button>
          <button className="btn ghost sm" onClick={onDiscard}>Discard</button>
        </div>
      ) : (
        <div className="muted small">{p.status === 'applied' ? '✓ Applied to the rules' : 'Discarded'}</div>
      )}
    </div>
  )
}

export function Chat({ messages, proposals, busy, aiReady, aiDetail, draftText, setDraftText, onSend, onApply, onDiscard, onFixCrosses }: {
  messages: ChatMessage[]
  proposals: LiveProposal[]
  busy: boolean
  aiReady: boolean
  aiDetail: string
  draftText: string
  setDraftText: (s: string) => void
  onSend: (text: string) => void
  onApply: (p: LiveProposal) => void
  onDiscard: (p: LiveProposal) => void
  onFixCrosses: (p: LiveProposal) => void
}) {
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [messages.length, proposals.length, busy])
  useEffect(() => { if (draftText) inputRef.current?.focus() }, [draftText])

  const send = () => {
    const t = draftText.trim()
    if (!t || busy) return
    onSend(t)
  }

  return (
    <aside className="chat" aria-label="Conversation">
      <div className="chat-scroll">
        {messages.length === 0 && proposals.length === 0 && (
          <div className="chat-empty">
            <p>Describe the idea in your own words, or edit the rules directly. Ask for changes like:</p>
            <ul>
              <li>“make the stop loss 2%”</li>
              <li>“only buy when RSI is under 40 too”</li>
              <li>“use EMA instead of SMA”</li>
            </ul>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="bubble">{m.content}</div>
          </div>
        ))}
        {proposals.map(p => (
          <ProposalCard key={p.key} p={p}
            onApply={() => onApply(p)} onDiscard={() => onDiscard(p)} onFixCrosses={() => onFixCrosses(p)} />
        ))}
        {busy && <div className="msg assistant"><div className="bubble typing">Reading your idea<span>…</span></div></div>}
        <div ref={endRef} />
      </div>
      <div className="composer">
        {!aiReady && <div className="ai-off" role="status">AI unavailable: {aiDetail} You can still edit the rules directly.</div>}
        <textarea ref={inputRef} rows={3} value={draftText} placeholder={aiReady ? 'Describe or change the strategy…' : 'AI is offline'}
          disabled={!aiReady} aria-label="Message"
          onChange={e => setDraftText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
        <div className="composer-row">
          <span className="muted small">Enter to send · Shift+Enter for a new line</span>
          <button className="btn sm" onClick={send} disabled={busy || !aiReady || !draftText.trim()}>{busy ? 'Thinking…' : 'Send'}</button>
        </div>
      </div>
    </aside>
  )
}
