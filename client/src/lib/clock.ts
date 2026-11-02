/**
 * Server clock sync. The client measures the round trip to GET /clock and takes
 * the offset as server time minus the midpoint. Countdowns are always drawn from
 * server time; deadlines are only enforced on the server.
 */
import { useEffect, useState } from 'react'
import { create } from 'zustand'
import { api, unwrap } from './api'

export const useClock = create<{ offset: number }>(() => ({ offset: 0 }))

export function offsetFrom(sentAt: number, serverMs: number, receivedAt: number) {
  return serverMs - (sentAt + receivedAt) / 2
}

export async function syncClock() {
  const sentAt = Date.now()
  const { server_time } = unwrap(await api.GET('/api/v1/clock'))
  useClock.setState({ offset: offsetFrom(sentAt, server_time * 1000, Date.now()) })
}

export const serverNow = () => Date.now() + useClock.getState().offset

export function useServerNow(intervalMs = 250) {
  const [now, setNow] = useState(serverNow)
  useEffect(() => {
    const id = setInterval(() => setNow(serverNow()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

/** Seconds left in a round's window, or null when no window is running. */
export function windowRemaining(
  round: { status: string; closes_at: number | null; paused_remaining: number | null } | null | undefined,
  nowMs: number,
): { seconds: number; paused: boolean } | null {
  if (!round || round.status !== 'open') return null
  if (round.paused_remaining !== null) return { seconds: round.paused_remaining, paused: true }
  if (round.closes_at === null) return null
  return { seconds: Math.max(0, round.closes_at - nowMs / 1000), paused: false }
}

export function formatDuration(seconds: number) {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const pad = (n: number) => String(n).padStart(2, '0')
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`
}
