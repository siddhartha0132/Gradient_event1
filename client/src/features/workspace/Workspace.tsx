import Editor, { type OnMount } from '@monaco-editor/react'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Badge, Button, Countdown, Empty, Panel, inputClass } from '../../components/ui'
import { ApiError, api, unwrap, type Schemas } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { useLive } from '../../lib/live'
import { useBots, useCurrentRound, useSubmissions } from '../../lib/queries'
import { BlockEditor } from '../blocks/BlockEditor'
import { CATEGORY_INFO, countBlocks, moduleName, newModule, type Layout } from '../blocks/blocks'
import { TEMPLATE, loadDraft, saveDraft, type Agent } from './drafts'
import { monaco, setModuleNames } from './monaco'

const AUTOSAVE_MS = 3000
const VALIDATE_DEBOUNCE_MS = 600

const toBody = (agent: Agent) => ({ hand_code: agent.hand_code, modules: agent.modules.map((layout) => ({ layout })) })

export function MoveStrip({ moves, max = 200 }: { moves: string; max?: number }) {
  return (
    <div className="flex flex-wrap gap-px">
      {[...moves.slice(0, max)].map((m, i) => (
        <span key={i} className={`h-2 w-2 ${m === 'C' ? 'bg-coop' : 'bg-alert'}`} title={`Turn ${i + 1}: ${m}`} />
      ))}
    </div>
  )
}

/** The server builds the agent as the team edits: errors, generated module code and the round's rules. */
function useValidation(agent: Agent | null, editor: Parameters<OnMount>[0] | null) {
  const [result, setResult] = useState<Schemas['ValidateOut'] | null>(null)
  useEffect(() => {
    if (!agent) return
    const id = setTimeout(async () => {
      try {
        setResult(unwrap(await api.POST('/api/v1/practice/validate', { body: toBody(agent) })))
      } catch {
        // offline: the next submission is checked on the server anyway
      }
    }, VALIDATE_DEBOUNCE_MS)
    return () => clearTimeout(id)
  }, [agent])

  const codeErrors = useMemo(() => result?.errors.filter((e) => e.module === null) ?? [], [result])
  useEffect(() => {
    const model = editor?.getModel()
    if (!model) return
    monaco.editor.setModelMarkers(
      model,
      'sandbox',
      codeErrors.map((e) => {
        const line = Math.min(Math.max(e.line ?? 1, 1), model.getLineCount())
        return {
          severity: monaco.MarkerSeverity.Error,
          message: e.message,
          startLineNumber: line,
          endLineNumber: line,
          startColumn: 1,
          endColumn: model.getLineMaxColumn(line),
        }
      }),
    )
  }, [codeErrors, editor])
  return result
}

/** Submit with an idempotency key, retrying network failures with the same key so nothing is stored twice. */
async function submitAgent(agent: Agent) {
  const key = crypto.randomUUID()
  for (let attempt = 0; ; attempt++) {
    try {
      return unwrap(await api.POST('/api/v1/submissions', { body: toBody(agent), headers: { 'Idempotency-Key': key } }))
    } catch (err) {
      if (err instanceof ApiError || attempt >= 2) throw err
      await new Promise((r) => setTimeout(r, 500 * (attempt + 1)))
    }
  }
}

