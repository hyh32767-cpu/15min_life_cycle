import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AppProvider } from '@/providers/contracts'
import { useAppStore } from '@/stores/app'
import { useCommuteStore } from '@/stores/commute'
import { usePlanStore } from '@/stores/plan'

function coord(lng: number, lat: number) {
  return { lng, lat, crs: 'BD09' as const }
}

it('turns waypoint order into hard dependencies and removes abandoned map nodes', async () => {
  setActivePinia(createPinia())
  const sent = vi.fn()
  useAppStore().setProviderForTesting(makeProvider(sent))
  const commute = useCommuteStore()
  commute.restoring = true
  commute.company = { name: '起点', coord: coord(116.3, 40), source: 'user-input' }
  commute.home = { name: '终点', coord: coord(116.4, 40), source: 'user-input' }
  const plan = usePlanStore()
  const a = plan.addFixedTask({ uid: 'a', name: '甲', coord: coord(116.31, 40), source: 'user-input' }, 1)
  const b = plan.addFixedTask({ uid: 'b', name: '乙', coord: coord(116.32, 40), source: 'user-input' }, 1)
  plan.setVisitOrder([b, a])
  await plan.runPlan()
  const request = sent.mock.calls[0]![0]
  expect(request.tasks.map((task: { id: string }) => task.id)).toEqual([b, a])
  expect(request.tasks[1].precedenceIds).toContain(b)
  plan.replaceFixedTask(a, { uid: 'c', name: '丙', coord: coord(116.33, 40), source: 'user-input' }, 1)
  expect(plan.nodeCoords.a).toBeUndefined()
  expect(plan.nodeCoords.c).toEqual(coord(116.33, 40))
  plan.removeTask(b)
  expect(plan.nodeCoords.b).toBeUndefined()
  expect(plan.visitOrder).toEqual([a])
  commute.resetState()
})

function makeProvider(onPlan = vi.fn()) {
  const provider: AppProvider = {
    mode: 'live',
    getHealth: async () => ({ status: 'ok', mode: 'live', baiduConfigured: true, warnings: [], features: {} }),
    searchLocations: async () => ({ traceId: 't', mode: 'live', candidates: [], warnings: [] }),
    getWalkingRoute: async () => ({
      traceId: 'r', mode: 'live', sourceKind: 'api-cache', cacheHit: true,
      route: { durationSeconds: 600, distanceM: 700, geometry: [], steps: [] }, warnings: [],
    }),
    getTravelMatrix: async (origins, destinations) => ({
      traceId: 'm', mode: 'live', sourceKind: 'api-cache', cacheHit: true,
      cells: origins.flatMap((_o, i) => destinations.map((_d, j) => ({
        fromIndex: i, toIndex: j, durationSeconds: 100, distanceM: 120,
        status: 'ok' as const, sourceKind: 'api-cache' as const,
      }))),
      warnings: [],
    }),
    getCorridorPois: async () => ({
      traceId: 'c', mode: 'live', sourceKind: 'derived',
      retrieval: {
        queryTerms: ['药店'], category: '药店', windows: 1, pages: 1,
        rawCount: 0, uniqueCount: 0, truncated: false, truncationReason: null, sourceKind: 'derived',
      },
      pois: [], warnings: [],
    }),
    getRouteBand: async () => { throw new Error('unexpected route-band request') },
    createIsochrone: async () => { throw new Error('no iso') },
    getIsochronePois: async () => { throw new Error('no pois') },
    getCorridorEvidence: async () => { throw new Error('no evidence') },
    createPlan: async (request) => {
      onPlan(request)
      return {
        status: 'ready',
        alternatives: [{
          stops: request.tasks.flatMap((t) => t.options.slice(0, 1).map((o) => ({
            taskId: t.id, placeId: o.placeId,
            arrivalSeconds: 100, startSeconds: 100, finishSeconds: 200, waitSeconds: 0,
            travelSeconds: 100, travelSourceKind: 'api-cache',
            serviceSourceKind: 'user-input', windowSourceKind: 'unknown',
          }))),
          timeline: [{ kind: 'returnTravel', durationSeconds: 100, sourceKind: 'api-cache' }],
          departureSeconds: request.departureSeconds,
          finishSeconds: request.departureSeconds + 500,
          deadlineSeconds: request.deadlineSeconds,
          slackSeconds: 100,
          totalTravelSeconds: 300, totalWaitSeconds: 0, totalServiceSeconds: 200,
          totalWalkingM: 300, returnTravelSeconds: 100, returnTravelSourceKind: 'api-cache',
        }],
        infeasibleReasons: {}, warnings: [], suggestions: [],
      }
    },
    createReplan: async () => { throw new Error('no replan') },
    checkExplore: async () => [],
    checkCoverage: async () => ({ coverage: {}, coveredCount: 0, totalGrids: 0, blindGrids: [] }),
    listCases: async () => [],
    getCase: async () => ({}),
      getMapsConfig: async () => ({ configured: false, ak: '', version: '4.0' }),
  }
  return provider
}

