import { describe, expect, it } from 'vitest'

import { rankCandidate } from '@/domain/commute'
import { boundsOf, projectPoint } from '@/domain/projection'

describe('rankCandidate', () => {
  it('computes detour, finish and slack from directional times', () => {
    const result = rankCandidate({
      startToPoiSeconds: 600,
      poiToEndSeconds: 500,
      baselineSeconds: 1000,
      waitSeconds: 60,
      serviceSeconds: 300,
      departureSeconds: 0,
      deadlineSeconds: 1460,
    })
    expect(result.feasible).toBe(true)
    expect(result.extraTravelSeconds).toBe(100)
    expect(result.finishSeconds).toBe(1460)
    expect(result.slackSeconds).toBe(0)
  })

  it('rejects missing route budget and deadline', () => {
    expect(rankCandidate({
      startToPoiSeconds: null,
      poiToEndSeconds: 500,
      baselineSeconds: 1000,
    }).reasons).toContain('NO_ROUTE')

    const over = rankCandidate({
      startToPoiSeconds: 600,
      poiToEndSeconds: 500,
      baselineSeconds: 1000,
      maxExtraTravelSeconds: 50,
      deadlineSeconds: 1000,
    })
    expect(over.feasible).toBe(false)
    expect(over.reasons).toEqual(expect.arrayContaining(['EXTRA_BUDGET', 'DEADLINE']))
  })
})

describe('projection', () => {
  it('projects a route north-up into svg bounds', () => {
    const points = [
      { lng: 116.3, lat: 39.9, crs: 'BD09' as const },
      { lng: 116.31, lat: 39.91, crs: 'BD09' as const },
    ]
    const bounds = boundsOf(points)!
    const topLeft = projectPoint(points[1], bounds, 200, 100)
    const bottomRight = projectPoint(points[0], bounds, 200, 100)
    expect(topLeft.y).toBeLessThan(bottomRight.y)
    expect(topLeft.x).toBeGreaterThan(bottomRight.x)
  })
})

describe('F36 opening-hours ranking', () => {
  it('marks known-closed POI infeasible with CLOSED', async () => {
    const { rankCandidate } = await import('@/domain/commute')
    const closed = rankCandidate({
      startToPoiSeconds: 100,
      poiToEndSeconds: 100,
      baselineSeconds: 500,
      waitSeconds: 0,
      serviceSeconds: 600,
      departureSeconds: 64800,
      deadlineSeconds: 100000,
      maxExtraTravelSeconds: 10000,
      place: {
        name: 'P',
        coord: { lng: 1, lat: 1, crs: 'BD09' },
        source: 'api-cache',
        shopHours: '09:00-10:00',
      },
    })
    expect(closed.feasible).toBe(false)
    expect(closed.reasons).toContain('CLOSED')
  })

  it('keeps unknown hours feasible and marked unknown', async () => {
    const { rankCandidate } = await import('@/domain/commute')
    const unknown = rankCandidate({
      startToPoiSeconds: 100,
      poiToEndSeconds: 100,
      baselineSeconds: 500,
      waitSeconds: 0,
      serviceSeconds: 100,
      departureSeconds: 0,
      deadlineSeconds: 10000,
      maxExtraTravelSeconds: 10000,
      place: { name: 'P', coord: { lng: 1, lat: 1, crs: 'BD09' }, source: 'api-cache' },
    })
    expect(unknown.feasible).toBe(true)
    expect(unknown.windowSource).toBe('unknown')
  })
})

describe('F38 invalid numeric input', () => {
  it('marks NaN timing as INVALID_INPUT instead of feasible', async () => {
    const { rankCandidate } = await import('@/domain/commute')
    const bad = rankCandidate({
      startToPoiSeconds: NaN,
      poiToEndSeconds: 100,
      baselineSeconds: 500,
      waitSeconds: NaN,
      serviceSeconds: 100,
    })
    expect(bad.feasible).toBe(false)
    expect(bad.reasons).toContain('INVALID_INPUT')
  })
})
