import { describe, expect, it } from 'vitest'

import { destAt, polygonFromRays } from '@/domain/geo'

describe('geo.destAt', () => {
  it('moves east/west/north by the requested distance', () => {
    const center = { lng: 116.3, lat: 39.9, crs: 'BD09' as const }
    const east = destAt(center, 90, 1000)
    const west = destAt(center, 270, 1000)
    const north = destAt(center, 0, 1000)
    expect(east.lng).toBeGreaterThan(center.lng)
    expect(west.lng).toBeLessThan(center.lng)
    expect(north.lat).toBeGreaterThan(center.lat)
  })
})

describe('polygonFromRays', () => {
  it('preserves a narrow measured concavity instead of smoothing it into false coverage', () => {
    const center = { lng: 116.3, lat: 39.9, crs: 'BD09' as const }
    const polygon = polygonFromRays(center, { 0: 900, 45: 80, 90: 900, 180: 300, 270: 700 })
    expect(polygon[1]).toEqual(destAt(center, 45, 80))
    expect(polygon[0]).toEqual(destAt(center, 0, 900))
    expect(destAt(center, 0, 0)).toEqual(center)
  })
  it('builds an ordered polygon from measured ray radii', () => {
    const center = { lng: 116.3, lat: 39.9, crs: 'BD09' as const }
    const polygon = polygonFromRays(center, { '90': 800, '0': 600, '180': 700 })
    expect(polygon).toHaveLength(3)
    expect(polygon[0].lat).toBeGreaterThan(center.lat) // bearing 0 first
    expect(polygon[1].lng).toBeGreaterThan(center.lng) // bearing 90 second
    expect(polygon[2].lng).toBeLessThanOrEqual(center.lng + 1e-9) // bearing 180 last
  })

  it('ignores missing rays and returns empty when fewer than one', () => {
    const center = { lng: 116.3, lat: 39.9, crs: 'BD09' as const }
    expect(polygonFromRays(center, { '0': null, '90': undefined })).toEqual([])
  })
})
