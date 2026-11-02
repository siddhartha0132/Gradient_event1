import { describe, expect, it } from 'vitest'
import { formatDuration, offsetFrom, windowRemaining } from './clock'
import { defconLevel, defectionRate } from './live'

describe('clock sync', () => {
  it('uses the midpoint of the round trip', () => {
    // sent at 1000, server says 5050, received at 1100: midpoint 1050, so 4000 ms ahead
    expect(offsetFrom(1000, 5050, 1100)).toBe(4000)
  })

  it('counts down from server time and freezes while paused', () => {
    const open = { status: 'open', closes_at: 100, paused_remaining: null }
    expect(windowRemaining(open, 40_000)).toEqual({ seconds: 60, paused: false })
    expect(windowRemaining(open, 200_000)).toEqual({ seconds: 0, paused: false })
    expect(windowRemaining({ ...open, paused_remaining: 42 }, 999_999)).toEqual({ seconds: 42, paused: true })
    expect(windowRemaining({ ...open, status: 'locked' }, 0)).toBeNull()
  })

  it('formats durations', () => {
    expect(formatDuration(65)).toBe('01:05')
    expect(formatDuration(3725)).toBe('1:02:05')
  })
})

describe('defcon', () => {
  it('maps defection share to a level', () => {
    expect(defectionRate(['CCCC', 'CCCC'])).toBe(0)
    expect(defectionRate(['DDDD', 'CCCC'])).toBe(0.5)
    expect(defconLevel(0)).toBe(5)
    expect(defconLevel(0.5)).toBe(3)
    expect(defconLevel(1)).toBe(1)
    expect(defconLevel(null)).toBe(5)
  })
})
