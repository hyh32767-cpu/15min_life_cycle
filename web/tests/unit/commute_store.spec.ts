import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AppProvider } from '@/providers/contracts'
import { useAppStore } from '@/stores/app'
import { useCommuteStore } from '@/stores/commute'

function place(name: string, lng: number, lat: number) {
  return {
    uid: name,
    name,
    address: `${name}地址`,
    coord: { lng, lat, crs: 'BD09' as const },
    source: 'api-cache' as const,
  }
}

function makeProvider(onIsochrone = vi.fn()) {
  const company = place('公司', 116.3, 39.9)
  const home = place('家', 116.32, 39.92)
  const poi = place('测试药店', 116.31, 39.91)
  const poi2 = place('测试超市', 116.305, 39.905)
  const poi3 = place('测试咖啡', 116.315, 39.915)
  const provider: AppProvider = {
    mode: 'live',
    getHealth: async () => ({ status: 'ok', mode: 'live', baiduConfigured: true,
                              warnings: [], features: {} }),
    searchLocations: async (query: string) => ({
      traceId: `t-${query}`, mode: 'live',
      candidates: [query.includes('回龙观') ? company : home], warnings: [],
    }),
    getWalkingRoute: async () => ({
      traceId: 'route', mode: 'live', sourceKind: 'api-cache', cacheHit: true,
      route: {
        durationSeconds: 1200,
        distanceM: 1500,
        geometry: [
          { lng: 116.3, lat: 39.9, crs: 'BD09' },
          { lng: 116.32, lat: 39.92, crs: 'BD09' },
        ],
        steps: [],
      },
      warnings: [],
    }),
    getTravelMatrix: async (_origins, destinations) => ({
      traceId: 'matrix', mode: 'live', sourceKind: 'api-cache', cacheHit: true,
      cells: destinations.map((_dest, index) => ({
        fromIndex: 0, toIndex: index, durationSeconds: 500, distanceM: 600,
        status: 'ok', sourceKind: 'api-cache',
      })),
      warnings: [],
    }),
    getCorridorPois: async () => ({
      traceId: 'corridor', mode: 'live', sourceKind: 'derived',
      retrieval: {
        queryTerms: ['药店'], category: '药店', windows: 1, pages: 1,
        rawCount: 1, uniqueCount: 1, truncated: false, truncationReason: null,
        sourceKind: 'derived',
      },
      pois: [
        { place: poi, distanceToRouteM: 80 },
        { place: poi2, distanceToRouteM: 120 },
        { place: poi3, distanceToRouteM: 160 },
      ],
      warnings: [],
    }),
    getRouteBand: async () => { throw new Error('unexpected route-band request') },
    createIsochrone: async (request) => {
      onIsochrone(request)
      return {
        taskId: 'iso-1', status: 'complete', placeId: request.placeId,
        thresholdSeconds: request.thresholdSeconds, radiiM: { '0': 500, '90': 510 },
        failedBearings: [], skippedBearings: [],
        algorithmVersion: 'm2-ray-bisect-v1', warnings: [], cacheHit: false,
        pairsUsed: 12,
      }
    },
    getIsochronePois: async () => { throw new Error('no pois') },
    getCorridorEvidence: async (request) => ({
      traceId: 'evidence', mode: 'live', sourceKind: 'derived',
      thresholdSeconds: request.thresholdSeconds, pairsUsed: 4,
      samples: [{
        index: 0, coord: request.poi, distanceFromStartM: 100, prefixSeconds: 100,
        inboundSeconds: 200, outboundSeconds: 210,
        inboundReachable: true, outboundReachable: true,
      }],
      evidence: {
        thresholdSeconds: request.thresholdSeconds,
        inboundReachableIndices: [0], outboundReachableIndices: [0],
        missingInboundIndices: [], missingOutboundIndices: [],
        symmetricAssumed: false, directionalFeasible: true,
      },
      bestAccess: null, warnings: [],
    }),
    createPlan: async () => ({
      status: 'ready', alternatives: [], infeasibleReasons: {}, warnings: [], suggestions: [],
    }),
    createReplan: async () => { throw new Error('no replan') },
    checkExplore: async () => [],
    checkCoverage: async () => ({ coverage: {}, coveredCount: 0, totalGrids: 0, blindGrids: [] }),
    listCases: async () => [],
    getCase: async () => ({}),
      getMapsConfig: async () => ({ configured: false, ak: '', version: '4.0' }),
  }
  return provider
}

