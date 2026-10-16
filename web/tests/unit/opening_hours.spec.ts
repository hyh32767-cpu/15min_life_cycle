import { describe, expect, it } from 'vitest'

import { parseHoursText, parseStructuredHours, resolveOpeningWindows } from '@/domain/openingHours'

describe('opening hours', () => {
  it('parses structured multi-segment windows first', () => {
    const resolved = resolveOpeningWindows(
      [{ open: '08:00', close: '12:00' }, { open: '14:00', close: '22:00' }],
      '08:00-22:00',
    )
    expect(resolved.source).toBe('structured')
    expect(resolved.windows).toHaveLength(2)
    expect(resolved.windows[1]).toEqual({ opensSeconds: 50400, closesSeconds: 79200, source: 'structured' })
  })

  it('keeps overnight windows for backend OpeningWindow', () => {
    const resolved = resolveOpeningWindows([{ open: '20:00', close: '02:00' }], null)
    expect(resolved.windows[0].opensSeconds).toBe(72000)
    expect(resolved.windows[0].closesSeconds).toBe(7200)
  })

  it('falls back to text single segment, else unknown', () => {
    expect(resolveOpeningWindows(null, '09:00-18:00').source).toBe('text')
    expect(resolveOpeningWindows(null, '全天营业').source).toBe('unknown')
    expect(resolveOpeningWindows(null, null).windows).toEqual([])
    expect(parseHoursText('24小时')).toEqual([])
  })

  it('accepts numeric seconds structured entries', () => {
    expect(parseStructuredHours([{ open: 28800, close: 64800 }])).toEqual([
      { opensSeconds: 28800, closesSeconds: 64800, source: 'structured' },
    ])
  })
})

describe('F43 regular_open_hour periods', () => {
  it('normalizes nested open/close objects per weekday', async () => {
    const { parseRegularOpenPeriods, resolveOpeningWindows } = await import('@/domain/openingHours')
    const periods = [
      { open: { day: 1, hour: 7, minute: 0 }, close: { day: 2, hour: 0, minute: 0 } },
      { open: { day: 2, hour: 7, minute: 0 }, close: { day: 3, hour: 0, minute: 0 } },
    ]
    const parsed = parseRegularOpenPeriods(periods)
    expect(parsed).toHaveLength(2)
    expect(parsed[0]).toMatchObject({ day: 1, closeDay: 2, opensSeconds: 25200, closesSeconds: 0 })
    // 有星期才生效：周一取到窗口，周三取不到
    expect(resolveOpeningWindows(periods, '07:00-24:00', { weekday: 1 }).source).toBe('structured')
    expect(resolveOpeningWindows(periods, '07:00-24:00', { weekday: 1 }).windows).toHaveLength(1)
    expect(resolveOpeningWindows(periods, '07:00-24:00', { weekday: 3 }).source).toBe('unknown')
    // 无星期不套用：降级 unknown，不把周一窗口套到所有日期
    expect(resolveOpeningWindows(periods, '07:00-24:00').source).toBe('unknown')
  })

  it('parses multi-segment text', async () => {
    const { parseHoursText } = await import('@/domain/openingHours')
    expect(parseHoursText('08:30-11:30,13:30-17:00')).toHaveLength(2)
    expect(parseHoursText('08:30-11:30；13:30-17:00')).toHaveLength(2)
  })

  it('normalizes backend day-grouped entries per weekday', async () => {
    const { resolveOpeningWindows } = await import('@/domain/openingHours')
    const backend = [
      { day: 1, opensSeconds: 25200, closesSeconds: 0, closeDay: 2 },
      { day: 2, opensSeconds: 25200, closesSeconds: 0, closeDay: 3 },
    ]
    expect(resolveOpeningWindows(backend, null, { weekday: 2 }).windows).toHaveLength(1)
    expect(resolveOpeningWindows(backend, null).source).toBe('unknown')
  })
})
