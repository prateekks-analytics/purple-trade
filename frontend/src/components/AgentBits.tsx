import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { Job, TeamDecision } from '../types'

export const errText = (e: unknown) => (e instanceof ApiError ? (e.details.length ? e.details.join(' ') : e.message) : String(e))

/** Polls a background job until it finishes. */
export function useJob<R>(job: Job<R> | null, onFinish?: (j: Job<R>) => void) {
  const [state, setState] = useState<Job<R> | null>(job)
  const fin = useRef(onFinish)
  fin.current = onFinish
  useEffect(() => {
    setState(job)
    if (!job || job.status !== 'running') { if (job) fin.current?.(job); return }
    let stop = false
    const tick = async () => {
      try {
        const j = await api.saJob<R>(job.id)
        if (stop) return
        setState(j)
        if (j.status === 'running') setTimeout(tick, 1200)
        else fin.current?.(j)
      } catch (e) { if (!stop) setState({ ...job, status: 'error', error: errText(e) }) }
    }
    tick()
    return () => { stop = true }
  }, [job])
  return state
}

const WHO: Record<string, string> = { analyst: 'Market analyst', bull: 'Bull researcher', bear: 'Bear researcher', manager: 'Trader and risk manager', note: 'Check' }

export function JobProgress({ job, label, note }: { job: Job; label: string; note?: string }) {
  const pct = job.total ? Math.round((job.done / job.total) * 100) : 100
  return (
    <div className="job" aria-live="polite">
      <div className="job-head">
        <b>{label}</b>
        <span>Trading day {Math.min(job.done + 1, job.total)} of {job.total}</span>
      </div>
      <div className="job-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}><i style={{ width: `${pct}%` }} /></div>
      {note && <p className="field-note">{note}</p>}
      <ul className="job-feed">
        {job.log.slice(-4).map((l, i) => (
          <li key={i}><b>{WHO[l.kind] ?? l.kind}</b>{l.date && <span className="sub"> {l.date}</span>}: {l.kind === 'analyst' ? l.text.split('\n')[0] : l.text}</li>
        ))}
      </ul>
    </div>
  )
}

type Decision = Pick<TeamDecision, 'date' | 'action' | 'confidence' | 'rating' | 'reason' | 'bull' | 'bear' | 'report'>

export function DecisionLog({ decisions }: { decisions: Decision[] }) {
  return (
    <ol className="decisions">
      {decisions.map(d => (
        <li key={d.date}>
          <div className="decision-head">
            <span className="date">{d.date}</span>
            <span className={`call ${d.action.toLowerCase()}`}>{d.action === 'BUY' ? 'Buy' : d.action === 'SELL' ? 'Sell' : 'Hold'}</span>
            <span className="sub">{d.rating ? `Rated ${d.rating}` : `${Math.round(d.confidence * 100)}% confident`}</span>
          </div>
          <p>{d.reason || 'No reason given.'}</p>
          {(d.bull || d.bear || d.report) && (
            <details>
              <summary>Read the bull and bear arguments and the market report</summary>
              <div className="debate">
                <div><b>Bull case</b><p>{d.bull}</p></div>
                <div><b>Bear case</b><p>{d.bear}</p></div>
              </div>
              <pre className="report">{d.report}</pre>
            </details>
          )}
        </li>
      ))}
    </ol>
  )
}

/** Downloads a standalone Python file for a bot. It prints signals only (DRY_RUN) until the user adds broker keys. */
export function DownloadCode({ agentId, symbol }: { agentId: string; symbol: string }) {
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const go = async () => {
    setBusy(true); setErr(null)
    try {
      const out = await api.saExport(agentId, symbol || 'INFY')
      const url = URL.createObjectURL(new Blob([out.code], { type: 'text/x-python' }))
      const a = document.createElement('a')
      a.href = url; a.download = out.filename; a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) { setErr(errText(e)) } finally { setBusy(false) }
  }
  return (
    <span className="download-code">
      <button className="link-btn" onClick={go} disabled={busy}>{busy ? 'Preparing…' : 'Download code'}</button>
      <span className="sub"> Python file that prints the day's signal. It places no orders unless you edit it and add your own broker keys.</span>
      {err && <span className="error-text"> {err}</span>}
    </span>
  )
}
