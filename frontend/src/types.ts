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

export interface TaEngine {
  id: string
  label: string
  paid: boolean
  note: string
  minutes: [number, number]
  cost_per_day: [number, number] | null
  available: boolean
  why: string
}

export interface SuperAgentInfo {
  id: string
  kind: 'ai-agent' | 'ai-team' | 'ta-original' | 'ai-news' | 'ai-crew' | 'rules' | 'research'
  title: string
  tagline: string
  source: { name: string; url: string }
  fidelity: string
  analyses: Analysis[]
  available: boolean
  speed: string
  engines?: TaEngine[]
  strategy?: Strategy
  describe?: NonNullable<Review['describe']>
  hidden?: boolean
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
  /** Purple Research Agent only */
  view?: 'BUY' | 'SELL' | 'HOLD'
  risks?: string
  steps?: { market?: string; news?: string; social?: string; tone?: string; items?: number; fundamentals?: string; health?: string }
  risk_plan?: RiskPlan | null
}

export interface RiskPlan { close: number; atr: number; stop: number; target: number; stop_pct: number; target_pct: number }

/** One Buy / Hold / Sell call on the latest completed session. */
export interface AgentCall {
  agent: { id: string; title: string; kind: SuperAgentInfo['kind'] }
  symbol: string; name: string; date: string; close: number; holding: boolean; analyses: string[]
  quote: Quote | null; model: string; cached: boolean
  decision: Omit<TeamDecision, 'date' | 'close'>
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
  interval?: string
}

export interface PaperView {
  account: PaperAccount
  agent: { id: string; title: string; kind: SuperAgentInfo['kind'] }
  latest_date: string
  interval?: string
  data_note: string
  pending_days: string[]
  can_refresh?: boolean
  today: { date: string; action: 'BUY' | 'SELL' | 'HOLD' | null; reason: string }
  decisions: TeamDecision[]
  result: BacktestResult
}

export interface Quote {
  ticker: string; name?: string | null; currency: string | null; price: number; prev_close: number | null; change_pct: number | null
  time: string | null; session_open: boolean; source: string
}

export interface MarketStatus {
  feed: string; calls_last_hour: number; rate_limited: boolean; retry_in_s: number
  last_error: string | null; last_error_at: string | null; session: 'open' | 'closed' | 'after'
  feeds: { id: string; label: string; connected: boolean; delay: string; cost: string; note: string }[]
  loop: { last_tick: string | null; last_error: string | null; bars_saved: number; ai_decisions: number; intraday_accounts: number; background_ai: boolean }
}

export interface Health { hosted?: boolean; ok: boolean; ai: { provider: string; model: string; available: boolean; detail: string } }

export interface AiProvider { id: string; label: string; cost: string; key_url: string; default_model: string; needs_key: boolean }

// ----- beat the market -----
export interface ChallengeWeek {
  start: string
  end: string
  bot_pct: number
  market_pct: number
  edge_rupees: number
  beat: boolean
  trades: number
  in_market: boolean
}

export interface ChallengeSummary {
  weeks: number
  beat: number
  avg_edge: number
  total_edge: number
  idle_weeks?: number
  cash_beat?: number
  capital?: number
  verdict: string
}

export interface ChallengeCard {
  weeks: ChallengeWeek[]
  summary: ChallengeSummary
  learn: ChallengeSummary
  unseen: ChallengeSummary
  describe: { entry: string; exit: string }
  strategy: Strategy
  symbol: string
  market: string
  week_sessions: number
}

export interface CoachTry { change: string; beat: number; weeks: number; unseen_beat: number; unseen_weeks: number }
export interface CoachResult { before: ChallengeCard; after: ChallengeCard | null; tries: CoachTry[] }

export interface Race {
  id: string
  name: string
  agent: { id: string; title: string; kind: string }
  symbol: string
  start: string
  days: number
  day: number
  finished: boolean
  capital: number
  bot_value: number
  market_value: number | null
  edge: number | null
  headline: string
  series: { date: string; bot: number; market: number | null }[]
  live_at: string | null
  today: { date: string; action: 'BUY' | 'SELL' | 'HOLD' | null; reason: string }
  holding: { qty: number; since: string; price: number } | null
  trades: { entry_date: string; exit_date: string | null; entry_price: number; exit_price: number | null; qty: number; pnl: number; exit_reason: string }[]
}

