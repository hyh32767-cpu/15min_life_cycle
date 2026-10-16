import { describe, expect, it } from 'vitest'
import { circleSearchRadius, inLifeCircle, lifeCircleSamples } from '@/domain/lifeCircle'
import { polygonFromRays } from '@/domain/geo'
import type { NamedCoord } from '@/domain/types'

const origin: NamedCoord = { lng: 116, lat: 40, crs: 'BD09' }
const ring = polygonFromRays(origin, Object.fromEntries([0, 45, 90, 135, 180, 225, 270, 315].map(b => [b, 500])))
describe('生活圈范围统一', () => {
  it('只生成当前边界内的点，包含中心且不重复', () => {
    const samples = lifeCircleSamples(origin, ring)
    expect(samples.length).toBeGreaterThan(9)
    expect(samples.length).toBeLessThanOrEqual(25)
    expect(samples.every(sample => inLifeCircle(sample.coord, ring))).toBe(true)
    expect(samples[0].coord).toEqual(origin)
    expect(new Set(samples.map(p => `${p.coord.lng},${p.coord.lat}`)).size).toBe(samples.length)
  })
  it('短时间圈不会继续沿用固定500米九点或1公里检索', () => {
    const short = polygonFromRays(origin, { 0: 100, 90: 100, 180: 100, 270: 100 })
    expect(circleSearchRadius(origin, short)).toBeLessThan(200)
    expect(lifeCircleSamples(origin, short).every(p => inLifeCircle(p.coord, short))).toBe(true)
    expect(inLifeCircle({ ...origin, lng: origin.lng + 0.01 }, short)).toBe(false)
  })
  it('空边界和混坐标不生成假范围，边界点保留', () => {
    expect(lifeCircleSamples(origin, [])).toEqual([])
    expect(inLifeCircle({ ...origin, crs: 'WGS84' }, ring)).toBe(false)
    expect(ring.every(p => inLifeCircle(p, ring))).toBe(true)
  })
})
