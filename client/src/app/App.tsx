import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Suspense, lazy, useEffect, useState } from 'react'
import { ConnectionStatus, Countdown, Empty, Toasts } from '../components/ui'
import { Dashboard } from '../features/admin/Dashboard'
import { ClaimCountry } from '../features/auth/ClaimCountry'
import { Login } from '../features/auth/Login'
import { FullscreenBanner, useFairplayReporting } from '../features/fairplay/fairplay'
import { WarRoom } from '../features/map/WarRoom'
import { Replay } from '../features/replay/Replay'
import { api, unwrap } from '../lib/api'
import { isStaff, useAuth } from '../lib/auth'
import { syncClock } from '../lib/clock'
import { handleEvent, useLive } from '../lib/live'
import { useCurrentRound } from '../lib/queries'
import { Realtime } from '../lib/realtime'

// Monaco is large, so the workspace loads only for teams
const Workspace = lazy(() => import('../features/workspace/Workspace').then((m) => ({ default: m.Workspace })))

const CLOCK_SYNC_MS = 30_000

function useRealtime(active: boolean, teamId: string | null | undefined) {
  const queries = useQueryClient()
  useEffect(() => {
    if (!active) return
    const realtime = new Realtime((message) => handleEvent(message, queries, teamId))
    realtime.start()
    syncClock().catch(() => {})
    const clock = setInterval(() => syncClock().catch(() => {}), CLOCK_SYNC_MS)
    return () => {
      realtime.stop()
      clearInterval(clock)
    }
  }, [active, teamId, queries])
}

/** Keeps the stored user (and its team, e.g. when it falls) in sync with the server. */
function useMe(active: boolean) {
  const setUser = useAuth((s) => s.setUser)
  const { data } = useQuery({
    queryKey: ['teams', 'me'],
    enabled: active,
    queryFn: async () => unwrap(await api.GET('/api/v1/me')),
  })
  useEffect(() => {
    if (data) setUser(data)
  }, [data, setUser])
}

type Tab = { key: string; label: string }

export function App() {
  const session = useAuth((s) => s.session)
  const logout = useAuth((s) => s.logout)
  const queries = useQueryClient()
  const user = session?.user
  const spectatePath = window.location.pathname.startsWith('/spectate')
  useRealtime(!!session, user?.team?.id)
  useMe(!!session)
  useFairplayReporting(user?.role === 'team')
  const { data: round } = useCurrentRound()

  const tabs: Tab[] =
    user?.role === 'team'
      ? [
          { key: 'workspace', label: 'Workspace' },
          { key: 'war', label: 'War Room' },
          { key: 'replay', label: 'Replays' },
        ]
      : isStaff(user?.role)
        ? [
            { key: 'command', label: 'Command' },
            { key: 'war', label: 'War Room' },
            { key: 'replay', label: 'Replays' },
          ]
        : [{ key: 'war', label: 'War Room' }]
  const [tab, setTab] = useState<string | null>(null)
  const active = tabs.find((t) => t.key === tab)?.key ?? tabs[0].key

  if (!session || !user) return <Login spectator={spectatePath} />
  if (spectatePath || user.role === 'spectator') {
    return (
      <>
        <WarRoom spectator />
        <div className="scanlines" />
      </>
    )
  }

  const needsCountry = user.role === 'team' && !user.team?.country_code

  return (
    <div className="flex h-screen flex-col">
      {user.role === 'team' && <FullscreenBanner />}
      <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-steel bg-ink/90 px-5">
        <div className="flex items-center gap-8">
          <span className="flex items-center gap-3">
            <span className="h-3 w-3 bg-alert shadow-[0_0_12px_var(--color-alert)]" />
            <span className="text-lg font-bold tracking-[0.3em] text-alert">IRON CURTAIN</span>
          </span>
          {!needsCountry && (
            <nav className="flex gap-1">
              {tabs.map((t, i) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`cursor-pointer border-b-2 px-3 py-4 text-xs font-bold tracking-[0.2em] uppercase transition ${
                    active === t.key ? 'border-alert text-paper' : 'border-transparent text-muted hover:text-paper'
                  }`}
                >
                  <span className="mr-2 text-alert">0{i + 1}</span>
                  {t.label}
                </button>
              ))}
            </nav>
          )}
        </div>
        <div className="flex items-center gap-6">
          <Countdown round={round} />
          <ConnectionStatus />
          <span className="text-sm">
            <span className="text-muted">{user.team ? user.team.name : user.role}</span>
            <button onClick={() => (logout(), queries.clear(), useLive.setState({ feed: [], flags: [], published: null }))} className="label ml-3 cursor-pointer !text-[10px] hover:!text-alert">
              Log out
            </button>
          </span>
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        {needsCountry ? (
          <ClaimCountry />
        ) : (
          <Suspense fallback={<Empty>Loading…</Empty>}>
            {active === 'workspace' && <Workspace />}
            {active === 'command' && <Dashboard />}
            {active === 'war' && <WarRoom />}
            {active === 'replay' && <Replay />}
          </Suspense>
        )}
      </main>
      <Toasts />
      <div className="scanlines" />
    </div>
  )
}
