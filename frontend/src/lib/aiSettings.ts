/** The AI this person connected. Kept in this browser only and sent with their own requests; never stored on the server. */
export interface AiSettings { provider: string; model: string; key: string }

const KEY = 'purple.ai'
let memory: AiSettings | null = null
const listeners = new Set<() => void>()

export function getAi(): AiSettings | null {
  if (memory) return memory
  try { const raw = localStorage.getItem(KEY); return raw ? JSON.parse(raw) as AiSettings : null } catch { return null }
}

export function setAi(s: AiSettings | null, remember = true) {
  memory = s && !remember ? s : null
  try {
    if (s && remember) localStorage.setItem(KEY, JSON.stringify(s))
    else localStorage.removeItem(KEY)
  } catch { /* storage unavailable: keep it for this visit only */ memory = s }
  listeners.forEach(f => f())
}

export function onAiChange(f: () => void) { listeners.add(f); return () => { listeners.delete(f) } }

export function aiHeaders(): Record<string, string> {
  const s = getAi()
  return s ? { 'X-AI-Provider': s.provider, 'X-AI-Model': s.model, 'X-AI-Key': s.key } : {}
}

/** Ask the app to show the "Connect an AI" dialog (used wherever an AI is needed). */
export function openAiConnect() { window.dispatchEvent(new Event('purple:connect-ai')) }
