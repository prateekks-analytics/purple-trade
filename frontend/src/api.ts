import type {
  AgentImport, AiProvider, BacktestResult, Dataset, Health, Job, PaperAccount, PaperView, Proposal, Review, RunResponse, Strategy,
  StrategyDoc, StrategySummary, SuperAgentInfo, Template,
} from './types'
import { aiHeaders } from './lib/aiSettings'

export class ApiError extends Error {
  status: number
  details: string[]
  constructor(status: number, message: string, details: string[] = []) {
    super(message)
    this.status = status
    this.details = details
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { cache: 'no-store', ...init, headers: { ...aiHeaders(), ...(init?.headers ?? {}) } })
  } catch {
    throw new ApiError(0, 'Cannot reach the Purple Trade server. Is it running?')
  }
  const text = await res.text()
  const body = text ? JSON.parse(text) : null
  if (!res.ok) {
    const d = body?.detail
    const details: string[] = Array.isArray(d?.errors) ? d.errors : Array.isArray(d?.shape_errors) ? d.shape_errors : []
    const msg = typeof d === 'string' ? d : details[0] ?? `Request failed (${res.status})`
    throw new ApiError(res.status, msg, details)
  }
  return body as T
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

export const api = {
  health: () => req<Health>('/api/health'),
  aiProviders: () => req<AiProvider[]>('/api/ai/providers'),
  aiTest: (provider: string, key: string) => req<{ ok: boolean; models: string[] }>('/api/ai/test', json('POST', { provider, key })),
  templates: () => req<Template[]>('/api/templates'),
  listStrategies: () => req<StrategySummary[]>('/api/strategies'),
  createStrategy: (name = 'Untitled strategy', template_id?: string) =>
    req<StrategyDoc>('/api/strategies', json('POST', { name, template_id })),
  getStrategy: (id: string) => req<StrategyDoc>(`/api/strategies/${id}`),
  deleteStrategy: (id: string) => req<{ ok: boolean }>(`/api/strategies/${id}`, json('DELETE')),
  saveDraft: (id: string, s: Strategy) => req<StrategyDoc>(`/api/strategies/${id}/draft`, json('PUT', s)),
  review: (s: Strategy) => req<Review>('/api/review', json('POST', s)),
  propose: (id: string, message: string) => req<Proposal>(`/api/strategies/${id}/ai`, json('POST', { message })),
  approve: (id: string) => req<StrategyDoc>(`/api/strategies/${id}/approve`, json('POST')),
  getVersion: (id: string) => req<{ id: string; number: number; body: Strategy; review: Review }>(`/api/versions/${id}`),
  datasets: () => req<Dataset[]>('/api/datasets'),
  datasetBars: (id: string) => req<{ date: string; open: number; high: number; low: number; close: number; volume: number }[]>(`/api/datasets/${id}/bars`),
  uploadDataset: (file: File, symbol: string, sourceNote: string) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('symbol', symbol)
    fd.append('source_note', sourceNote)
    return req<Dataset>('/api/datasets', { method: 'POST', body: fd })
  },
  importAgent: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return req<AgentImport>('/api/agents/import', { method: 'POST', body: fd })
  },
  exportStrategy: (id: string, versionId?: string | null) =>
    req<{ format: string; version: number; strategy: Strategy }>(
      `/api/strategies/${id}/export${versionId ? `?version_id=${versionId}` : ''}`),
  backtest: (strategy_id: string, dataset_id: string, version_id?: string) =>
    req<BacktestResult>('/api/backtests', json('POST', { strategy_id, dataset_id, version_id: version_id ?? null })),

  // ----- Trading SuperAgent -----
  saAgents: () => req<SuperAgentInfo[]>('/api/superagent/agents'),
  saRun: (agent_id: string, dataset_id: string | null, days: number, analyses: string[], symbol?: string, engine = 'local', confirm_paid = false) =>
    req<RunResponse>('/api/superagent/run', json('POST', { agent_id, dataset_id, days, analyses, symbol, engine, confirm_paid })),
  saJob: <R,>(id: string) => req<Job<R>>(`/api/superagent/jobs/${id}`),
  saPaperList: () => req<PaperAccount[]>('/api/superagent/paper'),
  saPaperCreate: (agent_id: string, dataset_id: string | null, capital: number, analyses: string[], symbol?: string) =>
    req<PaperView>('/api/superagent/paper', json('POST', { agent_id, dataset_id, capital, analyses, symbol })),
  saPaperRefresh: (id: string) => req<PaperView>(`/api/superagent/paper/${id}/refresh`, json('POST')),
  saPaper: (id: string) => req<PaperView>(`/api/superagent/paper/${id}`),
  saPaperNextDay: (id: string) => req<PaperView>(`/api/superagent/paper/${id}/next-day`, json('POST')),
  saPaperDecide: (id: string) => req<{ kind: 'job'; job: Job }>(`/api/superagent/paper/${id}/decide`, json('POST')),
  saPaperDelete: (id: string) => req<{ ok: boolean }>(`/api/superagent/paper/${id}`, json('DELETE')),
  saExport: (agent_id: string, symbol: string) =>
    req<{ filename: string; code: string }>(`/api/superagent/export?agent_id=${encodeURIComponent(agent_id)}&symbol=${encodeURIComponent(symbol)}`),
}
