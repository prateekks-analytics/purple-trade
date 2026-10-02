import type {
  BacktestResult, Dataset, Health, Proposal, Review, Strategy, StrategyDoc, StrategySummary, Template,
} from './types'

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
    res = await fetch(path, init)
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
  uploadDataset: (file: File, symbol: string, sourceNote: string) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('symbol', symbol)
    fd.append('source_note', sourceNote)
    return req<Dataset>('/api/datasets', { method: 'POST', body: fd })
  },
  backtest: (strategy_id: string, dataset_id: string, version_id?: string) =>
    req<BacktestResult>('/api/backtests', json('POST', { strategy_id, dataset_id, version_id: version_id ?? null })),
}
