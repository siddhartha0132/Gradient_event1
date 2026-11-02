import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Badge, Button, Countdown, Empty, Panel, inputClass } from '../../components/ui'
import { ApiError, type Schemas } from '../../lib/api'
import { api, unwrap } from '../../lib/api'
import { useLive } from '../../lib/live'
import { useAdminTeams, useCountries, useCurrentRound, useFairplay, useReview, useRounds } from '../../lib/queries'
import { CATEGORY_INFO } from '../blocks/categories'

function useAction() {
  const toast = useLive((s) => s.toast)
  const queries = useQueryClient()
  const [busy, setBusy] = useState(false)
  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(true)
    try {
      await fn()
      toast('good', label)
      queries.invalidateQueries({ queryKey: ['round'] })
      queries.invalidateQueries({ queryKey: ['rounds'] })
      queries.invalidateQueries({ queryKey: ['review'] })
    } catch (err) {
      const extra = err instanceof ApiError && Array.isArray(err.details.blockers) ? `: ${err.details.blockers.join(', ')}` : ''
      toast('bad', (err instanceof ApiError ? err.message : 'Request failed') + extra)
    } finally {
      setBusy(false)
    }
  }
  return { busy, run }
}

const path = (round_id: string) => ({ params: { path: { round_id } } })

function BlockRules({ round }: { round: Schemas['RoundOut'] }) {
  const { busy, run } = useAction()
  const [rules, setRules] = useState(round.block_rules)
  const current = JSON.stringify(round.block_rules)
  useEffect(() => setRules(JSON.parse(current)), [current])
  const editable = round.status === 'draft' || round.status === 'open'
  const changed = JSON.stringify(rules) !== current
  const toggle = (c: string) =>
    setRules({ ...rules, categories: rules.categories.includes(c) ? rules.categories.filter((x) => x !== c) : [...rules.categories, c] })

  return (
    <div className="flex flex-col gap-2 border-t border-steel pt-3">
      <span className="label">Block rules</span>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex items-center gap-2 text-xs text-muted">
          Modules
          <input className={inputClass} type="number" min={0} max={10} disabled={!editable} value={rules.max_modules} onChange={(e) => setRules({ ...rules, max_modules: Number(e.target.value) })} />
        </label>
        <label className="flex items-center gap-2 text-xs text-muted">
          Blocks each
          <input className={inputClass} type="number" min={1} max={200} disabled={!editable} value={rules.max_blocks} onChange={(e) => setRules({ ...rules, max_blocks: Number(e.target.value) })} />
        </label>
      </div>
      <div className="flex flex-wrap gap-3">
        {Object.entries(CATEGORY_INFO).map(([key, info]) => (
          <label key={key} className="flex items-center gap-1.5 text-xs">
            <input type="checkbox" disabled={!editable} checked={rules.categories.includes(key)} onChange={() => toggle(key)} />
            <span style={{ color: info.colour }}>{info.label}</span>
          </label>
        ))}
      </div>
      {editable && changed && (
        <Button
          disabled={busy}
          onClick={() =>
            run('Block rules updated', async () => unwrap(await api.PUT('/api/v1/admin/rounds/{round_id}/rules', { ...path(round.id), body: rules })))
          }
        >
          Save block rules
        </Button>
      )}
    </div>
  )
}

function CodeViewer({ submissionId, team, onClose }: { submissionId: string; team: string; onClose: () => void }) {
  const [detail, setDetail] = useState<Schemas['SubmissionDetail'] | null>(null)
  useEffect(() => {
    api.GET('/api/v1/submissions/{submission_id}', { params: { path: { submission_id: submissionId } } }).then((r) => setDetail(unwrap(r)))
  }, [submissionId])
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-ink/80 p-8" onClick={onClose}>
      <div className="flex max-h-full w-full max-w-4xl flex-col border border-steel-light bg-panel" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-steel px-4 py-2">
          <span className="label !text-paper">
            {team} · v{detail?.version} · {detail?.status}
          </span>
          <Button className="!px-2 !py-1" onClick={onClose}>
            Close
          </Button>
        </header>
        {detail ? (
          <div className="flex flex-col gap-4 overflow-y-auto p-4 text-xs">
            <div>
              <span className="label">Hand-written</span>
              <pre className="mt-1 border border-steel bg-ink p-3 whitespace-pre-wrap">{detail.hand_code}</pre>
            </div>
            {detail.modules.map((m) => (
              <div key={m.name}>
                <span className="label">
                  Block module {m.name} · {m.blocks} blocks
                </span>
                <pre className="mt-1 border border-steel bg-ink p-3 whitespace-pre-wrap text-coop/90">{m.code}</pre>
              </div>
            ))}
          </div>
        ) : (
          <Empty>Loading…</Empty>
        )}
      </div>
    </div>
  )
}

