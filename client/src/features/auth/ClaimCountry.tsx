import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Button, Panel, inputClass } from '../../components/ui'
import { ApiError, api, unwrap } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { useCountries, useTeams } from '../../lib/queries'
import { WorldMap } from '../map/WorldMap'

export function ClaimCountry() {
  const user = useAuth((s) => s.session!.user)
  const setUser = useAuth((s) => s.setUser)
  const queries = useQueryClient()
  const { data: countries = [] } = useCountries()
  const { data: teams = [] } = useTeams()
  const [selected, setSelected] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const free = useMemo(() => new Set(countries.filter((c) => !c.team_id).map((c) => c.code)), [countries])
  const chosen = countries.find((c) => c.code === selected)
  const matches = countries.filter((c) => !c.team_id && c.name.toLowerCase().includes(filter.toLowerCase())).slice(0, 8)

  async function claim() {
    if (!selected) return
    setBusy(true)
    setError(null)
    try {
      const team = unwrap(await api.POST('/api/v1/teams/me/country', { body: { code: selected } }))
      setUser({ ...user, team })
      queries.invalidateQueries({ queryKey: ['teams'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not claim the country')
      queries.invalidateQueries({ queryKey: ['countries'] })
      setSelected(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full gap-4 p-4">
      <div className="min-w-0 flex-1 border border-steel bg-panel/60">
        <WorldMap teams={teams} claimable={free} selected={selected} onPick={setSelected} myTeamId={user.team?.id} />
      </div>
      <Panel title="Claim your nation" className="w-80 shrink-0">
        <div className="flex flex-col gap-4">
          <p className="text-sm text-muted">
            {user.team?.name}, pick the country you will represent. Each country belongs to one team, and the choice is final.
          </p>
          <input className={inputClass} placeholder="Search countries" value={filter} onChange={(e) => setFilter(e.target.value)} />
          {filter && (
            <ul className="flex flex-col">
              {matches.map((c) => (
                <li key={c.code}>
                  <button className="w-full cursor-pointer px-2 py-1 text-left text-sm hover:bg-steel" onClick={() => setSelected(c.code)}>
                    {c.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="border border-steel p-3">
            <span className="label">Selected</span>
            <p className="mt-1 text-xl font-bold tracking-widest text-amber">{chosen ? chosen.name.toUpperCase() : '—'}</p>
          </div>
          {error && <p className="text-sm text-alert">{error}</p>}
          <Button variant="primary" disabled={!selected || busy} onClick={claim}>
            {busy ? 'Claiming…' : 'Claim this nation'}
          </Button>
        </div>
      </Panel>
    </div>
  )
}