describe('plan store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('imports a fixed task from a commute POI and plans it', async () => {
    const onPlan = vi.fn()
    const app = useAppStore()
    app.setProviderForTesting(makeProvider(onPlan))
    const commute = useCommuteStore()
    commute.company = { name: '公司', coord: coord(116.3, 39.9), source: 'api-cache' }
    commute.home = { name: '家', coord: coord(116.32, 39.92), source: 'api-cache' }
    const plan = usePlanStore()
    // seed a ranked POI by faking corridor state through the store internals
    plan.addFixedTask(
      { name: '测试药店', coord: coord(116.31, 39.91), source: 'api-cache', uid: 'poi-1' },
      10,
    )
    expect(plan.tasks).toHaveLength(1)
    expect(plan.tasks[0].options).toHaveLength(1)
    await plan.runPlan()
    expect(plan.error).toBe('')
    expect(plan.result?.status).toBe('ready')
    expect(onPlan).toHaveBeenCalledOnce()
    const request = onPlan.mock.calls[0][0]
    expect(request.preference).toBe('fastest')
    expect(request.tasks).toHaveLength(1)
  })

  it('rejects empty and oversized task lists without calling the API', async () => {
    const onPlan = vi.fn()
    const app = useAppStore()
    app.setProviderForTesting(makeProvider(onPlan))
    const commute = useCommuteStore()
    commute.company = { name: '公司', coord: coord(116.3, 39.9), source: 'api-cache' }
    commute.home = { name: '家', coord: coord(116.32, 39.92), source: 'api-cache' }
    const plan = usePlanStore()
    await plan.runPlan()
    expect(plan.error).toMatch('1–5')
    expect(onPlan).not.toHaveBeenCalled()
    for (let i = 0; i < 6; i += 1) {
      plan.addFixedTask(
        { name: `店${i}`, coord: coord(116.3 + i * 0.001, 39.9), source: 'user-input', uid: `p-${i}` },
        5,
      )
    }
    await plan.runPlan()
    expect(plan.error).toMatch('1–5')
    expect(onPlan).not.toHaveBeenCalled()
  })

  it('removes precedence edges when a task is deleted', () => {
    setActivePinia(createPinia())
    const app = useAppStore()
    app.setProviderForTesting(makeProvider())
    const plan = usePlanStore()
    const a = plan.addFixedTask({ name: 'A', coord: coord(1, 1), source: 'user-input', uid: 'a' }, 5)
    const b = plan.addFixedTask({ name: 'B', coord: coord(2, 2), source: 'user-input', uid: 'b' }, 5)
    plan.togglePrecedence(b, a)
    expect(plan.tasks.find((t: { id: string }) => t.id === b)?.precedenceIds).toContain(a)
    plan.removeTask(a)
    expect(plan.tasks.find((t: { id: string }) => t.id === b)?.precedenceIds).not.toContain(a)
  })
})

