// F55：等时圈体检 store 单测。旧请求丢弃、阈值切换透传、复位清状态。
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAppStore } from '@/stores/app'
import { useIsochroneStore } from '@/stores/isochrone'

function makeProvider(impl?: Record<string, unknown>) {
  return {
    mode: 'live',
    getHealth: vi.fn(),
    searchLocations: vi.fn(),
    getWalkingRoute: vi.fn(),
    getTravelMatrix: vi.fn(),
    getCorridorPois: vi.fn(),
    createIsochrone: vi.fn(),
    getIsochronePois: async () => { throw new Error('no pois') },
    getCorridorEvidence: vi.fn(),
    createPlan: vi.fn(),
    createReplan: vi.fn(),
    checkExplore: vi.fn(),
    checkCoverage: vi.fn(),
    listCases: vi.fn(),
    getCase: vi.fn(),
    getMapsConfig: vi.fn(),
    ...impl,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
})
afterEach(() => vi.useRealTimers())

describe('isochrone store', () => {
  it('固定15分钟主圈后自动补齐5/10分钟，重复生成复用全部有效缓存', async () => {
    const request = vi.fn(async (r: { thresholdSeconds: number; origin: unknown }) => ({ taskId: `t-${r.thresholdSeconds}`,
      status: 'complete', origin: r.origin, thresholdSeconds: r.thresholdSeconds, radiiM: { 0: 600, 90: 600, 180: 600, 270: 600 },
      failedBearings: [], skippedBearings: [], warnings: [], cacheHit: false, expiresAt: new Date(Date.now() + 300000).toISOString() }))
    useAppStore().setProviderForTesting(makeProvider({ createIsochrone: request }) as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40, crs: 'BD09' })
    store.thresholdSeconds = 1200
    await store.generateLifeCircle()
    expect(store.thresholdSeconds).toBe(900)
    expect(store.result?.thresholdSeconds).toBe(900)
    expect(store.heatLayers.map(l => l.thresholdSeconds)).toEqual([900, 600, 300])
    await store.generateLifeCircle()
    expect(request.mock.calls.map(([r]) => r.thresholdSeconds)).toEqual([900, 300, 600])
    expect(store.busy).toBe(false)
  })
  it('小圈失败保留15分钟结果，重试只补缺层，主圈失败不查询小圈', async () => {
    let fail = true
    const request = vi.fn(async (r: { thresholdSeconds: number }) => {
      if (fail && r.thresholdSeconds === 300) throw new Error('小圈暂不可用')
      return { taskId: 't', status: 'complete', thresholdSeconds: r.thresholdSeconds, radiiM: { 0: 600 },
        expiresAt: new Date(Date.now() + 300000).toISOString() }
    })
    useAppStore().setProviderForTesting(makeProvider({ createIsochrone: request }) as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40, crs: 'BD09' })
    await store.generateLifeCircle()
    expect(store.result?.thresholdSeconds).toBe(900)
    expect(store.heatLayers.map(l => l.thresholdSeconds)).toEqual([900])
    expect(store.heatError).toBe('小圈暂不可用')
    fail = false
    await store.loadHeatLayers()
    expect(request.mock.calls.map(([r]) => r.thresholdSeconds)).toEqual([900, 300, 300, 600])
    store.setOrigin({ lng: 117, lat: 40, crs: 'BD09' })
    request.mockRejectedValue(new Error('主圈不可用'))
    await store.generateLifeCircle()
    expect(request.mock.calls.at(-1)?.[0].thresholdSeconds).toBe(900)
    expect(request).toHaveBeenCalledTimes(5)
    expect(store.heatLayers).toEqual([])
    expect(store.busy).toBe(false)
  })
  it('后台超过12秒仍继续查询，实测轮廓先显示，最终结果缓存复用', async () => {
    vi.useFakeTimers()
    let polls = 0
    const base = { taskId: 'background', thresholdSeconds: 900, radiiM: { 0: 800 }, failedBearings: [], skippedBearings: [],
      algorithmVersion: 'adaptive-v1', warnings: [], pairsUsed: 100, cacheHit: false, expiresAt: new Date(Date.now() + 600_000).toISOString() }
    const request = vi.fn(async () => ({ ...base, status: 'degraded', backgroundStatus: 'running' }))
    const status = vi.fn(async () => ({ ...base, status: 'complete', backgroundStatus: ++polls >= 20 ? 'completed' : 'running' }))
    useAppStore().setProviderForTesting(makeProvider({ createIsochrone: request, getIsochroneTaskStatus: status }) as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40, crs: 'BD09' })
    const pending = store.run(900)
    await vi.advanceTimersByTimeAsync(13_000)
    expect(store.loading).toBe(true)
    expect(store.result?.status).toBe('complete')
    expect(store.backgroundStatus).toBe('running')
    await vi.advanceTimersByTimeAsync(30_000)
    await pending
    expect(store.backgroundStatus).toBe('completed')
    expect(store.loading).toBe(false)
    await store.run(900)
    expect(request).toHaveBeenCalledTimes(1)
    expect(store.rangeReused).toBe(true)
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ frontier: true, maxPairs: 376, l2First: true }))
  })
  it('连续轮询失败会恢复操作并保留已完成的轮廓', async () => {
    vi.useFakeTimers()
    let polls = 0
    const status = vi.fn(async () => {
      if (++polls > 1) throw new Error('网络已断开，请重试')
      return { taskId: 't', status: 'complete', backgroundStatus: 'running', radiiM: { 0: 800 } }
    })
    useAppStore().setProviderForTesting(makeProvider({
      createIsochrone: async () => ({ taskId: 't', status: 'degraded', backgroundStatus: 'running' }),
      getIsochroneTaskStatus: status,
    }) as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40, crs: 'BD09' })
    const pending = store.run(900)
    await vi.advanceTimersByTimeAsync(6000)
    await pending
    expect(store.loading).toBe(false)
    expect(store.result?.status).toBe('complete')
    expect(store.error).toContain('网络已断开')
  })
  it('expired or incomplete circles are remeasured instead of being reused as complete', async () => {
    const response = (seconds: number) => ({ taskId: 'circle', status: 'complete', thresholdSeconds: seconds,
      cacheHit: false, expiresAt: new Date(Date.now() - 1000).toISOString() })
    const request = vi.fn().mockImplementation(async (input: { thresholdSeconds: number }) => response(input.thresholdSeconds))
    useAppStore().setProviderForTesting(makeProvider({ createIsochrone: request }) as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40, crs: 'BD09' })
    await store.run(900)
    await store.run(900)
    expect(request).toHaveBeenCalledTimes(2)
    request.mockResolvedValue({ ...response(900), expiresAt: new Date(Date.now() + 60_000).toISOString(), status: 'partial' })
    await store.run(900)
    await store.run(900)
    expect(request).toHaveBeenCalledTimes(4)
    expect(store.rangeReused).toBe(false)
  })
  it('a shared budget edit discards old circle and POI state without starting another measurement', async () => {
    const request = vi.fn().mockResolvedValue({ taskId: 'old', status: 'complete', thresholdSeconds: 900 })
    useAppStore().setProviderForTesting(makeProvider({ createIsochrone: request }) as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40, crs: 'BD09' })
    await store.run(900)
    store.poisLoaded = true
    store.poiTruncated = true
    store.poiTruncationReason = 'page_budget'
    store.thresholdSeconds = 600
    expect(store.result).toBeNull()
    expect(store.heatLayers).toEqual([])
    expect(store.poisLoaded).toBe(false)
    expect(store.poiTruncated).toBe(false)
    expect(store.poiTruncationReason).toBeNull()
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('an old in-flight response cannot restore a circle after a shared budget edit', async () => {
    let release!: (value: unknown) => void
    const request = vi.fn(() => new Promise(resolve => { release = resolve }))
    useAppStore().setProviderForTesting(makeProvider({ createIsochrone: request }) as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40, crs: 'BD09' })
    const pending = store.run(900)
    store.thresholdSeconds = 300
    release({ taskId: 'old', status: 'complete', thresholdSeconds: 900 })
    await pending
    expect(store.result).toBeNull()
    expect(store.thresholdSeconds).toBe(300)
    expect(store.loading).toBe(false)
    expect(request).toHaveBeenCalledTimes(1)
  })
  it('圈内设施未查明不表示零家，切阈值清除旧计数和截断状态', async () => {
    const app = useAppStore()
    app.setProviderForTesting(makeProvider({
      createIsochrone: async () => ({ taskId: 't', status: 'complete' }),
      getIsochronePois: async () => ({ reachable: [], unreachable: [], pairsUsed: 0,
        retrieval: { truncated: true, truncationReason: 'page_budget' } }),
    }) as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40, crs: 'BD09' })
    expect(store.poisLoaded).toBe(false)
    await store.loadPois()
    expect(store.poisLoaded).toBe(true)
    expect(store.poiTruncated).toBe(true)
    await store.run(600)
    expect(store.poisLoaded).toBe(false)
    expect(store.poiTruncated).toBe(false)
    app.setProviderForTesting(makeProvider() as never)
    await store.loadPois()
    expect(store.poisLoaded).toBe(false)
  })
  it('热力分层独立请求各阈值，中心改变后丢弃旧层', async () => {
    const app = useAppStore()
    const calls: number[] = []
    let release!: (value: unknown) => void
    app.setProviderForTesting(makeProvider({ createIsochrone: vi.fn(async (request) => {
      calls.push(request.thresholdSeconds)
      return { taskId: 't', status: 'complete', thresholdSeconds: request.thresholdSeconds, radiiM: { 0: request.thresholdSeconds } }
    }) }) as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40, crs: 'BD09' })
    await store.run(900)
    await store.loadHeatLayers()
    expect(calls).toEqual([900, 300, 600])
    expect(store.heatLayers.map(layer => layer.thresholdSeconds)).toEqual([900, 600, 300])
    app.setProviderForTesting(makeProvider({ createIsochrone: () => new Promise(resolve => { release = resolve }) }) as never)
    const pending = store.loadHeatLayers()
    store.setOrigin({ lng: 116.4, lat: 40.1, crs: 'BD09' })
    release({ status: 'complete', thresholdSeconds: 300 })
    await pending
    expect(store.heatLayers).toEqual([])
    expect(store.heatLoading).toBe(false)
  })
  it('无起点时 run 给出可理解提示，不发起请求', async () => {
    const app = useAppStore()
    const provider = makeProvider()
    app.setProviderForTesting(provider as never)
    const store = useIsochroneStore()
    await store.run()
    expect(provider.createIsochrone).not.toHaveBeenCalled()
    expect(store.error).toContain('选择地点')
  })

  it('测量中禁止重复启动，结束后恢复切换', async () => {
    const app = useAppStore()
    // tsconfig 仍为 ES2022（Promise.withResolvers 未收录），沿用既有 new Promise 写法。
    let releaseFirst!: (value: unknown) => void
    const first = new Promise((resolve) => { releaseFirst = resolve })
    const provider = makeProvider({
      createIsochrone: vi.fn()
        .mockReturnValueOnce(first)
        .mockResolvedValueOnce({ taskId: 'new', status: 'complete', thresholdSeconds: 600 }),
    })
    app.setProviderForTesting(provider as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40.07, crs: 'BD09' }, '起点')
    const pending = store.run(900)
    expect(store.busy).toBe(true)
    await store.run(600)
    expect(provider.createIsochrone).toHaveBeenCalledTimes(1)
    expect(store.thresholdSeconds).toBe(900)
    releaseFirst({ taskId: 'old', status: 'complete', thresholdSeconds: 900 })
    await pending
    expect(store.busy).toBe(false)
    await store.run(600)
    expect(store.result?.taskId).toBe('new')
    expect(store.thresholdSeconds).toBe(600)
  })

  it('复位清理起点与结果', async () => {
    const app = useAppStore()
    app.setProviderForTesting(makeProvider({
      createIsochrone: vi.fn().mockResolvedValue({ taskId: 't', status: 'complete' }),
    }) as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40.07, crs: 'BD09' }, '起点')
    await store.run()
    store.reset()
    expect(store.origin).toBeNull()
    expect(store.result).toBeNull()
    expect(store.thresholdSeconds).toBe(900)
  })
})

