import { useId } from 'react'

const P = { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }

export const IconOverview = () => <svg {...P}><path d="M3 10.5L12 3l9 7.5" /><path d="M5 9v11h14V9" /><path d="M10 20v-6h4v6" /></svg>
export const IconTest = () => <svg {...P}><path d="M3 3v18h18" /><path d="M7 15l4-5 3 3 5-6" /></svg>
export const IconBuild = () => <svg {...P}><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z" /></svg>
export const IconPaper = () => <svg {...P}><rect x="3" y="6" width="18" height="14" rx="2" /><path d="M3 10h18M7 15h4" /><path d="M8 6V4h8v2" /></svg>
export const IconSpark = () => <svg {...P}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /></svg>
export const IconSun = () => <svg {...P}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
export const IconMoon = () => <svg {...P}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>

/* the agent's six analysts */
export const IconCandles = () => <svg {...P}><path d="M6 3v4M6 15v6M12 2v3M12 13v9M18 6v5M18 17v4" /><rect x="4" y="7" width="4" height="8" rx="1" /><rect x="10" y="5" width="4" height="8" rx="1" /><rect x="16" y="11" width="4" height="6" rx="1" /></svg>
export const IconNews = () => <svg {...P}><path d="M4 5h13v14a1 1 0 0 0 1 1H6a2 2 0 0 1-2-2z" /><path d="M17 9h3v9a2 2 0 0 1-2 2" /><path d="M8 9h5M8 13h5M8 16h3" /></svg>
export const IconChat = () => <svg {...P}><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" /><path d="M9 11h.01M12 11h.01M15 11h.01" /></svg>
export const IconLedger = () => <svg {...P}><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 7h8M8 11h8M8 15h4" /><path d="M15 15l1.5 1.5L19 14" /></svg>
export const IconScales = () => <svg {...P}><path d="M12 3v18M7 21h10M5 7h14" /><path d="M5 7l-3 6a3 3 0 0 0 6 0zM19 7l-3 6a3 3 0 0 0 6 0z" /></svg>
export const IconShield = () => <svg {...P}><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M8.5 12l2.5 2.5 4.5-5" /></svg>

/* bot glyphs and misc */
export const IconCross = () => <svg {...P}><path d="M3 17c4 0 5-10 9-10s5 6 9 6" /><path d="M3 9c5 0 6 8 10 8s5-4 8-4" /></svg>
export const IconWave = () => <svg {...P}><path d="M2 12c2.5-6 5-6 7.5 0s5 6 7.5 0 3.5-4 5-3" /><path d="M2 20h20" /></svg>
export const IconBolt = () => <svg {...P}><path d="M13 2L4 14h7l-1 8 9-12h-7z" /></svg>
export const IconTrend = () => <svg {...P}><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></svg>
export const IconUser = () => <svg {...P}><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></svg>
export const IconUpload = () => <svg {...P}><path d="M12 15V3M7 8l5-5 5 5" /><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" /></svg>
export const IconPlay = () => <svg {...P}><path d="M7 4v16l13-8z" /></svg>
export const IconPlus = () => <svg {...P}><path d="M12 5v14M5 12h14" /></svg>
export const IconArrow = () => <svg {...P}><path d="M5 12h14M13 6l6 6-6 6" /></svg>

export function Logo({ size = 30 }: { size?: number }) {
  const id = `pt-logo-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  return (
  <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
    <defs>
      <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#8a6bff" /><stop offset="1" stopColor="#5a35e8" />
      </linearGradient>
    </defs>
    <rect width="32" height="32" rx="10" fill={`url(#${id})`} />
    <path d="M8 21.5l5.2-6 4 3.2 6.8-8.2" fill="none" stroke="#fff" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="24" cy="10.5" r="2.4" fill="#ffb547" />
  </svg>
  )
}