describe('manual service minutes validation', () => {
  it('rejects NaN, negative, and oversized stay minutes', async () => {
    const { createPinia, setActivePinia } = await import('pinia')
    setActivePinia(createPinia())
    const { useAppStore } = await import('@/stores/app')
    const { usePlanStore } = await import('@/stores/plan')
    const app = useAppStore()
    app.setProviderForTesting({
      mode: 'live',
      getHealth: async () => ({ status: 'ok', mode: 'live', baiduConfigured: true, warnings: [], features: {} }),
      searchLocations: async () => ({ traceId: 't', mode: 'live', candidates: [], warnings: [] }),
      getWalkingRoute: async () => { throw new Error('no route') },
      getTravelMatrix: async () => { throw new Error('no matrix') },
      getCorridorPois: async () => { throw new Error('no corridor') },
      getRouteBand: async () => { throw new Error('unexpected route-band request') },
      createIsochrone: async () => { throw new Error('no iso') },
      getIsochronePois: async () => { throw new Error('no pois') },
      getCorridorEvidence: async () => { throw new Error('no evidence') },
      createPlan: async () => { throw new Error('no plan') },
      createReplan: async () => { throw new Error('no replan') },
      checkExplore: async () => [],
      checkCoverage: async () => ({ coverage: {}, coveredCount: 0, totalGrids: 0, blindGrids: [] }),
      listCases: async () => [],
      getCase: async () => ({}),
      getMapsConfig: async () => ({ configured: false, ak: '', version: '4.0' }),
    })
    const plan = usePlanStore()
    const place = { name: 'X', coord: { lng: 1, lat: 1, crs: 'BD09' as const }, source: 'user-input' as const }
    expect(() => plan.addFixedTask(place, Number.NaN)).toThrow('0–480')
    expect(() => plan.addFixedTask(place, -1)).toThrow('0–480')
    expect(() => plan.addFixedTask(place, 481)).toThrow('0–480')
    expect(() => plan.addFlexibleTask('cat', [place], Number.NaN)).toThrow('0–480')
    expect(plan.tasks).toHaveLength(0)
  })
})

describe('F33 stale plan invalidation', () => {
  it('clears result on task and constraint edits', async () => {
    const { createPinia, setActivePinia } = await import('pinia')
    setActivePinia(createPinia())
    const { useAppStore } = await import('@/stores/app')
    const { usePlanStore } = await import('@/stores/plan')
    const { useCommuteStore } = await import('@/stores/commute')
    const app = useAppStore()
    app.setProviderForTesting({
      mode: 'live',
      getHealth: async () => ({ status: 'ok', mode: 'live', baiduConfigured: true, warnings: [], features: {} }),
      searchLocations: async () => ({ traceId: 't', mode: 'live', candidates: [], warnings: [] }),
      getWalkingRoute: async () => ({ traceId: 'r', mode: 'live', sourceKind: 'api-cache', cacheHit: true, route: { durationSeconds: 1, distanceM: 1, geometry: [], steps: [] }, warnings: [] }),
      getTravelMatrix: async () => ({ traceId: 'm', mode: 'live', sourceKind: 'api-cache', cacheHit: true, cells: [], warnings: [] }),
      getCorridorPois: async () => { throw new Error('no corridor') },
      getRouteBand: async () => { throw new Error('unexpected route-band request') },
      createIsochrone: async () => { throw new Error('no iso') },
      getIsochronePois: async () => { throw new Error('no pois') },
      getCorridorEvidence: async () => { throw new Error('no evidence') },
      createPlan: async () => { throw new Error('no plan') },
      createReplan: async () => { throw new Error('no replan') },
      checkExplore: async () => [],
      checkCoverage: async () => ({ coverage: {}, coveredCount: 0, totalGrids: 0, blindGrids: [] }),
      listCases: async () => [],
      getCase: async () => ({}),
      getMapsConfig: async () => ({ configured: false, ak: '', version: '4.0' }),
    })
    const commute = useCommuteStore()
    commute.company = { name: 'S', coord: { lng: 1, lat: 1, crs: 'BD09' }, source: 'api-cache' }
    commute.home = { name: 'H', coord: { lng: 2, lat: 2, crs: 'BD09' }, source: 'api-cache' }
    const plan = usePlanStore()
    const place = { name: 'X', coord: { lng: 1, lat: 1, crs: 'BD09' as const }, source: 'user-input' as const }
    const id = plan.addFixedTask(place, 5)
    plan.result = { status: 'ready', alternatives: [], infeasibleReasons: {}, warnings: [], suggestions: [] }
    plan.setServiceMinutes(id, 0, 6)
    expect(plan.result).toBeNull()
    plan.result = { status: 'ready', alternatives: [], infeasibleReasons: {}, warnings: [], suggestions: [] }
    plan.setConstraint('deadline', '20:00')
    expect(plan.result).toBeNull()
    expect(plan.deadlineClock).toBe('20:00')
  })
})