describe('isochrone pois', () => {
  it('loadPois 把圈外接半径与阈值传给 provider，并写入可达结果', async () => {
    const { createPinia: mkPinia, setActivePinia: activate } = await import('pinia')
    activate(mkPinia())
    const { useAppStore } = await import('@/stores/app')
    const { useIsochroneStore } = await import('@/stores/isochrone')
    const app = useAppStore()
    const getIsochronePois = vi.fn().mockResolvedValue({
      traceId: 'p', mode: 'live', sourceKind: 'derived',
      reachable: [{ uid: 'u1', name: '药店A', walkSeconds: 300 }],
      unreachable: [], pairsUsed: 3, retrieval: {}, warnings: [],
    })
    app.setProviderForTesting(makeProvider({
      createIsochrone: vi.fn().mockResolvedValue({
        taskId: 't', status: 'complete', thresholdSeconds: 900,
        radiiM: { 0: 800 }, failedBearings: [], skippedBearings: [],
        algorithmVersion: 'v', warnings: [], cacheHit: false, pairsUsed: 1,
      }),
      getIsochronePois,
    }) as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40.07, crs: 'BD09' }, '起点')
    await store.run(900)
    store.poiTerms = '药店'
    await store.loadPois()
    expect(getIsochronePois).toHaveBeenCalledWith(expect.objectContaining({
      thresholdSeconds: 900,
      queryTerms: ['药店'],
      radiiM: { 0: 800 },
    }))
    expect(store.reachable).toHaveLength(1)
    expect(store.pairsUsedPois).toBe(3)
  })
})

