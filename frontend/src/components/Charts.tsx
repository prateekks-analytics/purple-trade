import { useEffect, useMemo, useRef, useState } from 'react'

export interface Bar { date: string; open: number; high: number; low: number; close: number; volume: number }
export interface TradeMark { date: string; price: number; kind: 'buy' | 'sell'; label: string }

/** Tiny trend line for tables and cards. Colour follows direction; the number beside it carries the value. */
export function Spark({ values, width = 96, height = 28, label }: { values: number[]; width?: number; height?: number; label: string }) {
  if (values.length < 2) return <span className="spark-empty" aria-hidden>—</span>
  const lo = Math.min(...values), hi = Math.max(...values)
  const span = hi - lo || 1
  const pts = values.map((v, i) => [(i / (values.length - 1)) * width, height - 2 - ((v - lo) / span) * (height - 4)])
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('')
  const up = values[values.length - 1] >= values[0]
  return (
    <svg className={`spark ${up ? 'up' : 'down'}`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      <path d={`${d}L${width},${height}L0,${height}Z`} className="spark-area" />
      <path d={d} className="spark-line" />
    </svg>
  )
}

export const RANGES = [['1M', 21], ['3M', 63], ['6M', 126], ['1Y', 252], ['All', 0]] as const
export type RangeKey = (typeof RANGES)[number][0]

export function RangeTabs({ value, onChange, total }: { value: RangeKey; onChange: (r: RangeKey) => void; total: number }) {
  return (
    <div className="range-tabs" role="group" aria-label="Chart period">
      {RANGES.map(([k, n]) => (
        <button key={k} type="button" aria-pressed={value === k} className={value === k ? 'on' : ''}
          disabled={n > 0 && n >= total} onClick={() => onChange(k)}>{k}</button>
      ))}
    </div>
  )
}

export function sliceRange<T>(rows: T[], r: RangeKey): T[] {
  const n = RANGES.find(x => x[0] === r)?.[1] ?? 0
  return n && rows.length > n ? rows.slice(-n) : rows
}

const PAD = { top: 10, right: 66, bottom: 24, left: 4 }
const fmt = (v: number) => v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function ticks(min: number, max: number, count = 5) {
  const step0 = (max - min || 1) / count
  const mag = 10 ** Math.floor(Math.log10(step0))
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0) ?? step0
  const out: number[] = []
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(8))
  return out
}

