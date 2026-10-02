import { useEffect, useMemo, useRef, useState } from 'react'

export interface Series { key: string; label: string; color: string; values: number[]; dashed?: boolean }
export interface Marker { index: number; value: number; kind: 'buy' | 'sell'; label: string }

interface Props {
  dates: string[]
  series: Series[]
  markers?: Marker[]
  height?: number
  format: (v: number) => string
  ariaLabel: string
  baseline?: number
}

const PAD = { top: 12, right: 64, bottom: 26, left: 8 }

function niceTicks(min: number, max: number, count = 4) {
  const span = max - min || Math.abs(max) || 1
  const step0 = span / count
  const mag = 10 ** Math.floor(Math.log10(step0))
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0) ?? step0
  const start = Math.ceil(min / step) * step
  const out: number[] = []
  for (let v = start; v <= max + 1e-9; v += step) out.push(+v.toFixed(10))
  return out
}

export function LineChart({ dates, series, markers = [], height = 240, format, ariaLabel, baseline }: Props) {
  const ref = useRef<SVGSVGElement>(null)
  const [hover, setHover] = useState<number | null>(null)
  const [width, setWidth] = useState(720)
  const n = dates.length

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(280, e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const { min, max } = useMemo(() => {
    let lo = Infinity, hi = -Infinity
    for (const s of series) for (const v of s.values) { lo = Math.min(lo, v); hi = Math.max(hi, v) }
    if (baseline !== undefined) { lo = Math.min(lo, baseline); hi = Math.max(hi, baseline) }
    const pad = (hi - lo) * 0.06 || 1
    return { min: lo - pad, max: hi + pad }
  }, [series, baseline])

  const innerW = width - PAD.left - PAD.right
  const innerH = height - PAD.top - PAD.bottom
  const x = (i: number) => PAD.left + (n <= 1 ? 0 : (i / (n - 1)) * innerW)
  const y = (v: number) => PAD.top + (1 - (v - min) / (max - min)) * innerH
  const ticks = niceTicks(min, max)

  const path = (vals: number[]) => {
    let d = ''
    vals.forEach((v, i) => { d += `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}` })
    return d
  }

  const dateTicks = useMemo(() => {
    const k = Math.max(1, Math.floor(n / 6))
    return dates.map((d, i) => ({ d, i })).filter(({ i }) => i % k === 0 && i < n - k / 2)
  }, [dates, n])

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const svg = ref.current
    if (!svg || n === 0) return
    const rect = svg.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * width
    const i = Math.round(((px - PAD.left) / innerW) * (n - 1))
    setHover(Math.max(0, Math.min(n - 1, i)))
  }

  const markersAtHover = hover === null ? [] : markers.filter(m => m.index === hover)
  const tipLeft = hover !== null && x(hover) > width * 0.6

  return (
    <div className="chart" style={{ height }}>
      <svg ref={ref} role="img" aria-label={ariaLabel} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none"
        width="100%" height={height}
        onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        {ticks.map(t => (
          <g key={t}>
            <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} className="grid" />
            <text x={width - PAD.right + 6} y={y(t) + 4} className="axis-label">{format(t)}</text>
          </g>
        ))}
        {baseline !== undefined && (
          <line x1={PAD.left} x2={width - PAD.right} y1={y(baseline)} y2={y(baseline)} className="baseline" />
        )}
        {dateTicks.map(({ d, i }) => (
          <text key={d} x={x(i)} y={height - 8} className="axis-label" textAnchor="middle">{d.slice(0, 7)}</text>
        ))}
        {series.map(s => (
          <path key={s.key} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2}
            strokeDasharray={s.dashed ? '5 4' : undefined} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {markers.map((m, k) => {
          const cx = x(m.index), cy = y(m.value)
          const pts = m.kind === 'buy'
            ? `${cx},${cy + 3} ${cx - 6},${cy + 13} ${cx + 6},${cy + 13}`
            : `${cx},${cy - 3} ${cx - 6},${cy - 13} ${cx + 6},${cy - 13}`
          return <polygon key={k} points={pts} className={`marker ${m.kind}`} />
        })}
        {hover !== null && (
          <g pointerEvents="none">
            <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={height - PAD.bottom} className="crosshair" />
            {series.map(s => (
              <circle key={s.key} cx={x(hover)} cy={y(s.values[hover])} r={4} fill={s.color} className="dot" />
            ))}
          </g>
        )}
      </svg>
      {series.length > 1 && (
        <div className="legend" aria-hidden>
          {series.map(s => (
            <span key={s.key}><i style={{ background: s.color }} className={s.dashed ? 'dashed' : ''} />{s.label}</span>
          ))}
        </div>
      )}
      {hover !== null && (
        <div className="tooltip" style={tipLeft ? { right: `${((width - x(hover)) / width) * 100 + 2}%` } : { left: `${(x(hover) / width) * 100 + 2}%` }}>
          <div className="tt-date">{dates[hover]}</div>
          {series.map(s => (
            <div key={s.key} className="tt-row"><i style={{ background: s.color }} />{s.label}<b>{format(s.values[hover])}</b></div>
          ))}
          {markersAtHover.map((m, k) => (
            <div key={k} className={`tt-event ${m.kind}`}>{m.kind === 'buy' ? '▲' : '▼'} {m.label}</div>
          ))}
        </div>
      )}
    </div>
  )
}
