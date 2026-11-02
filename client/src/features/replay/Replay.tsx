import { useEffect, useMemo, useState } from 'react'
import { Badge, Button, Empty, Panel, inputClass } from '../../components/ui'
import { useAuth } from '../../lib/auth'
import { useMatches, useReplay, useRounds, useTeams } from '../../lib/queries'

function Playback({ matchId, nameOf }: { matchId: string; nameOf: (id: string) => string }) {
  const { data } = useReplay(matchId)
  const [turn, setTurn] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(8)
  const total = data?.moves_a.length ?? 0

  useEffect(() => {
    setTurn(0)
    setPlaying(true)
  }, [matchId])

  useEffect(() => {
    if (!playing) return
    const id = setInterval(() => setTurn((t) => (t >= total ? t : t + 1)), 1000 / speed)
    return () => clearInterval(id)
  }, [playing, speed, total])

  useEffect(() => {
    if (total && turn >= total) setPlaying(false)
  }, [turn, total])

  const scores = useMemo(() => {
    if (!data) return [0, 0]
    let a = 0
    let b = 0
    for (let i = 0; i < turn; i++) {
      const [sa, sb] = data.game.payoffs[data.moves_a[i] + data.moves_b[i]]
      a += sa
      b += sb
    }
    return [a, b]
  }, [data, turn])

  if (!data) return <Empty>Loading replay…</Empty>
  const { match } = data
  const sides = [
    { name: nameOf(match.team_a), moves: data.moves_a, score: scores[0], final: match.score_a },
    { name: nameOf(match.team_b), moves: data.moves_b, score: scores[1], final: match.score_b },
  ]
  const start = Math.max(0, turn - 60) // show the last 60 turns

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <span className="label">
          {data.game.name} · repetition {match.repetition + 1} · turn {turn}/{total}
        </span>
        {match.forfeit_side !== null && <span className="text-sm text-alert">Forfeit: {match.forfeit_reason}</span>}
      </div>
      {sides.map((s, i) => (
        <div key={i} className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between">
            <span className="text-lg font-bold tracking-widest">{s.name}</span>
            <span className="text-3xl font-bold tabular-nums text-amber">{s.score}</span>
          </div>
          <div className="flex h-6 gap-0.5">
            {[...s.moves.slice(start, turn)].map((m, j) => (
              <span key={start + j} className={`w-2.5 ${m === 'C' ? 'bg-coop' : 'bg-alert'}`} title={`Turn ${start + j + 1}: ${m}`} />
            ))}
          </div>
        </div>
      ))}
      <input type="range" min={0} max={total} value={turn} onChange={(e) => setTurn(Number(e.target.value))} className="accent-[var(--color-alert)]" />
      <div className="flex items-center gap-3">
        <Button variant="primary" onClick={() => (turn >= total ? (setTurn(0), setPlaying(true)) : setPlaying(!playing))}>
          {playing ? 'Pause' : turn >= total ? 'Replay' : 'Play'}
        </Button>
        <Button onClick={() => setTurn(total)}>End</Button>
        <label className="ml-auto flex items-center gap-2 text-xs text-muted">
          Speed
          <select className={inputClass} value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {[2, 8, 25, 80].map((s) => (
              <option key={s} value={s}>
                {s} turns/s
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-xs text-muted">
        Legend: <span className="text-coop">■ cooperate</span> <span className="text-alert">■ defect</span>. Final score {sides[0].final}–{sides[1].final}.
      </p>
    </div>
  )
}

export function Replay() {
  const { data: rounds = [] } = useRounds()
  const { data: teams = [] } = useTeams()
  const user = useAuth((s) => s.session!.user)
  const playable = rounds.filter((r) => ['running', 'verifying', 'review', 'published'].includes(r.status))
  const [roundId, setRoundId] = useState<string | undefined>()
  const [matchId, setMatchId] = useState<string | undefined>()
  const activeRound = roundId ?? playable.at(-1)?.id
  const { data: matches = [] } = useMatches(activeRound)
  const [filter, setFilter] = useState('')

  const nameOf = useMemo(() => {
    const byId = new Map(teams.map((t) => [t.id, t.name]))
    return (id: string) => byId.get(id) ?? '?'
  }, [teams])

  const shown = matches.filter(
    (m) => m.status === 'done' && `${nameOf(m.team_a)} ${nameOf(m.team_b)}`.toLowerCase().includes(filter.toLowerCase()),
  )

  return (
    <div className="grid h-full grid-cols-[380px_1fr] gap-3 p-3">
      <Panel title="Matches" bodyClass="flex flex-col min-h-0">
        <div className="flex flex-col gap-2 border-b border-steel p-3">
          <select className={inputClass} value={activeRound ?? ''} onChange={(e) => (setRoundId(e.target.value), setMatchId(undefined))}>
            {playable.map((r) => (
              <option key={r.id} value={r.id}>
                Round {r.index}: {r.name} ({r.status})
              </option>
            ))}
          </select>
          <input className={inputClass} placeholder="Filter by team" value={filter} onChange={(e) => setFilter(e.target.value)} />
          {user.role === 'team' && rounds.find((r) => r.id === activeRound)?.status !== 'published' && (
            <p className="text-xs text-muted">Until this round is published you can only see your own matches.</p>
          )}
        </div>
        <ul className="min-h-0 flex-1 divide-y divide-steel overflow-y-auto">
          {shown.length === 0 && <Empty>No matches to show.</Empty>}
          {shown.map((m) => (
            <li key={m.id}>
              <button
                onClick={() => setMatchId(m.id)}
                className={`flex w-full cursor-pointer items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-steel/50 ${matchId === m.id ? 'bg-steel' : ''}`}
              >
                <span className="truncate">
                  {nameOf(m.team_a)} <span className="text-muted">vs</span> {m.team_a === m.team_b ? 'itself' : nameOf(m.team_b)}
                </span>
                <span className="flex items-center gap-2 tabular-nums">
                  {m.forfeit_side !== null && <Badge status="forfeit" />}
                  {m.score_a}–{m.score_b}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="Replay">{matchId ? <Playback matchId={matchId} nameOf={nameOf} /> : <Empty>Pick a match to replay it turn by turn.</Empty>}</Panel>
    </div>
  )
}
