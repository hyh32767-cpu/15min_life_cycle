import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { beforeEach, expect, it, vi } from 'vitest'
import { inMeasuredBand } from '@/domain/routeBand'
import { useRouteBandStore } from '@/stores/routeBand'
import { useAppStore } from '@/stores/app'
import { useCommuteStore } from '@/stores/commute'
import type { AppProvider, RouteBandResult } from '@/providers/contracts'

const a = { lng: 116.3, lat: 39.9, crs: 'BD09' as const }
const b = { lng: 116.32, lat: 39.92, crs: 'BD09' as const }
function result(complete = 0): RouteBandResult {
  return { routeHash: 'r', thresholdSeconds: 900, status: complete === 2 ? 'complete' : 'unknown',
    completeCount: complete, nodes: [a, b].map((origin, index) => ({ origin, index,
      status: index < complete ? 'complete' : 'partial', cached: false, warnings: [] })),
    fills: [], boundaries: [], maxGapM: 1000, cacheHit: false,
    cost: { liveRequests: 0, cacheHits: 0, pairs: 0, livePairs: 0 } }
}
function setup(getRouteBand: AppProvider['getRouteBand']) {
  useAppStore().provider.getRouteBand = getRouteBand
  useCommuteStore().route = { traceId: 'r', mode: 'live', sourceKind: 'api-cache', cacheHit: true,
    route: { geometry: [a, b], durationSeconds: 1200, distanceM: 1500, steps: [] }, warnings: [] }
  return useRouteBandStore()
}
beforeEach(() => { setActivePinia(createPinia()) })

it('measured polygon filter includes boundary but excludes gaps and other CRS', () => {
  const fills = [[{ ...a }, { ...a, lng: 116.31 }, { ...a, lng: 116.31, lat: 39.91 }, { ...a, lat: 39.91 }]]
  expect(inMeasuredBand(a, fills)).toBe(true)
  expect(inMeasuredBand({ ...a, lng: 116.305, lat: 39.905 }, fills)).toBe(true)
  expect(inMeasuredBand(b, fills)).toBe(false)
  expect(inMeasuredBand({ ...a, crs: 'WGS84' }, fills)).toBe(false)
})

it('opening reads cache only and supplements one missing center at a time', async () => {
  const request = vi.fn().mockResolvedValueOnce(result()).mockResolvedValueOnce(result(1)).mockResolvedValueOnce(result(2))
  const store = setup(request)
  store.toggle()
  await nextTick()
  expect(request.mock.calls[0][0].cacheOnly).toBe(true)
  await store.supplement()
  expect(request.mock.calls.slice(1).map(call => [call[0].cacheOnly, call[0].centerIndex])).toEqual([[false, 0], [false, 1]])
  expect(store.pendingCount).toBe(0)
  expect(store.supplementing).toBe(false)
})

it('late responses cannot restore a hidden or changed band', async () => {
  let resolve!: (value: RouteBandResult) => void
  const request = vi.fn().mockImplementation(() => new Promise<RouteBandResult>(done => { resolve = done }))
  const store = setup(request)
  store.toggle()
  store.toggle()
  resolve(result(2))
  await nextTick()
  expect(store.result).toBeNull()
  expect(store.loading).toBe(false)
  expect(store.enabled).toBe(false)
})

it('publishes running centers and polls their task without issuing another live measurement', async () => {
  vi.useFakeTimers()
  try {
    const running = result()
    running.nodes[0] = { ...running.nodes[0]!, taskId: 'circle-zero', backgroundStatus: 'running', previewContours: [[a,b]] }
    const request = vi.fn().mockResolvedValueOnce(result()).mockResolvedValueOnce(running)
      .mockResolvedValueOnce(result(1)).mockResolvedValueOnce(result(2))
    const store = setup(request)
    store.toggle()
    await nextTick()
    const work = store.supplement()
    await nextTick()
    expect(store.result?.nodes[0]?.backgroundStatus).toBe('running')
    expect(store.result?.nodes[0]?.previewContours).toEqual([[a,b]])
    await vi.advanceTimersByTimeAsync(1500)
    await work
    expect(request.mock.calls[2]![0]).toMatchObject({cacheOnly:true,taskIds:{0:'circle-zero'},thresholdSeconds:900})
    expect(request.mock.calls.filter(call=>!call[0].cacheOnly).map(call=>call[0].centerIndex)).toEqual([0,1])
    expect(store.pendingCount).toBe(0)
  } finally { vi.useRealTimers() }
})

it('quota failure stops further supplementation and retains partial result', async () => {
  const partial = result(1)
  partial.nodes[0]!.status = 'partial'
  partial.nodes[0]!.warnings = ['QUOTA_EXCEEDED']
  const request = vi.fn().mockResolvedValueOnce(result()).mockResolvedValueOnce(partial)
  const store = setup(request)
  store.toggle()
  await nextTick()
  await store.supplement()
  expect(request).toHaveBeenCalledTimes(2)
  expect(store.result).toEqual(partial)
  expect(store.error).toContain('稍后补齐')
})
