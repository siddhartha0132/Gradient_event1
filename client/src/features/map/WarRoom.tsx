import { useEffect, useMemo, useState } from 'react'
import { Badge, Countdown, Defcon, Empty, Panel } from '../../components/ui'
import type { Schemas } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { countryByCode } from '../../lib/geo'
import { defectionRate, useLive, type LiveMatch } from '../../lib/live'
import { useCurrentRound, useRounds, useStandings, useTeams } from '../../lib/queries'
import { WorldMap } from './WorldMap'

function headline(entry: LiveMatch, name: (id: string) => string) {
  const { match } = entry
  const a = name(match.team_a)
  const b = name(match.team_b)
  if (match.forfeit_side !== null) {
    const loser = match.forfeit_side === 0 ? a : b
    return { text: `${loser} COLLAPSES: ${match.forfeit_reason ?? 'forfeit'}`, tone: 'text-alert' }
  }
  if (match.team_a === match.team_b) return { text: `${a} WAR-GAMES AGAINST ITSELF`, tone: 'text-muted' }
  const rate = defectionRate([entry.moves_a, entry.moves_b]) ?? 0
  const score = `${match.score_a}–${match.score_b}`
  if (rate < 0.25) return { text: `${a} AND ${b} KEEP THE PEACE ${score}`, tone: 'text-coop' }
  if (rate > 0.6) return { text: `HOSTILITIES BETWEEN ${a} AND ${b} ${score}`, tone: 'text-alert' }
  const betrayer = (match.score_a ?? 0) > (match.score_b ?? 0) ? a : b
  return { text: `${betrayer} BREAKS AN ACCORD ${score}`, tone: 'text-amber' }
}

function useLastPublished(rounds: Schemas['RoundOut'][] | undefined) {
  const published = useLive((s) => s.published)
  const last = rounds?.filter((r) => r.status === 'published').at(-1)
  const { data } = useStandings(last?.id, !published || published.round.id !== last?.id)
  if (published && (!last || published.round.index >= last.index)) return { round: published.round, standings: published.standings }
  return last && data ? { round: last, standings: data } : null
}

function Ticker({ lines }: { lines: { text: string; tone: string }[] }) {
  if (!lines.length) return <div className="label px-4 py-2">Awaiting signals from the front…</div>
  const doubled = [...lines, ...lines]
  return (
    <div className="overflow-hidden py-2 whitespace-nowrap">
      <div className="ticker inline-block" style={{ animationDuration: `${Math.max(30, lines.length * 6)}s` }}>
        {doubled.map((l, i) => (
          <span key={i} className={`mx-6 text-sm tracking-wider ${l.tone}`}>
            ◆ {l.text}
          </span>
        ))}
      </div>
    </div>
  )
}

function FallOverlay() {
  const published = useLive((s) => s.published)
  const { data: teams } = useTeams()
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    if (!published || Date.now() - published.at > 5000) return
    setVisible(true)
    const id = setTimeout(() => setVisible(false), published.champion ? 20_000 : 9000)
    return () => clearTimeout(id)
  }, [published])
  if (!visible || !published) return null
  const byId = new Map(teams?.map((t) => [t.id, t]))
  const champion = published.champion && byId.get(published.champion)
  const fallen = published.eliminated.map((id) => byId.get(id)?.name ?? '?')
  return (
    <button
      onClick={() => setVisible(false)}
      className="absolute inset-0 z-20 flex cursor-pointer flex-col items-center justify-center gap-6 bg-ink/80 text-center backdrop-blur-sm"
    >
      {champion ? (
        <>
          <span className="label">After {published.round.index} rounds, one nation stands</span>
          <span className="text-6xl font-bold tracking-[0.2em] text-amber drop-shadow-[0_0_30px_#f5a524]">
            {champion.name.toUpperCase()}
          </span>
          <span className="stamp rotate-[-4deg] text-2xl text-coop">Champion</span>
        </>
      ) : (
        <>
          <span className="stamp rotate-[-3deg] text-3xl text-alert">Round {published.round.index} · {published.round.name}</span>
          <span className="label">Nations fallen</span>
          <span className="max-w-3xl text-2xl tracking-widest text-paper line-through decoration-alert">
            {fallen.join(' · ') || 'None'}
          </span>
        </>
      )}
    </button>
  )
}

