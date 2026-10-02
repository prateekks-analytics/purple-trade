import { useEffect, useRef } from 'react'

const TICKERS = ['NIFTY', 'RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK', 'SBIN', 'ITC', 'LT', 'BHARTIARTL', 'RSI', 'MACD', 'EMA', 'SMA', 'ATR', 'VWMA']
const DURATION = 2100

/** Full-screen "hyperspace into the market" transition. Decorative only: no prices shown are real. */
export function Warp({ onDone }: { onDone: () => void }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const done = useRef(onDone)
  done.current = onDone

  useEffect(() => {
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) { const t = setTimeout(() => done.current(), 200); return () => clearTimeout(t) }
    const cv = ref.current!
    const ctx = cv.getContext('2d')!
    const dpr = Math.min(devicePixelRatio || 1, 2)
    const resize = () => { cv.width = innerWidth * dpr; cv.height = innerHeight * dpr }
    resize()
    addEventListener('resize', resize)

    const rand = (a: number, b: number) => a + Math.random() * (b - a)
    const stars = Array.from({ length: 520 }, () => ({ a: rand(0, Math.PI * 2), r: rand(0, 1), s: rand(0.4, 1.6), hue: Math.random() < 0.7 ? 265 : Math.random() < 0.5 ? 150 : 190 }))
    const labels = Array.from({ length: 34 }, () => ({
      a: rand(0, Math.PI * 2), r: rand(0.05, 0.4), s: rand(0.6, 1.3),
      text: Math.random() < 0.5 ? TICKERS[Math.floor(rand(0, TICKERS.length))] : `${Math.random() < 0.6 ? '▲' : '▼'} ${rand(0.1, 4.9).toFixed(2)}%`,
    }))
    const candles = Array.from({ length: 90 }, (_, i) => ({ x: i, o: rand(0.3, 0.7), up: Math.random() < 0.58, h: rand(0.04, 0.16) }))

    let raf = 0
    const t0 = performance.now()
    const frame = (now: number) => {
      const t = Math.min((now - t0) / DURATION, 1)
      const W = cv.width, H = cv.height, cx = W / 2, cy = H / 2, R = Math.hypot(cx, cy)
      const speed = t < 0.6 ? 0.004 + t * t * 0.09 : 0.036 + (t - 0.6) * 0.05
      ctx.fillStyle = `rgba(7, 5, 16, ${t < 0.08 ? 1 : 0.32})`
      ctx.fillRect(0, 0, W, H)

      // warp streaks
      ctx.lineCap = 'round'
      for (const s of stars) {
        const r0 = s.r
        s.r += speed * s.s * (0.3 + s.r)
        if (s.r > 1.1) { s.r = rand(0, 0.08); s.a = rand(0, Math.PI * 2) }
        const x0 = cx + Math.cos(s.a) * r0 * R, y0 = cy + Math.sin(s.a) * r0 * R
        const x1 = cx + Math.cos(s.a) * s.r * R, y1 = cy + Math.sin(s.a) * s.r * R
        ctx.strokeStyle = `hsla(${s.hue}, 95%, ${60 + s.r * 30}%, ${Math.min(1, s.r * 2)})`
        ctx.lineWidth = (0.6 + s.r * 2.4) * dpr
        ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke()
      }

      // flying tickers and percentages
      ctx.textAlign = 'center'
      for (const l of labels) {
        l.r += speed * l.s * 0.9
        if (l.r > 1.05) { l.r = rand(0.02, 0.1); l.a = rand(0, Math.PI * 2) }
        const size = (10 + l.r * 34) * dpr
        ctx.font = `700 ${size}px ui-monospace, Consolas, monospace`
        ctx.fillStyle = l.text.startsWith('▼') ? `rgba(255,95,110,${Math.min(1, l.r * 2.2)})`
          : l.text.startsWith('▲') ? `rgba(60,240,150,${Math.min(1, l.r * 2.2)})` : `rgba(200,185,255,${Math.min(0.9, l.r * 2)})`
        ctx.fillText(l.text, cx + Math.cos(l.a) * l.r * R, cy + Math.sin(l.a) * l.r * R)
      }

      // candlestick tape racing along the bottom
      const cw = 14 * dpr, base = H * 0.86, band = H * 0.12, shift = (now - t0) * 0.9 * dpr * (1 + t * 3)
      for (const c of candles) {
        const x = ((c.x * cw * 1.6 - shift) % (candles.length * cw * 1.6) + candles.length * cw * 1.6) % (candles.length * cw * 1.6)
        const y = base - c.o * band
        ctx.fillStyle = c.up ? 'rgba(60,240,150,0.55)' : 'rgba(255,95,110,0.55)'
        ctx.fillRect(x, y, cw, c.h * band)
        ctx.fillRect(x + cw / 2 - dpr / 2, y - c.h * band * 0.5, dpr, c.h * band * 2)
      }

      // title punch-in
      if (t > 0.5) {
        const k = Math.min(1, (t - 0.5) / 0.3)
        const scale = 0.6 + 0.4 * (1 - Math.pow(1 - k, 3))
        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(scale, scale)
        ctx.shadowColor = 'rgba(150,110,255,0.95)'
        ctx.shadowBlur = 40 * dpr
        ctx.fillStyle = `rgba(255,255,255,${k})`
        ctx.font = `800 ${Math.min(W / 11, 92 * dpr)}px Inter, "Segoe UI", system-ui, sans-serif`
        ctx.fillText('TRADING SUPERAGENT', 0, 0)
        ctx.shadowBlur = 0
        ctx.font = `600 ${16 * dpr}px ui-monospace, Consolas, monospace`
        ctx.fillStyle = `rgba(60,240,150,${k})`
        ctx.fillText('AGENTS ONLINE · BACKTEST · PAPER TRADE · DEPLOY', 0, 46 * dpr)
        ctx.restore()
      }
      // final flash
      if (t > 0.86) {
        ctx.fillStyle = `rgba(235,228,255,${(t - 0.86) / 0.14 * 0.85})`
        ctx.fillRect(0, 0, W, H)
      }
      if (t < 1) raf = requestAnimationFrame(frame)
      else done.current()
    }
    raf = requestAnimationFrame(frame)
    return () => { cancelAnimationFrame(raf); removeEventListener('resize', resize) }
  }, [])

  return <canvas ref={ref} className="warp" aria-hidden onClick={() => done.current()} title="Click to skip" />
}