describe('F35 window provenance', () => {
  it('marks api-cache POI windows as api-cache, not live-api', async () => {
    const { createPinia, setActivePinia } = await import('pinia')
    setActivePinia(createPinia())
    const { usePlanStore } = await import('@/stores/plan')
    const plan = usePlanStore()
    plan.addFixedTask({
      name: 'P', uid: 'p1',
      coord: { lng: 1, lat: 1, crs: 'BD09' as const },
      source: 'api-cache' as const,
      opensSeconds: 28800, closesSeconds: 64800,
    }, 5)
    expect(plan.tasks[0].options[0].windowSourceKind).toBe('api-cache')
    plan.addFixedTask({
      name: 'Q', uid: 'q1',
      coord: { lng: 2, lat: 2, crs: 'BD09' as const },
      source: 'live-api' as const,
      opensSeconds: 28800, closesSeconds: 64800,
    }, 5)
    expect(plan.tasks[1].options[0].windowSourceKind).toBe('live-api')
    plan.addFixedTask({
      name: 'R', uid: 'r1',
      coord: { lng: 3, lat: 3, crs: 'BD09' as const },
      source: 'user-input' as const,
    }, 5)
    expect(plan.tasks[2].options[0].windowSourceKind).toBe('unknown')
  })
})

describe('F38 service minutes guard', () => {
  it('rejects NaN stay minutes without touching options', async () => {
    const { createPinia, setActivePinia } = await import('pinia')
    setActivePinia(createPinia())
    const { useAppStore } = await import('@/stores/app')
    const { usePlanStore } = await import('@/stores/plan')
    const app = useAppStore()
    const plan = usePlanStore()
    void app
    const id = plan.addFixedTask({
      name: 'S', coord: { lng: 1, lat: 1, crs: 'BD09' as const },
      source: 'user-input' as const,
    }, 5)
    const before = plan.tasks[0].options[0].serviceSeconds
    plan.setServiceMinutes(id, 0, NaN)
    expect(plan.error).toMatch('0–480')
    expect(plan.tasks[0].options[0].serviceSeconds).toBe(before)
  })
})

