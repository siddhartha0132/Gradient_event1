import { useState, type FormEvent } from 'react'
import { Button, inputClass } from '../../components/ui'
import { ApiError, api, unwrap } from '../../lib/api'
import { useAuth } from '../../lib/auth'

export function Login({ spectator = false }: { spectator?: boolean }) {
  const setSession = useAuth((s) => s.setSession)
  const [username, setUsername] = useState(spectator ? 'projector' : '')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const pair = unwrap(await api.POST('/api/v1/auth/login', { body: { username, password } }))
      setSession({ access: pair.access_token, refresh: pair.refresh_token, user: pair.user })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Cannot reach the Command Server')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-10 px-4">
      <div className="text-center">
        <p className="label mb-4">Eyes only · Directorate of Game Theory · Gradient Club</p>
        <h1 className="text-6xl font-bold tracking-[0.25em] text-alert drop-shadow-[0_0_24px_rgb(229_36_59/0.5)] sm:text-7xl">
          IRON CURTAIN
        </h1>
        <p className="mt-4 font-[family-name:var(--font-type)] text-xl">Trust is a strategy. So is betrayal.</p>
      </div>
      <form onSubmit={submit} className="flex w-full max-w-sm flex-col gap-4 border border-steel bg-panel p-6">
        <span className="label">{spectator ? 'Projector access' : 'Identify yourself'}</span>
        <input className={inputClass} placeholder="Username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        <input
          className={inputClass}
          placeholder="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <p className="text-sm text-alert">{error}</p>}
        <Button variant="primary" disabled={busy || !username || !password}>
          {busy ? 'Authenticating…' : 'Enter'}
        </Button>
      </form>
    </div>
  )
}
