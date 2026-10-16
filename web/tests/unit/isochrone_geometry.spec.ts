import { describe, expect, it } from 'vitest'
import { isochroneContains, isochroneSamples } from '@/domain/isochroneGeometry'
import type { IsochroneResult, NamedCoord } from '@/domain/types'

const point = (lng: number, lat: number): NamedCoord => ({ lng, lat, crs: 'BD09' })
const ring = (a: number, b: number) => [point(a,a),point(b,a),point(b,b),point(a,b),point(a,a)]
const circle = { status: 'complete', radiiM: { 0: 1000, 90: 1000, 180: 1000, 270: 1000 },
  frontier: { polygons: [{ outer: ring(0,10), holes: [ring(2,4)] }, { outer: ring(20,22), holes: [] }],
    previewContours: [ring(30,40)], previewOnly: true } } as unknown as IsochroneResult

describe('frontier classification geometry', () => {
  it('preserves holes and multiple components, excludes fitted previews', () => {
    expect(isochroneContains(point(1,1),circle,point(3,3))).toBe(false)
    expect(isochroneContains(point(1,1),circle,point(6,6))).toBe(true)
    expect(isochroneContains(point(1,1),circle,point(21,21))).toBe(true)
    expect(isochroneContains(point(1,1),circle,point(35,35))).toBe(false)
    expect(isochroneSamples(point(1,1),circle).every(p => isochroneContains(point(1,1),circle,p.coord))).toBe(true)
  })
})