function RoundControls({ round }: { round: Schemas['RoundOut'] }) {
  const { busy, run } = useAction()
  const [minutes, setMinutes] = useState(30)
  const id = round.id
  const extend = (m: number) =>
    run(`Window ${m > 0 ? 'extended' : 'shortened'} by ${Math.abs(m)} min`, async () =>
      unwrap(await api.POST('/api/v1/admin/rounds/{round_id}/window/extend', { ...path(id), body: { minutes: m } })),
    )

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-lg font-bold tracking-widest">
          {round.index}. {round.name.toUpperCase()}
        </span>
        <Badge status={round.status} />
      </div>
      <p className="text-xs text-muted">
        {round.game.name} · {round.turns ?? 'hidden'} turns · noise {round.noise} · {round.repetitions} reps · keeps{' '}
        {round.keep_count ?? `${Math.round(round.keep_fraction * 100)}%`}
      </p>

      {round.status === 'draft' && (
        <div className="flex gap-2">
          <input className={inputClass} type="number" min={1} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} />
          <Button
            variant="primary"
            disabled={busy || minutes <= 0}
            onClick={() =>
              run('Submission window opened', async () =>
                unwrap(await api.POST('/api/v1/admin/rounds/{round_id}/window/open', { ...path(id), body: { minutes } })),
              )
            }
          >
            Open window
          </Button>
        </div>
      )}

      {round.status === 'open' && (
        <>
          <Countdown round={round} large />
          <div className="flex flex-wrap gap-2">
            <Button disabled={busy} onClick={() => extend(1)}>+1 min</Button>
            <Button disabled={busy} onClick={() => extend(5)}>+5 min</Button>
            <Button disabled={busy} onClick={() => extend(-1)}>−1 min</Button>
            {round.paused_remaining === null ? (
              <Button disabled={busy} onClick={() => run('Window paused', async () => unwrap(await api.POST('/api/v1/admin/rounds/{round_id}/window/pause', path(id))))}>
                Pause
              </Button>
            ) : (
              <Button disabled={busy} onClick={() => run('Window resumed', async () => unwrap(await api.POST('/api/v1/admin/rounds/{round_id}/window/resume', path(id))))}>
                Resume
              </Button>
            )}
            <Button variant="danger" disabled={busy} onClick={() => run('Window closed', async () => unwrap(await api.POST('/api/v1/admin/rounds/{round_id}/window/close', path(id))))}>
              Close now
            </Button>
          </div>
          <p className="text-xs text-muted">When the window closes, each team's latest accepted version is locked in.</p>
        </>
      )}

      {round.status === 'locked' && (
        <Button variant="primary" disabled={busy} onClick={() => run('Round started', async () => unwrap(await api.POST('/api/v1/admin/rounds/{round_id}/start', path(id))))}>
          Start round
        </Button>
      )}

      {(round.status === 'running' || round.status === 'verifying') && (
        <div className="flex flex-col gap-1">
          <div className="h-2 border border-steel-light">
            <div className="h-full bg-alert transition-all" style={{ width: `${round.matches_total ? (100 * round.matches_done) / round.matches_total : 0}%` }} />
          </div>
          <span className="text-xs text-muted">
            {round.matches_done}/{round.matches_total} matches computed{round.status === 'verifying' ? ' · verifying cut line results' : ''}
          </span>
        </div>
      )}
      <BlockRules round={round} />
    </div>
  )
}

