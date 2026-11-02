/**
 * Typed API client generated from the server's OpenAPI schema (npm run gen:api).
 *
 * Adds the access token, refreshes it once on a 401, and fails over between
 * server nodes: VITE_API_NODES="http://node1:8000,http://node2:8000". With no
 * nodes configured, requests go to the page's own origin.
 */
import createClient from 'openapi-fetch'
import { useAuth } from './auth'
import type { components, paths } from './schema'

export type Schemas = components['schemas']

const NODES: string[] = (import.meta.env.VITE_API_NODES ?? '')
  .split(',')
  .map((s: string) => s.trim().replace(/\/$/, ''))
  .filter(Boolean)
let activeNode = 0

const pageOrigin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin
export const apiOrigin = () => NODES[activeNode] ?? pageOrigin

function onNode(request: Request): Request {
  if (!NODES.length) return request
  const url = new URL(request.url)
  const target = new URL(apiOrigin())
  url.protocol = target.protocol
  url.host = target.host
  return new Request(url, request)
}

/** Send to the active node; on a network failure, switch to the next node and retry. */
async function failoverFetch(request: Request): Promise<Response> {
  const attempts = Math.max(1, NODES.length)
  let lastError: unknown
  for (let i = 0; i < attempts; i++) {
    try {
      return await fetch(onNode(request.clone()))
    } catch (error) {
      lastError = error
      if (NODES.length > 1) activeNode = (activeNode + 1) % NODES.length
    }
  }
  throw lastError
}

let refreshing: Promise<boolean> | null = null

async function refreshTokens(): Promise<boolean> {
  const session = useAuth.getState().session
  if (!session) return false
  refreshing ??= (async () => {
    try {
      const response = await failoverFetch(
        new Request(`${pageOrigin}/api/v1/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: session.refresh }),
        }),
      )
      if (!response.ok) {
        useAuth.getState().logout()
        return false
      }
      const pair = (await response.json()) as Schemas['TokenPair']
      useAuth.getState().setSession({ access: pair.access_token, refresh: pair.refresh_token, user: pair.user })
      return true
    } finally {
      refreshing = null
    }
  })()
  return refreshing
}

export const accessToken = () => useAuth.getState().session?.access

async function authedFetch(input: Request): Promise<Response> {
  const withToken = () => {
    const request = input.clone()
    const token = accessToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  }
  const response = await failoverFetch(withToken())
  if (response.status === 401 && !input.url.includes('/auth/') && (await refreshTokens())) {
    return failoverFetch(withToken())
  }
  return response
}

export const api = createClient<paths>({ baseUrl: pageOrigin, fetch: authedFetch })

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details: Record<string, unknown> = {},
  ) {
    super(message)
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response }

/** Return the data or throw an ApiError carrying the server's stable error code. */
export function unwrap<T>(result: Result<T>): T {
  if (result.error !== undefined || result.data === undefined) {
    const body = result.error as { error?: { code: string; message: string; details?: Record<string, unknown> } }
    const e = body?.error
    throw new ApiError(e?.code ?? 'UNKNOWN', e?.message ?? 'Something went wrong', result.response.status, e?.details)
  }
  return result.data
}

export function wsUrl(path: string): string {
  const url = new URL(path, apiOrigin())
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

/** Called when a WebSocket is refused; switches node so the next attempt tries elsewhere. */
export function nextNode() {
  if (NODES.length > 1) activeNode = (activeNode + 1) % NODES.length
}

export { refreshTokens }
