import { afterEach, expect, it, vi } from 'vitest'
import { ResultCache } from '@/features/community/resultCache'
afterEach(() => vi.useRealTimers())
it('never extends source validity or returns mutable shared results', () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-13T08:00:00Z'))
  const cache = new ResultCache<{ covered: number }>()
  cache.put('scope', { covered: 5 }, ['2026-10-13T08:01:00Z', '2026-10-13T09:00:00Z'])
  const result = cache.get('scope')!
  result.covered = 0
  expect(cache.get('scope')).toEqual({ covered: 5 })
  vi.advanceTimersByTime(60_001)
  expect(cache.get('scope')).toBeNull()
})
it('does not cache missing expiry metadata or cross-use a different scope', () => {
  const cache = new ResultCache<number>()
  cache.put('scope', 5, [undefined])
  expect(cache.get('scope')).toBeNull()
  cache.put('scope', 5, [new Date(Date.now() + 60_000).toISOString()])
  expect(cache.get('other')).toBeNull()
})
