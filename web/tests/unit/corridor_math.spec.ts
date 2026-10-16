import { describe, expect, it } from 'vitest'

import { pointToPolylineM, sampleCenters } from '@/domain/corridorMath'

describe('corridorMath', () => {
  it('samples route centers including both endpoints', () => {
    const pts = [
      { lng: 116.364009, lat: 40.091438, crs: 'BD09' as const },
      { lng: 116.35, lat: 40.085, crs: 'BD09' as const },
      { lng: 116.331789, lat: 40.078588, crs: 'BD09' as const },
    ]
    const centers = sampleCenters(pts, 800, 800)
    expect(centers.length).toBeGreaterThanOrEqual(2)
    expect(centers[0]).toEqual(pts[0])
    expect(centers[centers.length - 1]).toEqual(pts[pts.length - 1])
  })

  it('measures on-route points near zero and far points large', () => {
    const line = [
      { lng: 0, lat: 0, crs: 'BD09' as const },
      { lng: 0.01, lat: 0, crs: 'BD09' as const },
    ]
    expect(pointToPolylineM({ lng: 0.005, lat: 0, crs: 'BD09' }, line)).toBeLessThan(1)
    expect(pointToPolylineM({ lng: 0.005, lat: 0.05, crs: 'BD09' }, line)).toBeGreaterThan(1000)
  })
})