describe('T212 unknown-hours warnings', () => {
  it('surfaces UNKNOWN_HOURS on ready results without blocking', async () => {
    const { createPinia, setActivePinia } = await import('pinia')
    setActivePinia(createPinia())
    const { useAppStore } = await import('@/stores/app')
    const { useCommuteStore } = await import('@/stores/commute')
    const { usePlanStore } = await import('@/stores/plan')
    const app = useAppStore()
    app.setProviderForTesting({
      mode: 'live',
      getHealth: async () => { throw new Error('no health') },
      searchLocations: async () => { throw new Error('no search') },
      getWalkingRoute: async () => { throw new Error('no route') },
      getTravelMatrix: async (origins, destinations) => ({
        traceId: 'm', mode: 'live', sourceKind: 'live-api', cacheHit: false,
        cells: origins.flatMap((_o, i) => destinations.map((_d, j) => ({
          fromIndex: i, toIndex: j, durationSeconds: 100, distanceM: 100,
          status: 'ok' as const, sourceKind: 'live-api' as const,
        }))),
        warnings: [],
      }),
      getCorridorPois: async () => { throw new Error('no corridor') },
      getRouteBand: async () => { throw new Error('unexpected route-band request') },
      createIsochrone: async () => { throw new Error('no iso') },
      getIsochronePois: async () => { throw new Error('no pois') },
      getCorridorEvidence: async () => { throw new Error('no evidence') },
      createPlan: async () => ({
        status: 'ready' as const, alternatives: [], infeasibleReasons: {},
        warnings: ['UNKNOWN_HOURS:A:A'], suggestions: [],
      }),
      createReplan: async () => { throw new Error('no replan') },
      checkExplore: async () => { throw new Error('no explore') },
      checkCoverage: async () => { throw new Error('no coverage') },
      listCases: async () => { throw new Error('no cases') },
      getCase: async () => { throw new Error('no case') },
      getMapsConfig: async () => ({ configured: false, ak: '', version: '4.0' }),
    })
    const commute = useCommuteStore()
    commute.company = { name: 'S', coord: { lng: 1, lat: 1, crs: 'BD09' }, source: 'api-cache' }
    commute.home = { name: 'H', coord: { lng: 2, lat: 2, crs: 'BD09' }, source: 'api-cache' }
    const plan = usePlanStore()
    plan.addFixedTask({
      name: 'U', coord: { lng: 1.1, lat: 1.1, crs: 'BD09' as const },
      source: 'api-cache' as const,
    }, 5)
    await plan.runPlan()
    expect(plan.result?.status).toBe('ready')
    expect(plan.result?.warnings.some((w) => w.startsWith('UNKNOWN_HOURS'))).toBe(true)
  })
})

describe('F51 stale plan responses', () => {
  it('drops stale plan responses after constraint edits', async () => {
    const { createPinia, setActivePinia } = await import('pinia')
    setActivePinia(createPinia())
    const { useAppStore } = await import('@/stores/app')
    const { useCommuteStore } = await import('@/stores/commute')
    const { usePlanStore } = await import('@/stores/plan')
    const app = useAppStore()
    let resolveFirst!: (v: { status: string; alternatives: never[]; infeasibleReasons: Record<string, number>; warnings: never[]; suggestions: never[] }) => void
    const first = new Promise((resolve) => { resolveFirst = resolve as never })
    let calls = 0
    app.setProviderForTesting({
      mode: 'live',
      getHealth: async () => ({ status: 'ok', mode: 'live', baiduConfigured: true, warnings: [], features: {} }),
      searchLocations: async () => ({ traceId: 't', mode: 'live', candidates: [], warnings: [] }),
      getWalkingRoute: async () => ({ traceId: 'r', mode: 'live', sourceKind: 'api-cache', cacheHit: true, route: { durationSeconds: 1, distanceM: 1, geometry: [], steps: [] }, warnings: [] }),
      getTravelMatrix: async () => ({ traceId: 'm', mode: 'live', sourceKind: 'api-cache', cacheHit: true, cells: [], warnings: [] }),
      getCorridorPois: async () => { throw new Error('no corridor') },
      getRouteBand: async () => { throw new Error('unexpected route-band request') },
      createIsochrone: async () => { throw new Error('no iso') },
      getIsochronePois: async () => { throw new Error('no pois') },
      getCorridorEvidence: async () => { throw new Error('no evidence') },
      createPlan: async () => {
        calls += 1
        if (calls === 1) return first as never
        return { status: 'ready', alternatives: [], infeasibleReasons: {}, warnings: [], suggestions: [] }
      },
      createReplan: async () => { throw new Error('no replan') },
      checkExplore: async () => [],
      checkCoverage: async () => ({ coverage: {}, coveredCount: 0, totalGrids: 0, blindGrids: [] }),
      listCases: async () => [],
      getCase: async () => ({}),
      getMapsConfig: async () => ({ configured: false, ak: '', version: '4.0' }),
    })
    const commute = useCommuteStore()
    commute.company = { name: 'S', coord: { lng: 1, lat: 1, crs: 'BD09' }, source: 'api-cache' }
    commute.home = { name: 'H', coord: { lng: 2, lat: 2, crs: 'BD09' }, source: 'api-cache' }
    const plan = usePlanStore()
    plan.addFixedTask({ name: 'X', coord: { lng: 1, lat: 1, crs: 'BD09' as const }, source: 'user-input' as const }, 5)
    const running = plan.runPlan()
    plan.setConstraint('deadline', '20:00')
    resolveFirst({ status: 'ready', alternatives: [], infeasibleReasons: {}, warnings: [], suggestions: [] })
    await running
    // 旧响应不得覆盖新约束后的空结果
    expect(plan.result).toBeNull()
  })
})