export function WarRoom({ spectator = false }: { spectator?: boolean }) {
  const { data: teams = [] } = useTeams()
  const { data: round } = useCurrentRound()
  const { data: rounds } = useRounds()
  const feed = useLive((s) => s.feed)
  const myTeamId = useAuth((s) => s.session?.user.team?.id)
  const last = useLastPublished(rounds)
  const byCode = useMemo(countryByCode, [])

  const roundFeed = useMemo(() => feed.filter((f) => f.match.round_id === round?.id), [feed, round?.id])
  const rate = defectionRate(roundFeed.slice(-60).flatMap((f) => [f.moves_a, f.moves_b]))
  const nameOf = useMemo(() => {
    const byId = new Map(teams.map((t) => [t.id, t]))
    return (id: string) => {
      const t = byId.get(id)
      return ((t?.country_code && byCode.get(t.country_code)?.name) || t?.name || '?').toUpperCase()
    }
  }, [teams, byCode])
  const lines = useMemo(() => roundFeed.slice(-14).reverse().map((f) => headline(f, nameOf)), [roundFeed, nameOf])
  const alive = teams.filter((t) => t.eliminated_in == null && t.country_code)
  const progress = round && round.matches_total ? round.matches_done / round.matches_total : 0

  const header = (
    <div className="flex flex-wrap items-center justify-between gap-4 border-b border-steel px-5 py-3">
      <div className="flex items-center gap-4">
        {round && (
          <>
            <span className="label">Round {round.index}</span>
            <span className="text-lg font-bold tracking-widest">{round.name.toUpperCase()}</span>
            <span className="text-sm text-amber">{round.game.name}</span>
            <Badge status={round.status} />
          </>
        )}
      </div>
      <div className="flex items-center gap-5">
        {round?.status === 'running' && (
          <div className="flex items-center gap-2">
            <div className="h-2 w-40 border border-steel-light">
              <div className="h-full bg-alert transition-all" style={{ width: `${progress * 100}%` }} />
            </div>
            <span className="text-xs text-muted tabular-nums">
              {round.matches_done}/{round.matches_total}
            </span>
          </div>
        )}
        {round?.status === 'open' && <Countdown round={round} large={spectator} />}
        <span className="label">{alive.length} nations stand</span>
        <Defcon rate={rate} />
      </div>
    </div>
  )

  return (
    <div className={`flex flex-col ${spectator ? 'h-screen' : 'h-full'}`}>
      {header}
      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          <WorldMap teams={teams} feed={roundFeed} myTeamId={myTeamId} />
          <FallOverlay />
        </div>
        {!spectator && (
          <aside className="flex w-80 shrink-0 flex-col gap-3 overflow-y-auto border-l border-steel p-3">
            <Panel title={last ? `Standings · round ${last.round.index}` : 'Standings'}>
              {last ? (
                <ol className="flex flex-col gap-1 text-sm">
                  {last.standings.map((s) => (
                    <li key={s.team_id} className={`flex items-center justify-between gap-2 ${s.team_id === myTeamId ? 'text-amber' : ''}`}>
                      <span className="truncate">
                        <span className="mr-2 inline-block w-5 text-right text-muted tabular-nums">{s.rank ?? '–'}</span>
                        {s.team_name}
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="tabular-nums text-muted">{s.rank ? s.total : ''}</span>
                        <Badge status={s.outcome} />
                      </span>
                    </li>
                  ))}
                </ol>
              ) : (
                <Empty>Standings appear once organisers approve a round.</Empty>
              )}
            </Panel>
            <Panel title="Dispatches">
              {lines.length ? (
                <ul className="flex flex-col gap-1.5 text-xs">
                  {lines.slice(0, 10).map((l, i) => (
                    <li key={i} className={l.tone}>
                      {l.text}
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty>Quiet on every front.</Empty>
              )}
            </Panel>
          </aside>
        )}
      </div>
      <div className="border-t border-steel bg-panel">
        <Ticker lines={lines} />
      </div>
    </div>
  )
}
