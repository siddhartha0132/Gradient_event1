import { create } from 'zustand'
import type { Schemas } from './api'

type Session = { access: string; refresh: string; user: Schemas['UserOut'] }

type AuthState = {
  session: Session | null
  setSession: (session: Session) => void
  setUser: (user: Schemas['UserOut']) => void
  logout: () => void
}

const KEY = 'ic.session'

function load(): Session | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Session) : null
  } catch {
    return null
  }
}

function save(session: Session | null) {
  try {
    if (session) localStorage.setItem(KEY, JSON.stringify(session))
    else localStorage.removeItem(KEY)
  } catch {
    // storage may be blocked; the session then lasts until reload
  }
}

export const useAuth = create<AuthState>((set, get) => ({
  session: load(),
  setSession: (session) => {
    save(session)
    set({ session })
  },
  setUser: (user) => {
    const current = get().session
    if (!current) return
    const session = { ...current, user }
    save(session)
    set({ session })
  },
  logout: () => {
    save(null)
    set({ session: null })
  },
}))

export const isStaff = (role?: string) => role === 'organiser' || role === 'admin'