describe('T212 infeasible reason display', () => {
  it('shows human-readable reason labels instead of raw codes', async () => {
    const { createPinia, setActivePinia } = await import('pinia')
    setActivePinia(createPinia())
    const { useAppStore } = await import('@/stores/app')
    const { useCommuteStore } = await import('@/stores/commute')
    const { usePlanStore } = await import('@/stores/plan')
    const app = useAppStore()
    app.setProviderForTesting({
      mode: 'live',
      getHealth: async () => ({ status: 'ok', mode: 'live', baiduConfigured: true, warnings: [], features: {} }),
      searchLocations: async () => ({ traceId: 't', mode: 'live', candidates: [], warnings: [] }),
      getWalkingRoute: async () => ({ traceId: 'r', mode: 'live', sourceKind: 'api-cache', cacheHit: true, route: { durationSeconds: 1, distanceM: 1, geometry: [], steps: [] }, warnings: [] }),
      getTravelMatrix: async () => ({ traceId: 'm', mode: 'live', sourceKind: 'api-cache', cacheHit: true, cells: [], warnings: [] }),
      getCorridorPois: async () => { throw new Error('no corridor') },
      getRouteBand: async () => { throw new Error('unexpected route-band request') },
      createIsochrone: async () => { throw new Error('no iso') },
      getIsochronePois: async () => { throw new Error('no pois') },
      getCorridorEvidence: async () => { throw new Error('no evidence') },
      createPlan: async () => ({
        status: 'infeasible', alternatives: [],
        infeasibleReasons: { OD_UNAVAILABLE: 2 }, warnings: [], suggestions: ['稍后重试'],
      }),
      createReplan: async () => { throw new Error('no replan') },
      checkExplore: async () => [],
      checkCoverage: async () => ({ coverage: {}, coveredCount: 0, totalGrids: 0, blindGrids: [] }),
      listCases: async () => [],
      getCase: async () => ({}),
      getMapsConfig: async () => ({ configured: false, ak: '', version: '4.0' }),
    })
    const commute = useCommuteStore()
    commute.company = { name: 'S', coord: { lng: 1, lat: 1, crs: 'BD09' }, source: 'api-cache' }
    commute.home = { name: 'H', coord: { lng: 2, lat: 2, crs: 'BD09' }, source: 'api-cache' }
    const plan = usePlanStore()
    plan.addFixedTask({ name: 'X', coord: { lng: 1, lat: 1, crs: 'BD09' as const }, source: 'user-input' as const }, 5)
    await plan.runPlan()
    // T212：页面错误用中文原因，不直接暴露 OD_UNAVAILABLE 原码
    expect(plan.error).toContain('用时查询未完成')
    expect(plan.error).not.toContain('OD_UNAVAILABLE')
  })
})
