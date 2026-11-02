import { useQuery } from '@tanstack/react-query'
import { api, unwrap } from './api'
import { useAuth } from './auth'

const useLoggedIn = () => useAuth((s) => !!s.session)

export const useCurrentRound = () =>
  useQuery({ queryKey: ['round', 'current'], enabled: useLoggedIn(), queryFn: async () => unwrap(await api.GET('/api/v1/rounds/current')) })

export const useRounds = () =>
  useQuery({ queryKey: ['rounds'], queryFn: async () => unwrap(await api.GET('/api/v1/rounds')) })

export const useTeams = () =>
  useQuery({ queryKey: ['teams'], queryFn: async () => unwrap(await api.GET('/api/v1/teams')) })

export const useCountries = () =>
  useQuery({ queryKey: ['countries'], queryFn: async () => unwrap(await api.GET('/api/v1/countries')) })

export const useSubmissions = () =>
  useQuery({ queryKey: ['submissions'], queryFn: async () => unwrap(await api.GET('/api/v1/submissions')) })

export const useBots = () =>
  useQuery({
    queryKey: ['bots'],
    queryFn: async () => unwrap(await api.GET('/api/v1/practice/bots')),
    staleTime: Infinity,
  })

export const useStandings = (roundId: string | undefined, enabled = true) =>
  useQuery({
    queryKey: ['standings', roundId],
    enabled: !!roundId && enabled,
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/rounds/{round_id}/standings', { params: { path: { round_id: roundId! } } })),
  })

export const useMatches = (roundId: string | undefined) =>
  useQuery({
    queryKey: ['matches', roundId],
    enabled: !!roundId,
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/rounds/{round_id}/matches', { params: { path: { round_id: roundId! } } })),
  })

export const useReplay = (matchId: string | undefined) =>
  useQuery({
    queryKey: ['replay', matchId],
    enabled: !!matchId,
    staleTime: Infinity,
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/matches/{match_id}/replay', { params: { path: { match_id: matchId! } } })),
  })

export const useAdminTeams = () =>
  useQuery({
    queryKey: ['admin', 'teams'],
    queryFn: async () => unwrap(await api.GET('/api/v1/admin/teams')),
    refetchInterval: 10_000,
  })

export const useReview = (roundId: string | undefined) =>
  useQuery({
    queryKey: ['review', roundId],
    enabled: !!roundId,
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/admin/rounds/{round_id}/review', { params: { path: { round_id: roundId! } } })),
  })

export const useFairplay = () =>
  useQuery({ queryKey: ['admin', 'fairplay'], queryFn: async () => unwrap(await api.GET('/api/v1/admin/fairplay')) })

export const useClientConfig = () =>
  useQuery({ queryKey: ['config'], enabled: useLoggedIn(), queryFn: async () => unwrap(await api.GET('/api/v1/config')), staleTime: Infinity })
