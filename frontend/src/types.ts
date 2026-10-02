export type PriceField = 'open' | 'high' | 'low' | 'close' | 'volume'
export type IndicatorName = 'sma' | 'ema' | 'rsi' | 'highest' | 'lowest'
export type CompareOp = '<' | '<=' | '==' | '!=' | '>=' | '>'

export type Operand =
  | { kind: 'price'; field: PriceField; offset: number }
  | { kind: 'indicator'; name: IndicatorName; period: number; source: PriceField; offset: number }
  | { kind: 'const'; value: number }
  | { kind: 'position'; field: 'bars_held' | 'pnl_pct' }

export type Condition =
  | { kind: 'compare'; left: Operand; op: CompareOp; right: Operand }
  | { kind: 'cross'; left: Operand; direction: 'above' | 'below'; right: Operand }
  | { kind: 'all'; items: Condition[] }
  | { kind: 'any'; items: Condition[] }
  | { kind: 'not'; item: Condition }

export interface Strategy {
  name: string
  entry: Condition
  exit: Condition
  sizing: { mode: 'percent_equity'; value: number }
  costs: { fee_bps: number; slippage_bps: number }
  initial_capital: number
  questions: string[]
}

export interface Review {
  valid_shape: boolean
  shape_errors?: string[]
  strategy?: Strategy
  describe?: { entry: string; exit: string; entry_lines: string[]; exit_lines: string[]; execution: string }
  validation?: { ok: boolean; errors: string[]; warnings: string[]; warmup_bars: number }
  hash?: string
}

export interface VersionMeta { id: string; number: number; hash: string; created_at: string }

export interface ChatMessage { role: 'user' | 'assistant'; content: string; at?: string; proposal?: boolean }

export interface StrategyDoc {
  id: string
  name: string
  created_at: string
  updated_at: string
  draft: Strategy | null
  chat: ChatMessage[]
  versions: VersionMeta[]
  review: Review | null
  source: AgentSource | null
}

export interface AgentSource { filename: string; kind: 'purple-json' | 'code' | 'document'; content: string; created_at: string }

export interface AgentImport { mode: 'exact' | 'ai'; strategy: StrategyDoc; proposal: Proposal | null }

export interface StrategySummary { id: string; name: string; updated_at: string; versions: number }

export interface Proposal {
  ok: boolean
  strategy: Strategy | null
  questions: string[]
  notes: string
  error: string | null
  fidelity: string[]
  attempts: number
  provider: string
  model: string
  review?: Review
}

export interface Dataset {
  id: string
  name: string
  symbol: string | null
  source_note: string | null
  rows: number
  first_date: string
  last_date: string
  hash: string
  synthetic: number
  warnings?: string[]
}

export interface Trade {
  entry_date: string
  entry_price: number
  exit_date: string | null
  exit_price: number | null
  qty: number
  pnl: number
  pnl_pct: number
  bars_held: number
  entry_reason: string
  exit_reason: string
  fees: number
  open: boolean
}

export interface Metrics {
  start_equity: number
  end_equity: number
  total_return_pct: number
  cagr_pct: number | null
  buy_hold_return_pct: number
  max_drawdown_pct: number
  trades: number
  win_rate_pct: number | null
  avg_trade_pct: number | null
  profit_factor: number | null
  exposure_pct: number
  fees_paid: number
  bars: number
  first_date: string
  last_date: string
}

export interface BacktestResult {
  id: string
  engine: string
  mode: 'draft' | 'approved'
  metrics: Metrics
  trades: Trade[]
  equity: { date: string; equity: number; close: number }[]
  warmup_bars: number
  strategy_hash: string
  data_hash: string
  dataset: Dataset
  describe: NonNullable<Review['describe']>
}

export interface Template { id: string; title: string; blurb: string; strategy: Partial<Strategy>; review: Review }

export interface Analysis { id: string; label: string; available: boolean; detail: string }

export interface SuperAgentInfo {
  id: string
  kind: 'ai-team' | 'ta-original' | 'rules' | 'research'
  title: string
  tagline: string
  source: { name: string; url: string }
  fidelity: string
  analyses: Analysis[]
  available: boolean
  speed: string
  strategy?: Strategy
  describe?: NonNullable<Review['describe']>
}

export interface TeamDecision {
  date: string
  close: number
  action: 'BUY' | 'SELL' | 'HOLD'
  confidence: number
  rating?: string
  reason: string
  bull: string
  bear: string
  notes: string[]
  report: string
}

export type TeamResult = BacktestResult & { decisions: TeamDecision[] }

export interface Job<R = unknown> {
  id: string
  status: 'running' | 'done' | 'error'
  done: number
  total: number
  log: { kind: string; text: string; date: string | null }[]
  result: R | null
  error: string | null
}

export type RunResponse =
  | { kind: 'rules'; result: BacktestResult; strategy: Strategy }
  | { kind: 'job'; job: Job<TeamResult> }

export interface PaperAccount {
  id: string; name: string; agent_id: string; dataset_id: string; symbol: string | null
  synthetic: number; start_date: string; sim_days: number; capital: number; created_at: string
}

export interface PaperView {
  account: PaperAccount
  agent: { id: string; title: string; kind: SuperAgentInfo['kind'] }
  latest_date: string
  data_note: string
  pending_days: string[]
  can_refresh?: boolean
  today: { date: string; action: 'BUY' | 'SELL' | 'HOLD' | null; reason: string }
  decisions: TeamDecision[]
  result: BacktestResult
}

export interface Health { ok: boolean; ai: { provider: string; model: string; available: boolean; detail: string } }
