/**
 * Fair play signals: full screen exits, tab switches, focus loss and, when
 * enabled, a probe that flags any route to the internet. Reports are batched.
 * They are signals for invigilators; the network cut and invigilators are the
 * real controls, since a modified client could stay silent.
 */
import { useEffect, useState } from 'react'
import { Button } from '../../components/ui'
import { api } from '../../lib/api'
import { serverNow } from '../../lib/clock'
import { useClientConfig } from '../../lib/queries'

type Report = { kind: string; detail: string; client_ts: number }

const FLUSH_MS = 5000
const PROBE_MS = 15_000
const DEDUPE_MS = 2000

export function useFairplayReporting(enabled: boolean) {
  const { data: config } = useClientConfig()

  useEffect(() => {
    if (!enabled) return
    const queue: Report[] = []
    const last: Record<string, number> = {}
    const report = (kind: string, detail = '') => {
      const now = Date.now()
      if (now - (last[kind] ?? 0) < DEDUPE_MS) return
      last[kind] = now
      queue.push({ kind, detail, client_ts: serverNow() / 1000 })
    }

    const onFullscreen = () => {
      if (!document.fullscreenElement) report('fullscreen_exit')
    }
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') report('tab_hidden')
    }
    const onBlur = () => report('focus_lost')
    document.addEventListener('fullscreenchange', onFullscreen)
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('blur', onBlur)

    const flush = setInterval(async () => {
      if (!queue.length) return
      const batch = queue.splice(0, queue.length)
      try {
        const { error } = await api.POST('/api/v1/fairplay/events', { body: { events: batch } })
        if (error) throw error
      } catch {
        queue.unshift(...batch) // try again on the next flush
      }
    }, FLUSH_MS)

    let probe: ReturnType<typeof setInterval> | undefined
    if (config?.probe_internet) {
      probe = setInterval(async () => {
        try {
          await fetch(`${config.probe_url}?t=${Date.now()}`, { mode: 'no-cors', cache: 'no-store', signal: AbortSignal.timeout(3000) })
          report('internet_reachable', config.probe_url)
        } catch {
          // unreachable is what we want
        }
      }, PROBE_MS)
    }

    return () => {
      document.removeEventListener('fullscreenchange', onFullscreen)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('blur', onBlur)
      clearInterval(flush)
      clearInterval(probe)
    }
  }, [enabled, config])
}

export function FullscreenBanner() {
  const [full, setFull] = useState(() => !!document.fullscreenElement)
  useEffect(() => {
    const on = () => setFull(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', on)
    return () => document.removeEventListener('fullscreenchange', on)
  }, [])
  if (full) return null
  return (
    <div className="flex items-center justify-center gap-4 border-b border-amber/40 bg-amber/10 px-4 py-1.5 text-xs text-amber">
      Work in full screen. Leaving it, switching tabs or losing focus is reported to the invigilators.
      <Button className="!px-2 !py-0.5" onClick={() => document.documentElement.requestFullscreen().catch(() => {})}>
        Enter full screen
      </Button>
    </div>
  )
}