// ----- the portfolio bot (desk) -----
export interface DeskAgent { id: string; name: string; style: string; team?: string; record_pct?: number | null; wins?: number; proposal?: Record<string, number> }
export interface DeskTrade { time: string; symbol: string; side: 'BUY' | 'SELL'; qty: number; price: number; value: number; why: string }
export interface DeskHolding { symbol: string; qty: number; price: number; value: number; avg: number | null }
export interface DeskDecision {
  time: string
  winner: string
  winner_name: string
  reason: string
  by: string | null
  targets: Record<string, number>
  debate: { agent: string; name: string; case: string }[]
  confidence: number | null
  rules_used?: string[]
  uses?: string[]
}
export interface CoachStat { n: number; days: number; edge_pct: number | null }
export interface CoachRule {
  id: string
  text: string
  why: string
  added: string
  status: 'active' | 'trial' | 'retired'
  score?: { followed: CoachStat; not_followed: CoachStat; verdict: 'too early' | 'helping' | 'hurting' | 'no clear effect' } | null
}
export interface DeskCoach { rules: CoachRule[] }
export interface JournalItem { label: string; text: string }
export interface JournalEntry { date: string; day: string; summary: string | null; items: JournalItem[] }
export interface DayCosts {
  charges: { stt: number; stamp: number; exchange: number; sebi: number; gst: number; dp: number; brokerage: number }
  charges_total: number; turnover: number; intraday_value: number; delivery_value: number
  short_term_gain: number; intraday_gain: number; tax: number; total: number
}
export interface ReportCard {
  id: string; name: string; team: string; today_pct: number | null; since_start_pct: number | null
  trades_today: number; costs_today: number; led_today: number; used_today: number
  grade: 'strong' | 'average' | 'weak' | null; trust: 'more' | 'same' | 'less' | null; why: string
}
export interface CoachReport {
  day: string; bot_id: string; capital: number; headline: string; story: string
  numbers: { desk_pct: number | null; nifty_pct: number | null; twin_pct: number | null; company_rupees: number | null
    company_since_start_pct: number | null; nifty_since_start_pct: number | null; trades: number; decisions: number; by_ai: number; day_complete: boolean }
  costs: { day: DayCosts | null; since_start: { total: number } | null; switch_pct: number; note: string }
  cards: ReportCard[]
  advice_check: { rule: string; followed: string; helped: 'yes' | 'no' | 'too early'; note: string }[]
  rule_changes: string[]
  ideas: { title: string; detail: string; who: 'coach' | 'owner'; expected: string }[]
  watch: string
}
export interface DeskBot { id: string; name: string; capital: number; days: number; start_time: string; status: 'running' | 'stopped' | 'finished'; created_at: string }
export interface DeskView {
  bot: DeskBot | null
  agents: DeskAgent[]
  universe: string[]
  value?: number
  cash?: number
  capital?: number
  return_pct?: number
  market_pct?: number
  edge?: number
  day?: number
  series?: { time: string; value: number; market: number }[]
  trades?: DeskTrade[]
  holdings?: DeskHolding[]
  decisions?: DeskDecision[]
  mood?: { time: string; scores: Record<string, { score: number; why: string }> } | null
  lessons?: string[]
  data_time?: string
  next_decision?: string | null
  ai?: boolean
  last_error?: string | null
  market_name?: string
  coach?: DeskCoach
  guard?: { time: string; kind: 'market' | 'stock'; reason: string }[]
  twin?: { value: number; return_pct: number; edge: number } | null
  core?: { on: boolean; picks: string[]; gap_pct: number | null; refreshed: string | null; pool: number }
}
export interface DeskBacktest {
  from: string
  to: string
  capital: number
  return_pct: number
  market_pct: number
  edge: number
  trades: number
  series: { time: string; value: number; market: number }[]
  weeks: { start: string; end: string; bot_pct: number; market_pct: number; edge: number; beat: boolean }[]
  weeks_beat: number
  agents: { id: string; name: string; return_pct: number; picked: number }[]
  note: string
}
