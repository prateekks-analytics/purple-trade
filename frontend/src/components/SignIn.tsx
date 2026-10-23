import { useState } from 'react'
import { api } from '../api'
import type { Me } from '../lib/auth'
import { errText } from './AgentBits'
import { Logo } from './Icons'

/** Sign in, or create one of the few friends' accounts while places are left. */
export function SignIn({ me, onDone }: { me: Me; onDone: (m: Me) => void }) {
  const [mode, setMode] = useState<'in' | 'new'>('in')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const full = me.seats_left <= 0

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || !password) { setError('Enter your name and password.'); return }
    setBusy(true); setError('')
    try {
      onDone(mode === 'in' ? await api.authLogin(name, password) : await api.authRegister(name, password))
    } catch (err) { setError(errText(err)); setBusy(false) }
  }

  return (
    <main className="signin" id="main">
      <form className="signin-card glass" onSubmit={submit} aria-labelledby="signin-h">
        <div className="signin-brand"><Logo size={30} /><span>Purple Trade</span></div>
        <h1 id="signin-h" className="signin-title">{mode === 'in' ? 'Sign in' : 'Create your account'}</h1>
        <p className="sub">{mode === 'in'
          ? 'Watch the Purple Desk bot trade with paper money, read its daily review, and build your own bots.'
          : `Your own private space to build and test bots, and a view of the main bot. ${me.seats_left} place${me.seats_left === 1 ? '' : 's'} left.`}</p>
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={e => { setName(e.target.value); setError('') }} autoComplete="username" autoFocus />
        </label>
        <label className="field">
          <span>Password{mode === 'new' ? ' (at least 8 characters)' : ''}</span>
          <input type="password" value={password} onChange={e => { setPassword(e.target.value); setError('') }}
            autoComplete={mode === 'in' ? 'current-password' : 'new-password'} />
        </label>
        {error && <p className="error-text" role="alert">{error}</p>}
        <button className="btn glow lg" type="submit" disabled={busy}>
          {busy ? 'One moment…' : mode === 'in' ? 'Sign in' : 'Create account'}
        </button>
        {mode === 'in'
          ? <p className="sub signin-switch">New here? {full
              ? 'All places are taken; ask the owner.'
              : <button type="button" className="linklike" onClick={() => { setMode('new'); setError('') }}>Create an account</button>}</p>
          : <p className="sub signin-switch">Have an account? <button type="button" className="linklike" onClick={() => { setMode('in'); setError('') }}>Sign in</button></p>}
        <p className="sub signin-note">Virtual money only. No real orders.</p>
      </form>
    </main>
  )
}
