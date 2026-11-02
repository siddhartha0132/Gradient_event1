/**
 * Live state fed by the WebSocket: the match feed for the map and ticker, the
 * latest published standings, fair play flags and toasts. Server data that has
 * a REST endpoint is refreshed through TanStack Query instead.
 */
import type { QueryClient } from '@tanstack/react-query'
import { create } from 'zustand'
import type { Schemas } from './api'
import type { Envelope } from './realtime'

export type LiveMatch = {
  match: Schemas['MatchOut']
  moves_a: string
  moves_b: string
  at: number
}

export type Published = {
  round: Schemas['RoundOut']
  standings: Schemas['StandingOut'][]
  eliminated: string[]
  champion: string | null
  at: number
}

export type Toast = { id: number; tone: 'info' | 'good' | 'bad'; text: string }

type LiveState = {
  feed: LiveMatch[]
  published: Published | null
  flags: Schemas['FairplayOut'][]
  toasts: Toast[]
  toast: (tone: Toast['tone'], text: string) => void
  dismiss: (id: number) => void
}

const FEED_LIMIT = 400
let toastId = 0

export const useLive = create<LiveState>((set) => ({
  feed: [],
  published: null,
  flags: [],
  toasts: [],
  toast: (tone, text) => {
    const id = ++toastId
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, tone, text }] }))
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 6000)
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

/** Share of defections in a set of moves, 0..1. */
export function defectionRate(moves: string[]): number | null {
  let d = 0
  let n = 0
  for (const m of moves) {
    n += m.length
    for (const c of m) if (c === 'D') d++
  }
  return n ? d / n : null
}

/** 5 = peace, 1 = war. */
export const defconLevel = (rate: number | null) => (rate === null ? 5 : Math.max(1, 5 - Math.floor(rate * 5)))

export function handleEvent(message: Envelope, queries: QueryClient, myTeamId?: string | null) {
  const p = message.payload as Record<string, unknown>
  const live = useLive.getState()
  switch (message.type) {
    case 'round.status':
    case 'window.updated': {
      const round = p.round as Schemas['RoundOut']
      queries.setQueryData(['round', 'current'], (old: Schemas['RoundOut'] | null | undefined) =>
        !old || old.index <= round.index ? round : old,
      )
      queries.invalidateQueries({ queryKey: ['rounds'] })
      queries.invalidateQueries({ queryKey: ['review'] })
      if (message.type === 'round.status' && round.status === 'running') useLive.setState({ feed: [] })
      break
    }
    case 'team.updated':
      queries.invalidateQueries({ queryKey: ['teams'] })
      queries.invalidateQueries({ queryKey: ['countries'] })
      break
    case 'submission.result': {
      const s = p.submission as Schemas['SubmissionOut']
      queries.invalidateQueries({ queryKey: ['submissions'] })
      queries.invalidateQueries({ queryKey: ['admin', 'teams'] })
      if (message.seq && Date.now() / 1000 - message.ts < 30) {
        live.toast(s.status === 'accepted' ? 'good' : 'bad', `Version ${s.version} ${s.status}`)
      }
      break
    }
    case 'match.done': {
      const entry = { match: p.match as Schemas['MatchOut'], moves_a: p.moves_a as string, moves_b: p.moves_b as string, at: Date.now() }
      useLive.setState((s) => ({ feed: [...s.feed.slice(-(FEED_LIMIT - 1)), entry] }))
      queries.setQueryData(['round', 'current'], (old: Schemas['RoundOut'] | null | undefined) =>
        old && old.id === entry.match.round_id ? { ...old, matches_done: old.matches_done + 1 } : old,
      )
      if (myTeamId && (entry.match.team_a === myTeamId || entry.match.team_b === myTeamId)) {
        queries.invalidateQueries({ queryKey: ['matches'] })
      }
      break
    }
    case 'standings.published': {
      useLive.setState({ published: { ...(p as Omit<Published, 'at'>), at: Date.now() } })
      for (const key of ['teams', 'rounds', 'round', 'standings', 'matches', 'countries', 'admin']) {
        queries.invalidateQueries({ queryKey: [key] })
      }
      break
    }
    case 'fairplay.flag':
      useLive.setState((s) => ({ flags: [p.flag as Schemas['FairplayOut'], ...s.flags].slice(0, 200) }))
      queries.invalidateQueries({ queryKey: ['admin', 'teams'] })
      break
    case 'penalty.issued':
      live.toast('bad', `Penalty: ${p.points} points. ${p.reason}`)
      break
    case 'job.dead':
      queries.invalidateQueries({ queryKey: ['review'] })
      break
  }
}