describe('commute store isochrone flow', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('keeps legacy queue and service totals when presenting the merged stay time', () => {
    const commute = useCommuteStore()
    commute.serviceMinutes = 6
    commute.waitMinutes = 4
    expect(commute.stayMinutes).toBe(10)
    commute.stayMinutes = 12
    expect(commute.serviceMinutes).toBe(12)
    expect(commute.waitMinutes).toBe(0)
  })

  it('previews a place without calculating an isochrone and clears its geometry on deselection', async () => {
    const onIsochrone = vi.fn()
    const provider = makeProvider(onIsochrone)
    const evidence = provider.getCorridorEvidence
    provider.getCorridorEvidence = async (request) => ({
      ...await evidence(request),
      bestAccess: { entryIndex: 0, returnIndex: 0, totalTravelSeconds: 1000,
        extraTravelSeconds: -200, finishSeconds: 66000 },
    })
    useAppStore().setProviderForTesting(provider)
    const commute = useCommuteStore()
    await commute.searchCompany()
    await commute.searchHome()
    await commute.planCommute()
    await commute.selectPoi(0, false)
    expect(onIsochrone).not.toHaveBeenCalled()
    expect(commute.evidence).not.toBeNull()
    expect(commute.detourGeometries).toHaveLength(2)
    await commute.selectPoi(null, false)
    expect(commute.selectedPoiIndex).toBeNull()
    expect(commute.evidence).toBeNull()
    expect(commute.detourGeometries).toEqual([])
  })

  it('ranks a corridor POI and loads an on-demand isochrone', async () => {
    const onIsochrone = vi.fn()
    const app = useAppStore()
    app.setProviderForTesting(makeProvider(onIsochrone))
    const commute = useCommuteStore()

    await commute.searchCompany()
    await commute.searchHome()
    await commute.planCommute()
    expect(commute.rankedPois).toHaveLength(3)
    expect(commute.rankedPois[0].extraTravelSeconds).toBe(-200)

    await commute.selectPoi(0)
    expect(onIsochrone).toHaveBeenCalledTimes(1)
    expect(commute.isochrone?.status).toBe('complete')
    expect(commute.isochrone?.radiiM['90']).toBe(510)
    expect(commute.evidence?.evidence.directionalFeasible).toBe(true)
    expect(commute.evidence?.pairsUsed).toBe(4)
  })

  it('reports cache miss without fabricating an isochrone', async () => {
    const app = useAppStore()
    const failing = makeProvider()
    failing.createIsochrone = async () => {
      throw new Error('CACHE_MISS: no fixture')
    }
    app.setProviderForTesting(failing)
    const commute = useCommuteStore()
    await commute.searchCompany()
    await commute.searchHome()
    await commute.planCommute()
    await commute.selectPoi(0)
    expect(commute.isochrone).toBeNull()
    expect(commute.error).toContain('CACHE_MISS')
  })

  it('recomputes candidate feasibility without refetching Baidu OD', async () => {
    const app = useAppStore()
    app.setProviderForTesting(makeProvider())
    const commute = useCommuteStore()
    commute.departureClock = '00:00'
    commute.deadlineClock = '00:20'
    commute.serviceMinutes = 10
    await commute.searchCompany()
    await commute.searchHome()
    await commute.planCommute()
    expect(commute.rankedPois[0].feasible).toBe(false)

    commute.serviceMinutes = 0
    commute.recomputeRanking()
    expect(commute.rankedPois[0].feasible).toBe(true)
  })

  it('compares at most three isochrones', async () => {
    const app = useAppStore()
    app.setProviderForTesting(makeProvider())
    const commute = useCommuteStore()
    await commute.searchCompany()
    await commute.searchHome()
    await commute.planCommute()
    expect(commute.rankedPois).toHaveLength(3)

    await commute.toggleCompare(0)
    await commute.toggleCompare(1)
    await commute.toggleCompare(2)
    expect(commute.compareIndices).toEqual([0, 1, 2])
    expect(Object.keys(commute.compareIsochrones)).toHaveLength(3)

    await commute.toggleCompare(0)
    expect(commute.compareIndices).toEqual([1, 2])
  })
})

describe('F48/F50 commute generations', () => {
  it('immediately retires old POIs and late route responses when category changes', async () => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    try {
      const provider = makeProvider()
      useAppStore().setProviderForTesting(provider)
      const commute = useCommuteStore()
      await commute.searchCompany()
      await commute.searchHome()
      await commute.planCommute()
      let finish!: (value: Awaited<ReturnType<AppProvider['getWalkingRoute']>>) => void
      const oldRoute = commute.route!
      provider.getWalkingRoute = () => new Promise(resolve => { finish = resolve })
      const obsolete = commute.planCommute()
      commute.category = '超市'
      expect(commute.rankedPois).toEqual([])
      expect(commute.selectedPoiIndex).toBeNull()
      finish(oldRoute)
      await obsolete
      expect(commute.rankedPois).toEqual([])
      expect(commute.route).toBeNull()
      commute.resetState()
    } finally { vi.useRealTimers() }
  })
  it('clears candidates and route synchronously when endpoints change', async () => {
    setActivePinia(createPinia())
    useAppStore().setProviderForTesting(makeProvider())
    const commute = useCommuteStore()
    await commute.searchCompany()
    await commute.searchHome()
    await commute.planCommute()
    commute.home = place('新终点', 116.4, 40)
    expect(commute.route).toBeNull()
    expect(commute.rankedPois).toEqual([])
    expect(commute.detourGeometries).toEqual([])
    commute.resetState()
  })
  it('clears selected isochrone on recompute and retires reset responses', async () => {
    const { createPinia, setActivePinia } = await import('pinia')
    setActivePinia(createPinia())
    const { useCommuteStore } = await import('@/stores/commute')
    const commute = useCommuteStore()
    commute.selectedPoiIndex = 3
    commute.isochrone = {
      taskId: 't', status: 'complete', thresholdSeconds: 900, radiiM: { 0: 100 },
      failedBearings: [], skippedBearings: [], algorithmVersion: 'v',
      warnings: [], cacheHit: false, pairsUsed: 1,
    }
    commute.compareIsochrones = { 3: commute.isochrone }
    // F48 语义：重算入口清空旧选中/旧圈（直接调内部清理等价路径：resetState 覆盖更强）
    commute.resetState()
    expect(commute.selectedPoiIndex).toBeNull()
    expect(commute.isochrone).toBeNull()
    expect(commute.compareIsochrones).toEqual({})
  })
})
