import { describe, expect, it } from 'vitest'

import { formatClockSeconds, formatDurationSeconds, parseClockToSeconds } from '@/domain/time'

describe('formatDurationSeconds', () => {
  it('formats hours, minutes and seconds from integer seconds', () => {
    expect(formatDurationSeconds(0)).toBe('0秒')
    expect(formatDurationSeconds(575)).toBe('9分35秒')
    expect(formatDurationSeconds(5400)).toBe('1小时30分')
  })

  it('returns unknown for negative or non-finite input', () => {
    expect(formatDurationSeconds(-1)).toBe('未知')
    expect(formatDurationSeconds(Number.NaN)).toBe('未知')
  })
})

describe('parseClockToSeconds', () => {
  it('parses HH:MM and HH:MM:SS', () => {
    expect(parseClockToSeconds('00:00')).toBe(0)
    expect(parseClockToSeconds('18:30')).toBe(66600)
    expect(parseClockToSeconds('23:59:59')).toBe(86399)
  })

  it('rejects invalid clock strings', () => {
    expect(parseClockToSeconds('24:00')).toBeNull()
    expect(parseClockToSeconds('18:60')).toBeNull()
    expect(parseClockToSeconds('abc')).toBeNull()
  })

  it('formats scene seconds back to clock', () => {
    expect(formatClockSeconds(66600)).toBe('18:30')
    expect(formatClockSeconds(86400 + 60)).toBe('00:01')
  })
})