function Review({ round }: { round: Schemas['RoundOut'] }) {
  const { data } = useReview(round.id)
  const { data: teams = [] } = useAdminTeams()
  const { busy, run } = useAction()
  const [penalty, setPenalty] = useState({ team: '', points: 50, reason: '' })
  const nameOf = useMemo(() => new Map(teams.map((t) => [t.team.id, t.team.name])), [teams])
  if (!data) return <Empty>Loading review…</Empty>
  const v = data.verification

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="border border-steel p-2">
          <div className="text-2xl font-bold">{v.done}/{v.total}</div>
          <div className="label !text-[10px]">Verified</div>
        </div>
        <div className={`border p-2 ${v.mismatches.length ? 'border-alert text-alert' : 'border-steel'}`}>
          <div className="text-2xl font-bold">{v.mismatches.length}</div>
          <div className="label !text-[10px]">Mismatches</div>
        </div>
        <div className={`border p-2 ${data.failed_matches.length ? 'border-alert text-alert' : 'border-steel'}`}>
          <div className="text-2xl font-bold">{data.failed_matches.length}</div>
          <div className="label !text-[10px]">Failed</div>
        </div>
      </div>

      {v.mismatches.map((m) => (
        <div key={m.match_id} className="flex items-center justify-between gap-2 border border-alert-dim p-2 text-xs">
          <span>
            {nameOf.get(m.team_a)} vs {nameOf.get(m.team_b)}: {m.original.join('–')} ≠ {m.recomputed.join('–')}
          </span>
          <Button disabled={busy} onClick={() => run('Re-verification queued', async () => unwrap(await api.POST('/api/v1/admin/matches/{match_id}/reverify', { params: { path: { match_id: m.match_id } } })))}>
            Re-verify
          </Button>
        </div>
      ))}
      {data.failed_matches.map((m) => (
        <div key={m.id} className="flex items-center justify-between gap-2 border border-alert-dim p-2 text-xs">
          <span>
            {nameOf.get(m.team_a)} vs {nameOf.get(m.team_b)}: {m.forfeit_reason}
          </span>
          <Button disabled={busy} onClick={() => run('Match queued again', async () => unwrap(await api.POST('/api/v1/admin/matches/{match_id}/retry', { params: { path: { match_id: m.id } } })))}>
            Retry
          </Button>
        </div>
      ))}

      <table className="w-full text-sm">
        <thead>
          <tr className="label text-left !text-[10px]">
            <th className="py-1">#</th>
            <th>Team</th>
            <th className="text-right">Score</th>
            <th className="text-right">W/L/D</th>
            <th className="text-right">Outcome</th>
          </tr>
        </thead>
        <tbody>
          {data.standings.map((s) => (
            <tr key={s.team_id} className="border-t border-steel" title={s.reason ?? undefined}>
              <td className="py-1 text-muted tabular-nums">{s.rank ?? '–'}</td>
              <td>
                {s.team_name}
                {s.penalty > 0 && <span className="ml-2 text-xs text-alert">−{s.penalty}</span>}
              </td>
              <td className="text-right tabular-nums">{s.rank ? s.total : ''}</td>
              <td className="text-right text-muted tabular-nums">{s.rank ? `${s.wins}/${s.losses}/${s.draws}` : ''}</td>
              <td className="text-right">
                <Badge status={s.outcome} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.standings.some((s) => s.reason) && (
        <ul className="flex flex-col gap-1 text-xs text-muted">
          {data.standings.filter((s) => s.reason).map((s) => (
            <li key={s.team_id}>
              <span className="text-paper">{s.team_name}</span>: {s.reason}
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-col gap-2 border-t border-steel pt-3">
        <span className="label">Issue penalty for this round</span>
        <div className="flex gap-2">
          <select className={inputClass} value={penalty.team} onChange={(e) => setPenalty({ ...penalty, team: e.target.value })}>
            <option value="">Team…</option>
            {data.standings.map((s) => (
              <option key={s.team_id} value={s.team_id}>
                {s.team_name}
              </option>
            ))}
          </select>
          <input className={`${inputClass} w-24`} type="number" min={1} value={penalty.points} onChange={(e) => setPenalty({ ...penalty, points: Number(e.target.value) })} />
        </div>
        <input className={inputClass} placeholder="Reason" value={penalty.reason} onChange={(e) => setPenalty({ ...penalty, reason: e.target.value })} />
        <Button
          variant="danger"
          disabled={busy || !penalty.team || !penalty.reason || penalty.points <= 0}
          onClick={() =>
            run('Penalty issued', async () => {
              unwrap(
                await api.POST('/api/v1/admin/teams/{team_id}/penalties', {
                  params: { path: { team_id: penalty.team } },
                  body: { round_id: round.id, points: penalty.points, reason: penalty.reason },
                }),
              )
              setPenalty({ team: '', points: 50, reason: '' })
            })
          }
        >
          Issue penalty
        </Button>
      </div>

      {data.blockers.length > 0 && round.status === 'review' && (
        <p className="text-sm text-alert">Blocked: {data.blockers.join(' · ')}</p>
      )}
      <Button
        variant="primary"
        disabled={busy || data.blockers.length > 0}
        onClick={() => run('Round published', async () => unwrap(await api.POST('/api/v1/admin/rounds/{round_id}/approve', path(round.id))))}
      >
        Approve and publish
      </Button>
    </div>
  )
}

function Teams() {
  const { data: rows = [] } = useAdminTeams()
  const { data: countries = [] } = useCountries()
  const countryName = useMemo(() => new Map(countries.map((c) => [c.code, c.name])), [countries])
  const [viewing, setViewing] = useState<{ id: string; team: string } | null>(null)
  return (
    <Panel title={`Teams · ${rows.filter((r) => r.team.eliminated_in == null).length} standing`} bodyClass="p-0 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="label text-left !text-[10px]">
            <th className="px-3 py-2">Team</th>
            <th>Country</th>
            <th>Login</th>
            <th>Latest</th>
            <th>Accepted</th>
            <th className="text-right">Flags</th>
            <th className="pr-3" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.team.id} className={`border-t border-steel ${r.team.eliminated_in != null ? 'opacity-40' : ''}`}>
              <td className="px-3 py-1.5">
                {r.team.name}
                {r.team.eliminated_in != null && <span className="ml-2 text-xs text-alert">fell in R{r.team.eliminated_in}</span>}
              </td>
              <td className="text-muted">{r.team.country_code ? countryName.get(r.team.country_code) : '—'}</td>
              <td className="text-muted">{r.usernames.join(', ')}</td>
              <td>{r.latest_version ? <span className="flex items-center gap-1">v{r.latest_version} <Badge status={r.latest_status!} /></span> : '—'}</td>
              <td>{r.accepted_version ? `v${r.accepted_version}` : <span className="text-alert">none</span>}</td>
              <td className={`text-right tabular-nums ${r.fairplay_flags ? 'text-amber' : 'text-muted'}`}>{r.fairplay_flags}</td>
              <td className="pr-3 text-right">
                {r.latest_submission_id && (
                  <button className="label cursor-pointer !text-[10px] hover:!text-paper" onClick={() => setViewing({ id: r.latest_submission_id!, team: r.team.name })}>
                    View
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {viewing && <CodeViewer submissionId={viewing.id} team={viewing.team} onClose={() => setViewing(null)} />}
    </Panel>
  )
}

const FLAG_LABELS: Record<string, string> = {
  fullscreen_exit: 'Left full screen',
  tab_hidden: 'Switched tab or window',
  focus_lost: 'Window lost focus',
  internet_reachable: 'Reached the internet',
}

function FairPlay() {
  const { data: initial = [] } = useFairplay()
  const live = useLive((s) => s.flags)
  const flags = useMemo(() => {
    const seen = new Set<string>()
    return [...live, ...initial].filter((f) => (seen.has(f.id) ? false : (seen.add(f.id), true))).slice(0, 100)
  }, [live, initial])
  return (
    <Panel title="Fair play flags" bodyClass="p-0 max-h-96 overflow-y-auto">
      {flags.length === 0 ? (
        <Empty>No flags. All quiet.</Empty>
      ) : (
        <ul className="divide-y divide-steel text-sm">
          {flags.map((f) => (
            <li key={f.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
              <span>
                <span className={f.kind === 'internet_reachable' ? 'text-alert' : 'text-amber'}>{f.team_name}</span>{' '}
                <span className="text-muted">{FLAG_LABELS[f.kind] ?? f.kind}</span>
                {f.detail && <span className="text-xs text-muted"> · {f.detail}</span>}
              </span>
              <span className="text-xs text-muted tabular-nums">{new Date(f.server_ts * 1000).toLocaleTimeString()}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

export function Dashboard() {
  const { data: round } = useCurrentRound()
  const { data: rounds = [] } = useRounds()
  return (
    <div className="grid min-h-full grid-cols-[440px_1fr] gap-3 p-3">
      <div className="flex flex-col gap-3">
        <Panel title="Current round">{round ? <RoundControls round={round} /> : <Empty>No rounds configured.</Empty>}</Panel>
        {round && (round.status === 'verifying' || round.status === 'review') && (
          <Panel title="Review">
            <Review round={round} />
          </Panel>
        )}
        <Panel title="Event plan" bodyClass="p-0">
          <ol className="divide-y divide-steel text-sm">
            {rounds.map((r) => (
              <li key={r.id} className="flex items-center justify-between px-4 py-2">
                <span>
                  {r.index}. {r.name} <span className="text-xs text-muted">· {r.game.name}</span>
                </span>
                <Badge status={r.status} />
              </li>
            ))}
          </ol>
        </Panel>
      </div>
      <div className="flex min-w-0 flex-col gap-3">
        <Teams />
        <FairPlay />
      </div>
    </div>
  )
}
