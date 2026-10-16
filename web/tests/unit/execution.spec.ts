import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import type { AppProvider } from '@/providers/contracts'
import { useAppStore } from '@/stores/app'
import { useCommuteStore } from '@/stores/commute'
import { useExecutionStore } from '@/stores/execution'
import { usePlanStore } from '@/stores/plan'

function coord(lng: number, lat: number) {
  return { lng, lat, crs: 'BD09' as const }
}

function makeProvider() {
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
    getCorridorPois: async () => { throw new Error('no corridor') },
    getRouteBand: async () => { throw new Error('unexpected route-band request') },
    createIsochrone: async () => { throw new Error('no iso') },
    getIsochronePois: async () => { throw new Error('no pois') },
    getCorridorEvidence: async () => { throw new Error('no evidence') },
    createPlan: async (request) => ({
      status: 'ready',
      alternatives: [{
        stops: request.tasks.flatMap((t) => t.options.slice(0, 1).map((o) => ({
          taskId: t.id, placeId: o.placeId,
          arrivalSeconds: 100, startSeconds: 100,
          finishSeconds: 200, waitSeconds: 0, travelSeconds: 100,
          travelSourceKind: 'api-cache', serviceSourceKind: 'user-input',
          windowSourceKind: 'unknown',
        }))),
        timeline: [],
        departureSeconds: request.departureSeconds,
        finishSeconds: request.departureSeconds + 500,
        deadlineSeconds: request.deadlineSeconds,
        slackSeconds: 100,
        totalTravelSeconds: 300, totalWaitSeconds: 0, totalServiceSeconds: 200,
        totalWalkingM: 300, returnTravelSeconds: 100, returnTravelSourceKind: 'api-cache',
      }],
      infeasibleReasons: {}, warnings: [], suggestions: [],
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

describe('execution precedence guard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('keeps edited waypoint order in the execution replan request', async () => {
    const provider = makeProvider()
    let received: string[] = []
    provider.createReplan = async request => {
      received = request.tasks[1]!.precedenceIds ?? []
      throw new Error('stop after request inspection')
    }
    useAppStore().setProviderForTesting(provider)
    const commute = useCommuteStore()
    commute.restoring = true
    commute.company = { name: 'S', coord: coord(116, 40), source: 'api-cache' }
    commute.home = { name: 'H', coord: coord(116.1, 40.1), source: 'api-cache' }
    const plan = usePlanStore()
    const a = plan.addFixedTask({ name: 'A', uid: 'A', coord: coord(116.01, 40), source: 'user-input' }, 1)
    const b = plan.addFixedTask({ name: 'B', uid: 'B', coord: coord(116.02, 40), source: 'user-input' }, 1)
    plan.setVisitOrder([b, a])
    await plan.runPlan()
    await useExecutionStore().runReplan('18:00')
    expect(received).toEqual([b])
    commute.resetState()
  })

  it('blocks completing a successor before its predecessor', async () => {
    const app = useAppStore()
    app.setProviderForTesting(makeProvider())
    const plan = usePlanStore()
    const execution = useExecutionStore()
    const commute = useCommuteStore()
    commute.company = { name: 'S', coord: coord(1, 1), source: 'api-cache' }
    commute.home = { name: 'H', coord: coord(2, 2), source: 'api-cache' }
    const a = plan.addFixedTask({ name: 'A', coord: coord(1, 1), source: 'user-input', uid: 'A' }, 5)
    const b = plan.addFixedTask({ name: 'B', coord: coord(2, 2), source: 'user-input', uid: 'B' }, 5)
    plan.togglePrecedence(b, a)
    await plan.runPlan()
    expect(plan.result?.status).toBe('ready')
    expect(execution.canComplete(b)).toBe(false)
    expect(execution.blockReason(b)).toMatch('A')
    execution.completeTask(b)
    expect(execution.completedTaskIds).not.toContain(b)
    expect(execution.currentNodeId).toBe('S')
    execution.completeTask(a)
    expect(execution.completedTaskIds).toContain(a)
    expect(execution.canComplete(b)).toBe(true)
    execution.completeTask(b)
    expect(execution.completedTaskIds).toContain(b)
    expect(execution.currentNodeId).toBe('B')
  })

  it('skipping does not teleport to the task or charge its travel/service', async () => {
    const plan = usePlanStore()
    const execution = useExecutionStore()
    const id = plan.addFixedTask({ name: 'A', uid: 'A', coord: coord(116, 40), source: 'user-input' }, 5)
    execution.currentTimeSeconds = 64800
    execution.skipTask(id)
    expect(execution.currentNodeId).toBe('S')
    expect(execution.currentTimeSeconds).toBe(64800)
    expect(execution.completedPlaceIds).toEqual([])
    expect(execution.skippedTaskIds).toEqual([id])
  })

  it('after replan completion uses the replacement place and updated timeline', async () => {
    const app = useAppStore()
    const provider = makeProvider()
    app.setProviderForTesting(provider)
    const plan = usePlanStore()
    const execution = useExecutionStore()
    const commute = useCommuteStore()
    commute.company = { name: 'S', coord: coord(116, 40), source: 'api-cache' }
    commute.home = { name: 'H', coord: coord(116.1, 40.1), source: 'api-cache' }
    const id = plan.addFixedTask({ name: 'A', uid: 'A', coord: coord(116.05, 40.05), source: 'user-input' }, 5)
    await plan.runPlan()
    const original = plan.result!
    provider.createReplan = async () => ({ status: 'ready', lockedCompleted: [], appliedEvents: [], reason: '',
      plan: { ...original, alternatives: [{ ...original.alternatives[0],
        stops: [{ ...original.alternatives[0].stops[0], taskId: id, placeId: 'B', finishSeconds: 777 }],
        finishSeconds: 900 }] } })
    await execution.runReplan('18:00')
    expect(execution.baseAlternative?.finishSeconds).toBe(900)
    execution.completeTask(id)
    expect(execution.currentNodeId).toBe('B')
    expect(execution.currentTimeSeconds).toBe(777)
  })
})
