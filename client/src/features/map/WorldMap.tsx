import { useEffect, useMemo, useRef, useState } from 'react'
import type { Schemas } from '../../lib/api'
import { MAP_HEIGHT, MAP_WIDTH, arcPath, countries, countryByCode, teamColor } from '../../lib/geo'
import { defectionRate, type LiveMatch } from '../../lib/live'

type Strike = { key: string; from: [number, number]; to: [number, number]; color: string; born: number }

const STRIKE_MS = 1700
const MAX_ACTIVE = 36
const RELEASE_EVERY_MS = 70

function strikeColor(entry: LiveMatch) {
  const rate = defectionRate([entry.moves_a, entry.moves_b]) ?? 0
  if (entry.match.forfeit_side !== null) return '#ffffff'
  return rate < 0.25 ? '#22c55e' : rate > 0.6 ? '#e5243b' : '#f5a524'
}

/**
 * Matches arrive in bursts, so they are queued and released at a steady pace,
 * which keeps the map smooth however fast results come in.
 */
function useStrikes(feed: LiveMatch[], teamCountry: Map<string, string>) {
  const [active, setActive] = useState<Strike[]>([])
  const queue = useRef<Strike[]>([])
  const seen = useRef(new Set<string>())
  const byCode = useMemo(countryByCode, [])

  useEffect(() => {
    for (const entry of feed) {
      if (seen.current.has(entry.match.id)) continue
      seen.current.add(entry.match.id)
      if (Date.now() - entry.at > 10_000) continue // old news, e.g. after a tab was hidden
      const a = byCode.get(teamCountry.get(entry.match.team_a) ?? '')
      const b = byCode.get(teamCountry.get(entry.match.team_b) ?? '')
      if (!a || !b) continue
      queue.current.push({ key: entry.match.id, from: a.center, to: b.center, color: strikeColor(entry), born: 0 })
    }
    if (queue.current.length > 300) queue.current.splice(0, queue.current.length - 300)
  }, [feed, teamCountry, byCode])

  useEffect(() => {
    const id = setInterval(() => {
      const now = Date.now()
      setActive((current) => {
        const alive = current.filter((s) => now - s.born < STRIKE_MS)
        if (alive.length < MAX_ACTIVE && queue.current.length) {
          const next = queue.current.shift()!
          alive.push({ ...next, born: now })
        }
        return alive.length === current.length && alive.every((s, i) => s === current[i]) ? current : alive
      })
    }, RELEASE_EVERY_MS)
    return () => clearInterval(id)
  }, [])

  return active
}

export function WorldMap({
  teams,
  feed = [],
  myTeamId,
  claimable,
  selected,
  onPick,
  showLabels = true,
}: {
  teams: Schemas['TeamOut'][]
  feed?: LiveMatch[]
  myTeamId?: string | null
  claimable?: Set<string>
  selected?: string | null
  onPick?: (code: string) => void
  showLabels?: boolean
}) {
  const shapes = useMemo(countries, [])
  const byCode = useMemo(countryByCode, [])
  const owner = useMemo(() => new Map(teams.filter((t) => t.country_code).map((t) => [t.country_code!, t])), [teams])
  const teamCountry = useMemo(
    () => new Map(teams.filter((t) => t.country_code).map((t) => [t.id, t.country_code!])),
    [teams],
  )
  const strikes = useStrikes(feed, teamCountry)
  const [hover, setHover] = useState<{ name: string; x: number; y: number } | null>(null)

  return (
    <div className="relative h-full w-full">
      <svg viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} className="h-full w-full" preserveAspectRatio="xMidYMid meet">
        <defs>
          <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">
            <path d="M24 0H0V24" fill="none" stroke="#ffffff08" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width={MAP_WIDTH} height={MAP_HEIGHT} fill="url(#grid)" />
        {shapes.map((c) => {
          const team = owner.get(c.code)
          const canClaim = claimable?.has(c.code)
          const classes = [
            'country',
            team ? 'claimed' : '',
            team?.eliminated_in != null ? 'fallen' : '',
            team && team.id === myTeamId ? 'mine' : '',
            canClaim ? 'claimable' : '',
            selected === c.code ? 'selected' : '',
          ].join(' ')
          return (
            <path
              key={c.code}
              d={c.d}
              className={classes}
              style={team && team.eliminated_in == null ? { fill: teamColor(team.id) } : undefined}
              onClick={canClaim && onPick ? () => onPick(c.code) : undefined}
              onMouseMove={(e) => {
                const box = e.currentTarget.ownerSVGElement!.getBoundingClientRect()
                setHover({ name: team ? `${c.name} · ${team.name}` : c.name, x: e.clientX - box.left, y: e.clientY - box.top })
              }}
              onMouseLeave={() => setHover(null)}
            />
          )
        })}
        {strikes.map((s) => {
          const arc = arcPath(s.from, s.to)
          const self = s.from[0] === s.to[0] && s.from[1] === s.to[1]
          return (
            <g key={s.key} style={{ pointerEvents: 'none' }}>
              {!self && (
                <path
                  d={arc.d}
                  className="strike"
                  stroke={s.color}
                  strokeWidth={1.4}
                  style={{ strokeDasharray: arc.length, ['--len' as string]: arc.length }}
                />
              )}
              <circle cx={s.to[0]} cy={s.to[1]} r={5} fill="none" stroke={s.color} strokeWidth={1.2} className="pulse" />
            </g>
          )
        })}
        {showLabels &&
          teams
            .filter((t) => t.country_code && byCode.has(t.country_code))
            .map((t) => {
              const c = byCode.get(t.country_code!)!
              const fallen = t.eliminated_in != null
              return (
                <text
                  key={t.id}
                  x={c.center[0]}
                  y={c.center[1]}
                  textAnchor="middle"
                  className="pointer-events-none select-none"
                  style={{
                    fontSize: 8,
                    fill: fallen ? '#5b636d' : '#f2f4f6',
                    textDecoration: fallen ? 'line-through' : undefined,
                    paintOrder: 'stroke',
                    stroke: '#08090a',
                    strokeWidth: 2.5,
                    letterSpacing: '0.08em',
                    transition: 'fill 2.5s',
                  }}
                >
                  {t.name.toUpperCase()}
                </text>
              )
            })}
      </svg>
      {hover && (
        <div
          className="pointer-events-none absolute z-10 border border-steel-light bg-ink/95 px-2 py-1 text-xs"
          style={{ left: hover.x + 12, top: hover.y + 12 }}
        >
          {hover.name}
        </div>
      )}
    </div>
  )
}
