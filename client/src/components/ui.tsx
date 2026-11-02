import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { formatDuration, useServerNow, windowRemaining } from '../lib/clock'
import { defconLevel, useLive } from '../lib/live'
import { useConnection } from '../lib/realtime'
import type { Schemas } from '../lib/api'

export function Panel({
  title,
  right,
  className = '',
  bodyClass = 'p-4',
  children,
}: {
  title?: ReactNode
  right?: ReactNode
  className?: string
  bodyClass?: string
  children: ReactNode
}) {
  return (
    <section className={`relative flex flex-col border border-steel bg-panel/90 shadow-[0_0_0_1px_#000,0_10px_30px_-10px_#000] ${className}`}>
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-steel bg-steel/40 px-4 py-2">
          <h2 className="label !text-paper">{title}</h2>
          {right}
        </header>
      )}
      <div className={`min-h-0 flex-1 ${bodyClass}`}>{children}</div>
    </section>
  )
}

const BUTTON_STYLES = {
  primary: 'bg-alert text-white border-alert hover:bg-[#ff3b52] shadow-[0_0_20px_-4px_var(--color-alert)]',
  ghost: 'bg-transparent text-paper border-steel-light hover:border-paper',
  danger: 'bg-transparent text-alert border-alert-dim hover:border-alert',
}

export function Button({
  variant = 'ghost',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof BUTTON_STYLES }) {
  return (
    <button
      className={`cursor-pointer border px-4 py-2 font-mono text-xs font-semibold uppercase tracking-widest transition disabled:cursor-not-allowed disabled:opacity-40 ${BUTTON_STYLES[variant]} ${className}`}
      {...props}
    />
  )
}

export const inputClass =
  'w-full border border-steel-light bg-ink px-3 py-2 font-mono text-sm text-paper outline-none focus:border-alert'

const STATUS_TONE: Record<string, string> = {
  accepted: 'text-coop border-coop/50',
  advanced: 'text-coop border-coop/50',
  published: 'text-coop border-coop/50',
  rejected: 'text-alert border-alert-dim',
  eliminated: 'text-alert border-alert-dim',
  disqualified: 'text-alert border-alert-dim',
  failed: 'text-alert border-alert-dim',
  forfeit: 'text-alert border-alert-dim',
  absent: 'text-muted border-steel-light',
  checking: 'text-amber border-amber/50',
  open: 'text-amber border-amber/50',
  running: 'text-amber border-amber/50',
  verifying: 'text-amber border-amber/50',
  review: 'text-peace border-peace/50',
  locked: 'text-paper border-steel-light',
  draft: 'text-muted border-steel-light',
}

export function Badge({ status }: { status: string }) {
  return (
    <span className={`inline-block border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest ${STATUS_TONE[status] ?? 'text-muted border-steel'}`}>
      {status}
    </span>
  )
}

export function Countdown({ round, large = false }: { round: Schemas['RoundOut'] | null | undefined; large?: boolean }) {
  const now = useServerNow()
  const left = windowRemaining(round, now)
  if (!left) return <span className="label">{round ? `Round ${round.index}: ${round.status}` : 'No round'}</span>
  const urgent = !left.paused && left.seconds < 60
  return (
    <span className="flex items-baseline gap-2">
      <span className="label">{left.paused ? 'Paused' : 'Window closes'}</span>
      <span
        className={`font-bold tabular-nums ${large ? 'text-4xl' : 'text-lg'} ${left.paused ? 'text-muted' : urgent ? 'text-alert' : 'text-amber'} ${urgent ? 'blink' : ''}`}
      >
        {formatDuration(left.seconds)}
      </span>
    </span>
  )
}

export function ConnectionStatus() {
  const status = useConnection((s) => s.status)
  const tone = status === 'connected' ? 'bg-coop' : status === 'offline' ? 'bg-alert' : 'bg-amber blink'
  return (
    <span className="flex items-center gap-2" title="Live connection to the Command Server">
      <span className={`h-2 w-2 rounded-full ${tone}`} />
      <span className="label !text-[10px]">{status}</span>
    </span>
  )
}

export function Defcon({ rate }: { rate: number | null }) {
  const level = defconLevel(rate)
  const colors = ['', 'text-alert', 'text-[#fd9644]', 'text-amber', 'text-coop', 'text-peace']
  return (
    <span className="flex items-center gap-2 border border-steel px-3 py-1" title="Share of defections in live matches">
      <span className="label !text-[10px]">Defcon</span>
      <span className={`text-xl font-bold ${colors[level]}`}>{level}</span>
    </span>
  )
}

export function Toasts() {
  const toasts = useLive((s) => s.toasts)
  const dismiss = useLive((s) => s.dismiss)
  const tone = { info: 'border-steel-light', good: 'border-coop text-coop', bad: 'border-alert text-alert' }
  return (
    <div className="fixed right-4 bottom-4 z-40 flex w-80 flex-col gap-2">
      {toasts.map((t) => (
        <button key={t.id} onClick={() => dismiss(t.id)} className={`border bg-panel px-4 py-3 text-left text-sm ${tone[t.tone]}`}>
          {t.text}
        </button>
      ))}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted">{children}</p>
}
