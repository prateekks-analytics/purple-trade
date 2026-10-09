import type { BacktestResult } from '../types'
import { fmtMoney, fmtPct } from './tree'

/** Largest fall from a running peak, in percent (negative or 0). */
export function maxDrawdown(values: number[]): number {
  let peak = -Infinity, worst = 0
  for (const v of values) {
    peak = Math.max(peak, v)
    if (peak > 0) worst = Math.min(worst, (v / peak - 1) * 100)
  }
  return worst
}

const pts = (v: number) => `${Math.abs(v).toFixed(1)} percentage point${Math.abs(v).toFixed(1) === '1.0' ? '' : 's'}`

export interface Fact { label: string; value: string; tone?: 'pos' | 'neg'; note: string }

export interface Verdict {
  outcome: 'beat' | 'lagged' | 'matched' | 'idle'
  headline: string
  money: string
  facts: Fact[]
  meaning: string[]
}

/** Plain-English reading of a backtest. Every sentence is derived from the numbers, never from AI text. */
export function readVerdict(r: BacktestResult, bot: string, stock: string): Verdict {
  const m = r.metrics
  const diff = m.total_return_pct - m.buy_hold_return_pct
  const bhEnd = m.start_equity * (1 + m.buy_hold_return_pct / 100)
  const bhDD = maxDrawdown(r.equity.map(e => e.close))
  const open = r.trades.find(t => t.open)
  const idle = m.trades === 0 && !open
  const outcome = idle ? 'idle' : Math.abs(diff) < 0.5 ? 'matched' : diff > 0 ? 'beat' : 'lagged'

  const headline = outcome === 'idle'
    ? `${bot} never bought ${stock} in this period, so the money stayed in cash.`
    : outcome === 'matched'
    ? `${bot} roughly matched simply holding ${stock}.`
    : outcome === 'beat'
      ? `${bot} beat simply holding ${stock} by ${pts(diff)}.`
      : `${bot} trailed simply holding ${stock} by ${pts(diff)}.`
  const money = `${fmtMoney(m.start_equity)} became ${fmtMoney(m.end_equity)} (${fmtPct(m.total_return_pct)}) between ${m.first_date} and ${m.last_date}. `
    + `Buying on the first day and holding would have ended at ${fmtMoney(bhEnd)} (${fmtPct(m.buy_hold_return_pct)}).`

  const tone = (v: number) => (v > 0 ? 'pos' : v < 0 ? 'neg' : undefined) as Fact['tone']
  const facts: Fact[] = [
    { label: 'Return', value: fmtPct(m.total_return_pct), tone: tone(m.total_return_pct), note: `Holding the stock: ${fmtPct(m.buy_hold_return_pct)}` },
    { label: 'Worst drop', value: fmtPct(m.max_drawdown_pct), tone: m.max_drawdown_pct < 0 ? 'neg' : undefined,
      note: `Holding the stock: ${fmtPct(bhDD)}. The biggest fall from a previous high.` },
    { label: 'Completed trades', value: String(m.trades),
      note: m.win_rate_pct === null ? (open ? 'One trade is still open.' : 'No trade was completed.')
        : `${m.win_rate_pct.toFixed(0)}% made money${open ? ', plus one still open' : ''}.` },
    { label: 'Time invested', value: `${m.exposure_pct.toFixed(0)}%`, note: 'Share of days it held shares rather than cash.' },
  ]

  const meaning: string[] = []
  if (idle) meaning.push(`Its buy rule never matched on these prices, so there is nothing to judge. Holding the stock would have returned ${fmtPct(m.buy_hold_return_pct)}. Try a longer period or a different stock.`)
  else if (m.trades < 5) meaning.push(`Only ${m.trades} completed trade${m.trades === 1 ? '' : 's'}. That is too few to tell a good rule from luck.`)
  if (outcome === 'beat' && m.total_return_pct < 0)
    meaning.push(`It still lost money (${fmtPct(m.total_return_pct)}). Beating a falling stock means losing less, not making a profit.`)
  if (m.bars < 250) meaning.push('The test covers less than a year of prices, so a single market phase can decide the result.')
  if (outcome === 'lagged' && m.max_drawdown_pct > bhDD + 1)
    meaning.push(`It earned less than holding but also fell less at its worst (${fmtPct(m.max_drawdown_pct)} against ${fmtPct(bhDD)}): a trade of return for a smoother ride.`)
  if (outcome === 'lagged' && m.max_drawdown_pct <= bhDD + 1)
    meaning.push(`It earned less than holding and fell at least as far at its worst (${fmtPct(m.max_drawdown_pct)} against ${fmtPct(bhDD)}). On this data, simply holding was better on both counts.`)
  if (outcome === 'beat' && m.max_drawdown_pct < bhDD - 1)
    meaning.push(`The extra return came with deeper falls than holding (${fmtPct(m.max_drawdown_pct)} against ${fmtPct(bhDD)}).`)
  if (outcome === 'beat' && m.max_drawdown_pct >= bhDD - 1 && m.trades >= 5)
    meaning.push('It earned more than holding without deeper falls. Check that it holds on other stocks and periods before trusting it.')
  if (r.dataset.synthetic) meaning.push('These prices are synthetic, made for trying the app. Import real NSE prices before drawing conclusions.')
  meaning.push('A backtest shows how the rules would have behaved in the past. It does not predict future returns.')

  return { outcome, headline, money, facts, meaning }
}