/** Candlestick price chart with volume and buy/sell markers. Hover or arrow keys read one day. */
export function CandleChart({ bars, marks = [], height = 360 }: { bars: Bar[]; marks?: TradeMark[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(800)
  const [hover, setHover] = useState<number | null>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(300, e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const n = bars.length
  const volH = Math.round(height * 0.18)
  const priceH = height - PAD.top - PAD.bottom - volH - 8
  const innerW = width - PAD.left - PAD.right
  const { lo, hi, vmax } = useMemo(() => {
    let lo = Infinity, hi = -Infinity, vmax = 0
    for (const b of bars) { lo = Math.min(lo, b.low); hi = Math.max(hi, b.high); vmax = Math.max(vmax, b.volume) }
    const pad = (hi - lo) * 0.06 || 1
    return { lo: lo - pad, hi: hi + pad, vmax: vmax || 1 }
  }, [bars])
  const slot = innerW / Math.max(n, 1)
  const bw = Math.max(1, Math.min(12, slot * 0.7))
  const x = (i: number) => PAD.left + slot * (i + 0.5)
  const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * priceH
  const vTop = PAD.top + priceH + 8
  const idx = useMemo(() => new Map(bars.map((b, i) => [b.date, i])), [bars])
  const shownMarks = marks.filter(m => idx.has(m.date))
  const dateTicks = useMemo(() => {
    const k = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(innerW / 110))))
    return bars.map((b, i) => ({ b, i })).filter(({ i }) => i % k === 0 && slot * (i + 0.5) > 24 && i < n - k / 3)
  }, [bars, n, innerW, slot])

  const onMove = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect()
    const i = Math.floor((e.clientX - r.left - PAD.left) / slot)
    setHover(Math.max(0, Math.min(n - 1, i)))
  }
  const onKey = (e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 10 : 1
    if (e.key === 'ArrowRight') setHover(h => Math.min(n - 1, (h ?? -1) + step))
    else if (e.key === 'ArrowLeft') setHover(h => Math.max(0, (h ?? n) - step))
    else if (e.key === 'Escape') setHover(null)
    else return
    e.preventDefault()
  }
  const cur = bars[hover ?? n - 1]
  const prev = bars[(hover ?? n - 1) - 1]
  const chg = cur && prev ? (cur.close / prev.close - 1) * 100 : 0
  const markAt = hover !== null ? shownMarks.filter(m => m.date === bars[hover].date) : []

  return (
    <div className="candle" ref={ref}>
      {cur && (
        <div className="ohlc" aria-live="off">
          <span className="ohlc-date">{cur.date}</span>
          <span>O <b>{fmt(cur.open)}</b></span><span>H <b>{fmt(cur.high)}</b></span>
          <span>L <b>{fmt(cur.low)}</b></span><span>C <b>{fmt(cur.close)}</b></span>
          <span className={chg >= 0 ? 'pos' : 'neg'}>{chg >= 0 ? '+' : ''}{chg.toFixed(2)}%</span>
          {cur.volume > 0 && <span>Vol <b>{cur.volume.toLocaleString('en-IN')}</b></span>}
        </div>
      )}
      <svg width={width} height={height} role="group" aria-roledescription="chart" tabIndex={0}
        aria-label="Daily candlestick price chart with volume and trade markers. Use the left and right arrow keys to read each day."
        onPointerMove={onMove} onPointerLeave={() => setHover(null)} onKeyDown={onKey} onBlur={() => setHover(null)}>
        {ticks(lo, hi).map(t => (
          <g key={t}>
            <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} className="grid" />
            <text x={width - PAD.right + 8} y={y(t) + 4} className="axis">{t.toLocaleString('en-IN')}</text>
          </g>
        ))}
        {dateTicks.map(({ b, i }) => (
          <text key={b.date} x={x(i)} y={height - 6} className="axis" textAnchor="middle">{b.date.slice(2, 7).replace('-', '/')}</text>
        ))}
        {bars.map((b, i) => {
          const up = b.close >= b.open
          const top = y(Math.max(b.open, b.close)), bot = y(Math.min(b.open, b.close))
          const vh = (b.volume / vmax) * volH
          return (
            <g key={b.date} className={up ? 'c-up' : 'c-down'}>
              <line x1={x(i)} x2={x(i)} y1={y(b.high)} y2={y(b.low)} className="wick" />
              <rect x={x(i) - bw / 2} y={top} width={bw} height={Math.max(1, bot - top)} className="body" />
              {b.volume > 0 && <rect x={x(i) - bw / 2} y={vTop + volH - vh} width={bw} height={vh} className="vol" />}
            </g>
          )
        })}
        {shownMarks.map((m, k) => {
          const i = idx.get(m.date)!
          const cx = x(i)
          const pts = m.kind === 'buy'
            ? `${cx},${y(bars[i].low) + 4} ${cx - 6},${y(bars[i].low) + 15} ${cx + 6},${y(bars[i].low) + 15}`
            : `${cx},${y(bars[i].high) - 4} ${cx - 6},${y(bars[i].high) - 15} ${cx + 6},${y(bars[i].high) - 15}`
          return <polygon key={k} points={pts} className={`mark ${m.kind}`} />
        })}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={vTop + volH} className="crosshair" />}
        {cur && <g>
          <rect x={width - PAD.right + 2} y={y(cur.close) - 10} width={PAD.right - 4} height={20} rx={3} className="last-tag" />
          <text x={width - PAD.right + 8} y={y(cur.close) + 4} className="last-text">{fmt(cur.close)}</text>
        </g>}
      </svg>
      {markAt.length > 0 && (
        <div className="mark-note" role="status">
          {markAt.map((m, k) => <div key={k} className={m.kind}>{m.kind === 'buy' ? '▲ Bought' : '▼ Sold'}: {m.label}</div>)}
        </div>
      )}
    </div>
  )
}