describe('F71 threshold switch invalidates POI results', () => {
  it('clears stale POI rows when switching threshold', async () => {
    const { createPinia: mkPinia, setActivePinia: activate } = await import('pinia')
    activate(mkPinia())
    const { useAppStore } = await import('@/stores/app')
    const { useIsochroneStore } = await import('@/stores/isochrone')
    const app = useAppStore()
    app.setProviderForTesting({
      mode: 'live',
      getHealth: async () => ({ status: 'ok', mode: 'live', baiduConfigured: true, warnings: [], features: {} }),
      searchLocations: async () => ({ traceId: 't', mode: 'live', candidates: [], warnings: [] }),
      getWalkingRoute: async () => { throw new Error('no route') },
      getTravelMatrix: async () => { throw new Error('no matrix') },
      getCorridorPois: async () => { throw new Error('no corridor') },
      createIsochrone: async () => ({
        taskId: 't', status: 'complete', thresholdSeconds: 900,
        radiiM: { 0: 800 }, failedBearings: [], skippedBearings: [],
        algorithmVersion: 'v', warnings: [], cacheHit: false, pairsUsed: 1,
      }),
      getIsochronePois: async () => { throw new Error('no pois') },
      getCorridorEvidence: async () => { throw new Error('no evidence') },
      createPlan: async () => { throw new Error('no plan') },
      createReplan: async () => { throw new Error('no replan') },
      checkExplore: async () => [],
      checkCoverage: async () => ({ coverage: {}, coveredCount: 0, totalGrids: 0, blindGrids: [] }),
      listCases: async () => [],
      getCase: async () => ({}),
      getMapsConfig: async () => ({ configured: false, ak: '', version: '4.0' }),
    } as never)
    const store = useIsochroneStore()
    store.setOrigin({ lng: 116.3, lat: 40.07, crs: 'BD09' }, '起点')
    store.reachable = [{ uid: 'old', name: '旧POI', walkSeconds: 100 }]
    await store.run(600)
    // 切阈值即清空旧 POI 行，不把旧阈值结果留在新阈值下
    expect(store.reachable).toEqual([])
    expect(store.thresholdSeconds).toBe(600)
  })
})
