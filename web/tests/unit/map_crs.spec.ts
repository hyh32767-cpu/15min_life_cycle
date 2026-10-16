import { describe, expect, it } from 'vitest'

import { assertSameCrs } from '@/domain/mapCrs'
import { boundsOf, projectPolyline } from '@/domain/projection'

describe('mapCrs', () => {
  it('rejects mixed CRS instead of silently mixing', () => {
    expect(() => assertSameCrs([
      { lng: 116.3, lat: 39.9, crs: 'BD09' },
      { lng: 116.31, lat: 39.91, crs: 'GCJ02' },
    ])).toThrow('CRS_MISMATCH')
  })

  it('accepts single-CRS layers and projects identically', () => {
    const points = [
      { lng: 116.3, lat: 39.9, crs: 'BD09' as const },
      { lng: 116.31, lat: 39.91, crs: 'BD09' as const },
    ]
    expect(() => assertSameCrs(points)).not.toThrow()
    const bounds = boundsOf(points)!
    // 同一坐标走同一投影：像素字符串一致（对齐是结构性的）。
    expect(projectPolyline(points, bounds, 560, 320)).toBe(projectPolyline(points, bounds, 560, 320))
  })
})
