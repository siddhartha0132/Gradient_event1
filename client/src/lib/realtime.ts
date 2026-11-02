/**
 * One WebSocket per client. Every message is validated with Zod. The client
 * remembers the last seq it saw and sends it on reconnect, so the server replays
 * anything missed while the connection was down.
 */
import { z } from 'zod'
import { create } from 'zustand'
import { accessToken, nextNode, refreshTokens, wsUrl } from './api'

export const Envelope = z.object({
  seq: z.number().nullable(),
  type: z.string(),
  ts: z.number(),
  payload: z.record(z.string(), z.unknown()),
})
export type Envelope = z.infer<typeof Envelope>

export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'offline'
export const useConnection = create<{ status: ConnectionStatus }>(() => ({ status: 'connecting' }))

type Listener = (message: Envelope) => void

export class Realtime {
  private ws: WebSocket | null = null
  private lastSeq: number | null = null
  private retry = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private stopped = false
  private listener: Listener

  constructor(listener: Listener) {
    this.listener = listener
  }

  start() {
    this.stopped = false
    this.connect()
  }

  stop() {
    this.stopped = true
    if (this.timer) clearTimeout(this.timer)
    this.ws?.close()
    this.ws = null
  }

  private connect() {
    const token = accessToken()
    if (!token) return
    const after = this.lastSeq === null ? '' : `&after=${this.lastSeq}`
    const ws = new WebSocket(wsUrl(`/api/v1/ws?token=${encodeURIComponent(token)}${after}`))
    this.ws = ws
    useConnection.setState({ status: this.retry ? 'reconnecting' : 'connecting' })

    ws.onopen = () => {
      this.retry = 0
      useConnection.setState({ status: 'connected' })
    }
    ws.onmessage = (event) => {
      const parsed = Envelope.safeParse(JSON.parse(event.data))
      if (!parsed.success) return
      const message = parsed.data
      if (message.type === 'hello') {
        if (this.lastSeq === null) this.lastSeq = (message.payload.head as number) ?? 0
      } else if (message.seq !== null) {
        if (this.lastSeq !== null && message.seq <= this.lastSeq) return // already seen
        this.lastSeq = message.seq
      }
      this.listener(message)
    }
    ws.onclose = async (event) => {
      if (this.ws !== ws || this.stopped) return
      this.ws = null
      if (event.code === 4401 && !(await refreshTokens())) return // logged out
      if (event.code !== 4401) nextNode()
      this.retry += 1
      useConnection.setState({ status: this.retry > 3 ? 'offline' : 'reconnecting' })
      const delay = Math.min(8000, 500 * 2 ** Math.min(this.retry - 1, 4))
      this.timer = setTimeout(() => this.connect(), delay)
    }
  }
}