function Practice({ agent }: { agent: Agent }) {
  const { data: bots = [] } = useBots()
  const [opponent, setOpponent] = useState('tit_for_tat')
  const [game, setGame] = useState('prisoners_dilemma')
  const [turns, setTurns] = useState(50)
  const [noise, setNoise] = useState(0)
  const [result, setResult] = useState<Schemas['PracticeOut'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true)
    setError(null)
    try {
      setResult(unwrap(await api.POST('/api/v1/practice/simulate', { body: { ...toBody(agent), opponent, game, turns, noise } })))
    } catch (err) {
      setResult(null)
      setError(err instanceof ApiError ? err.message : 'Simulation failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title="Side simulation">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-2">
          <select className={inputClass} value={opponent} onChange={(e) => setOpponent(e.target.value)}>
            <option value="self">A copy of yourself</option>
            {bots.map((b) => (
              <option key={b.key} value={b.key} title={b.description}>
                {b.key}
              </option>
            ))}
          </select>
          <select className={inputClass} value={game} onChange={(e) => setGame(e.target.value)}>
            <option value="prisoners_dilemma">Prisoner's Dilemma</option>
            <option value="chicken">Chicken</option>
            <option value="stag_hunt">Stag Hunt</option>
          </select>
          <label className="flex items-center gap-2 text-xs text-muted">
            Turns
            <input className={inputClass} type="number" min={1} max={500} value={turns} onChange={(e) => setTurns(Number(e.target.value))} />
          </label>
          <label className="flex items-center gap-2 text-xs text-muted">
            Noise
            <input className={inputClass} type="number" min={0} max={0.5} step={0.01} value={noise} onChange={(e) => setNoise(Number(e.target.value))} />
          </label>
        </div>
        <Button onClick={run} disabled={busy}>
          {busy ? 'Simulating…' : 'Run practice match'}
        </Button>
        {error && <p className="text-sm text-alert">{error}</p>}
        {result && (
          <div className="flex flex-col gap-2 text-sm">
            {result.forfeit && <p className="text-alert">{result.forfeit}</p>}
            <div className="flex justify-between">
              <span>You</span>
              <span className="font-bold tabular-nums">{result.score}</span>
            </div>
            <MoveStrip moves={result.my_moves} />
            <div className="flex justify-between">
              <span>{opponent === 'self' ? 'Copy' : opponent}</span>
              <span className="font-bold tabular-nums">{result.opponent_score}</span>
            </div>
            <MoveStrip moves={result.opponent_moves} />
          </div>
        )}
      </div>
    </Panel>
  )
}

function History({ onLoad }: { onLoad: (agent: Agent) => void }) {
  const { data: submissions = [] } = useSubmissions()
  const [open, setOpen] = useState<string | null>(null)

  async function load(id: string) {
    const detail = unwrap(await api.GET('/api/v1/submissions/{submission_id}', { params: { path: { submission_id: id } } }))
    onLoad({ hand_code: detail.hand_code, modules: detail.modules.map((m) => m.layout as Layout) })
  }

  return (
    <Panel title="Version history" bodyClass="p-0">
      {submissions.length === 0 ? (
        <Empty>No submissions yet.</Empty>
      ) : (
        <ul className="divide-y divide-steel">
          {submissions.map((s) => (
            <li key={s.id} className="px-4 py-2 text-sm">
              <div className="flex items-center justify-between gap-2">
                <button className="cursor-pointer text-left" onClick={() => setOpen(open === s.id ? null : s.id)}>
                  <span className="font-bold">v{s.version}</span>
                  <span className="ml-2 text-xs text-muted">{new Date(s.created_at * 1000).toLocaleTimeString()}</span>
                  {s.module_count > 0 && <span className="ml-2 text-xs text-muted">· {s.module_count} module{s.module_count > 1 ? 's' : ''}</span>}
                </button>
                <span className="flex items-center gap-2">
                  <Badge status={s.status} />
                  <button className="label cursor-pointer !text-[10px] hover:!text-paper" onClick={() => load(s.id)}>
                    Load
                  </button>
                </span>
              </div>
              {s.rule_problems.length > 0 && <p className="mt-1 text-xs text-amber">Cannot play this round: {s.rule_problems[0]}</p>}
              {open === s.id && (
                <div className="mt-2 flex flex-col gap-1 text-xs">
                  {s.errors.map((e, i) => (
                    <p key={i} className="text-alert">
                      {e}
                    </p>
                  ))}
                  {s.test_results.map((t) => (
                    <p key={t.opponent} className="flex justify-between text-muted">
                      <span>vs {t.opponent}</span>
                      <span className="tabular-nums">
                        {t.score} – {t.opponent_score}
                      </span>
                    </p>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

type Tab = 'code' | number

export function Workspace() {
  const team = useAuth((s) => s.session!.user.team!)
  const { data: round } = useCurrentRound()
  const { data: submissions } = useSubmissions()
  const toast = useLive((s) => s.toast)
  const queries = useQueryClient()
  const [agent, setAgent] = useState<Agent | null>(null)
  const [tab, setTab] = useState<Tab>('code')
  const [moduleKeys, setModuleKeys] = useState<string[]>([])
  const [editor, setEditor] = useState<Parameters<OnMount>[0] | null>(null)
  const [busy, setBusy] = useState(false)
  const saved = useRef<Agent | null>(null)
  const build = useValidation(agent, editor)

  const rules = round?.block_rules ?? { max_modules: 0, max_blocks: 1, categories: [] }
  const names = useMemo(() => agent?.modules.map(moduleName) ?? [], [agent])
  useEffect(() => setModuleNames(names), [names])

  function load(next: Agent) {
    setAgent(next)
    setModuleKeys(next.modules.map(() => crypto.randomUUID()))
    setTab('code')
  }

  // Restore: the autosaved draft, else the latest submitted version, else the template
  useEffect(() => {
    if (agent !== null || submissions === undefined) return
    ;(async () => {
      const draft = await loadDraft(team.id)
      if (draft !== undefined) return load(draft)
      const latest = submissions[0]
      if (latest) {
        const detail = unwrap(await api.GET('/api/v1/submissions/{submission_id}', { params: { path: { submission_id: latest.id } } }))
        return load({ hand_code: detail.hand_code, modules: detail.modules.map((m) => m.layout as Layout) })
      }
      load({ hand_code: TEMPLATE, modules: [] })
    })()
  }, [agent, submissions, team.id])

  useEffect(() => {
    const id = setInterval(() => {
      if (agent !== null && agent !== saved.current) {
        saved.current = agent
        saveDraft(team.id, agent)
      }
    }, AUTOSAVE_MS)
    return () => clearInterval(id)
  }, [agent, team.id])

  const setModule = (index: number, layout: Layout) =>
    setAgent((a) => a && { ...a, modules: a.modules.map((m, i) => (i === index ? layout : m)) })

  function addModule() {
    if (!agent) return
    setAgent({ ...agent, modules: [...agent.modules, newModule(names)] })
    setModuleKeys((k) => [...k, crypto.randomUUID()])
    setTab(agent.modules.length)
  }

  function removeModule(index: number) {
    if (!agent || !confirm(`Delete the module '${names[index]}'?`)) return
    setAgent({ ...agent, modules: agent.modules.filter((_, i) => i !== index) })
    setModuleKeys((k) => k.filter((_, i) => i !== index))
    setTab('code')
  }

  const errors = build?.errors ?? []
  const fallen = team.eliminated_in != null
  const canSubmit = !!round?.window_open && !fallen && !busy && agent !== null && errors.length === 0

  async function submit() {
    if (agent === null) return
    setBusy(true)
    try {
      const s = await submitAgent(agent)
      toast('info', `Version ${s.version} received. Testing in the sandbox…`)
      queries.invalidateQueries({ queryKey: ['submissions'] })
    } catch (err) {
      const detail = err instanceof ApiError && Array.isArray(err.details.errors) ? `: ${(err.details.errors[0] as { message: string }).message}` : ''
      toast('bad', err instanceof ApiError ? err.message + detail : 'Could not reach the server. Your draft is saved locally.')
    } finally {
      setBusy(false)
    }
  }

  const accepted = submissions?.find((s) => s.status === 'accepted')
  const activeModule = typeof tab === 'number' && agent && tab < agent.modules.length ? tab : null
  const moduleErrors = (i: number) => errors.filter((e) => e.module === i)
  const generalErrors = errors.filter((e) => e.module === null && e.line === null && e.kind === 'blocks')

  const tabs = (
    <div className="flex items-stretch gap-px overflow-x-auto border-b border-steel bg-steel/40">
      <button
        onClick={() => setTab('code')}
        className={`cursor-pointer px-4 py-2 text-xs font-bold tracking-widest uppercase ${tab === 'code' ? 'bg-panel text-paper' : 'text-muted hover:text-paper'}`}
      >
        strategy.py
        {errors.some((e) => e.module === null && e.kind === 'code') && <span className="ml-2 text-alert">●</span>}
      </button>
      {agent?.modules.map((layout, i) => {
        const blocks = countBlocks(layout)
        return (
          <button
            key={moduleKeys[i]}
            onClick={() => setTab(i)}
            className={`flex cursor-pointer items-center gap-2 px-4 py-2 text-xs font-bold tracking-wider ${tab === i ? 'bg-panel text-paper' : 'text-muted hover:text-paper'}`}
          >
            <span className="text-alert">▦</span>
            {names[i]}
            <span className={`font-normal tabular-nums ${blocks > rules.max_blocks ? 'text-alert' : 'text-muted'}`}>
              {blocks}/{rules.max_blocks}
            </span>
            {moduleErrors(i).length > 0 && <span className="text-alert">●</span>}
          </button>
        )
      })}
      <button
        onClick={addModule}
        disabled={!agent || agent.modules.length >= rules.max_modules}
        title={rules.max_modules ? `This round allows ${rules.max_modules} block module(s)` : 'Block modules are off this round'}
        className="cursor-pointer px-4 py-2 text-xs font-bold tracking-widest text-amber uppercase hover:text-paper disabled:cursor-not-allowed disabled:text-steel-light"
      >
        + Block module
      </button>
      <span className="ml-auto flex items-center px-4 text-[11px] whitespace-nowrap text-muted">
        {errors.length ? <span className="text-alert">{errors.length} problem{errors.length > 1 ? 's' : ''}</span> : <span className="text-coop">Passes all checks</span>}
      </span>
    </div>
  )

  return (
    <div className="grid h-full grid-cols-[1fr_380px] gap-3 p-3">
      <section className="flex min-h-0 flex-col border border-steel bg-panel/90">
        {tabs}
        {generalErrors.map((e, i) => (
          <p key={i} className="border-b border-alert-dim bg-alert/10 px-4 py-1.5 text-xs text-alert">
            {e.message}
          </p>
        ))}
        <div className="relative min-h-0 flex-1">
          {agent === null ? (
            <Empty>Loading your workspace…</Empty>
          ) : (
            <>
              {/* Monaco stays mounted so its undo history survives tab switches */}
              <div className={`absolute inset-0 ${activeModule === null ? '' : 'invisible'}`}>
                <Editor
                  language="python"
                  theme="iron"
                  value={agent.hand_code}
                  onChange={(v) => setAgent((a) => a && { ...a, hand_code: v ?? '' })}
                  onMount={(e) => setEditor(e)}
                  options={{
                    fontFamily: 'JetBrains Mono, monospace',
                    fontSize: 14,
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    tabSize: 4,
                    insertSpaces: true,
                    automaticLayout: true,
                  }}
                />
              </div>
              {activeModule !== null && (
                <div className="absolute inset-0 flex flex-col">
                  <div className="min-h-0 flex-1">
                    <BlockEditor
                      key={moduleKeys[activeModule]}
                      layout={agent.modules[activeModule]}
                      onChange={(layout) => setModule(activeModule, layout)}
                      maxBlocks={rules.max_blocks}
                      categories={rules.categories}
                    />
                  </div>
                  <div className="grid max-h-56 shrink-0 grid-cols-[1fr_auto] gap-4 overflow-y-auto border-t border-steel bg-ink/80 p-3">
                    <div className="min-w-0">
                      <span className="label !text-[10px]">Generated Python · call it from strategy.py as {names[activeModule]}(my_history, opp_history)</span>
                      {moduleErrors(activeModule).map((e, i) => (
                        <p key={i} className="mt-1 text-xs text-alert">
                          {e.message}
                        </p>
                      ))}
                      <pre className="mt-1 text-xs whitespace-pre-wrap text-coop/90">{build?.modules[activeModule]?.code ?? ''}</pre>
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <span className="text-xs text-muted tabular-nums">
                        {countBlocks(agent.modules[activeModule])} of {rules.max_blocks} blocks
                      </span>
                      <Button variant="danger" className="!px-2 !py-1" onClick={() => removeModule(activeModule)}>
                        Delete module
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </section>
      <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
        <Panel title={round ? `Round ${round.index} · ${round.name}` : 'Command'}>
          <div className="flex flex-col gap-3">
            <Countdown round={round} />
            {round && (
              <>
                <p className="text-xs text-muted">
                  {round.game.name} · {round.turns ?? 'hidden number of'} turns · noise {round.noise} · {round.repetitions} repetitions
                </p>
                <p className="text-xs text-muted">
                  Blocks:{' '}
                  {rules.max_modules
                    ? `up to ${rules.max_modules} module${rules.max_modules > 1 ? 's' : ''} of ${rules.max_blocks} blocks · ${rules.categories.map((c) => CATEGORY_INFO[c]?.label ?? c).join(', ') || 'moves only'}`
                    : 'not allowed this round'}
                </p>
              </>
            )}
            {fallen ? (
              <p className="stamp self-start text-alert">Nation fallen</p>
            ) : (
              <Button variant="primary" onClick={submit} disabled={!canSubmit}>
                {busy ? 'Transmitting…' : round?.window_open ? 'Submit strategy' : 'Submissions closed'}
              </Button>
            )}
            <p className="text-xs text-muted">
              {accepted ? `Version ${accepted.version} is your latest accepted strategy and will play when the window closes.` : 'You have no accepted strategy yet.'}
            </p>
          </div>
        </Panel>
        {agent && <Practice agent={agent} />}
        <History onLoad={load} />
      </div>
    </div>
  )
}
