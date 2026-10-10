const P = { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }

export const IconOverview = () => <svg {...P}><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></svg>
export const IconTest = () => <svg {...P}><path d="M3 3v18h18" /><path d="M7 15l4-5 3 3 5-6" /></svg>
export const IconBuild = () => <svg {...P}><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z" /></svg>
export const IconPaper = () => <svg {...P}><rect x="3" y="6" width="18" height="14" rx="2" /><path d="M3 10h18M7 15h4" /><path d="M8 6V4h8v2" /></svg>
export const IconSpark = () => <svg {...P}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /></svg>
export const IconSun = () => <svg {...P}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
export const IconMoon = () => <svg {...P}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
export const Logo = () => (
  <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
    <rect width="32" height="32" rx="8" fill="var(--brand)" />
    <path d="M8 21.5l5.2-6 4 3.2 6.8-8.2" fill="none" stroke="#fff" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="24" cy="10.5" r="2.2" fill="#fff" />
  </svg>
)
