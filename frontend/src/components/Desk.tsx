import type { CSSProperties, ReactNode } from 'react'
import { IconBolt, IconCandles, IconChat, IconCross, IconLedger, IconNews, IconScales, IconShield, IconTrend, IconUser, IconWave } from './Icons'

/** The agent's research desk: one face per pipeline step (ids match Agent STEPS). */
export const DESK: { id: string; name: string; icon: ReactNode }[] = [
  { id: 'market', name: 'Charts', icon: <IconCandles /> },
  { id: 'news', name: 'News', icon: <IconNews /> },
  { id: 'social', name: 'Traders', icon: <IconChat /> },
  { id: 'fundamentals', name: 'Financials', icon: <IconLedger /> },
  { id: 'debate', name: 'Bull vs bear', icon: <IconScales /> },
  { id: 'call', name: 'Risk check', icon: <IconShield /> },
]

/** A face for each rule bot: glyph + colour family (CSS class `look-<tone>`). */
export function botLook(id: string): { icon: ReactNode; tone: string } {
  if (id.startsWith('version:')) return { icon: <IconUser />, tone: 'violet' }
  if (id.includes('golden')) return { icon: <IconCross />, tone: 'gold' }
  if (id.includes('rsi') || id.includes('dip')) return { icon: <IconWave />, tone: 'teal' }
  if (id.includes('macd') || id.includes('break')) return { icon: <IconBolt />, tone: 'pink' }
  return { icon: <IconTrend />, tone: 'blue' }
}

export function BotBadge({ id, size = 'md' }: { id: string; size?: 'sm' | 'md' | 'lg' }) {
  const l = botLook(id)
  return <span className={`bot-badge ${size} look-${l.tone}`} aria-hidden="true">{l.icon}</span>
}

export const POPULAR =['RELIANCE', 'INFY', 'TCS', 'HDFCBANK', 'ICICIBANK', 'SBIN']

/** The headline question with the stock as an inline field: "Should I buy RELIANCE?" */
export function AskSentence({ value, onChange, onSubmit, holding = false, size = 'xl', id = 'ask-symbol' }: {
  value: string; onChange: (v: string) => void; onSubmit: () => void; holding?: boolean; size?: 'xl' | 'lg'; id?: string
}) {
  return (
    <form className={`ask-sentence ${size}`} onSubmit={e => { e.preventDefault(); onSubmit() }}>
      <label htmlFor={id}>{holding ? 'Should I keep' : 'Should I buy'}</label>
      <span className="ask-end">
        <span className="ask-field" data-value={value || 'RELIANCE'}>
          <input id={id} value={value} onChange={e => onChange(e.target.value.toUpperCase().replace(/[^A-Z0-9&.^-]/g, ''))}
            placeholder="RELIANCE" autoComplete="off" spellCheck={false} aria-label="NSE stock symbol" maxLength={20} size={1} />
        </span>
        <span className="ask-q" aria-hidden="true">?</span>
      </span>
    </form>
  )
}

/** Row of analyst faces; `state` lights each one (done / working / off / waiting). */
export function DeskRow({ state, compact }: { state?: (id: string) => 'done' | 'working' | 'off' | 'waiting'; compact?: boolean }) {
  return (
    <ol className={`desk ${compact ? 'compact' : ''}`} aria-label="The agent's research steps">
      {DESK.map((d, i) => {
        const st = state?.(d.id) ?? 'waiting'
        return (
          <li key={d.id} className={`desk-seat ${st}`} style={{ '--i': i } as CSSProperties}>
            <span className="desk-face">{d.icon}</span>
            <span className="desk-name">{d.name}</span>
          </li>
        )
      })}
    </ol>
  )
}
