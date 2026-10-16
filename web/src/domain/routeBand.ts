import type { NamedCoord } from './types'

/** 填色片均为无孔洞的并集片；只用于近似范围展示，不替代有向 OD 可行性。 */
export function inMeasuredBand(point: NamedCoord, fills: NamedCoord[][]): boolean {
  if (point.crs !== 'BD09') return false
  return fills.some(ring => {
    let inside = false
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const a = ring[i]!, b = ring[j]!
      const cross = (point.lng - a.lng) * (b.lat - a.lat) - (point.lat - a.lat) * (b.lng - a.lng)
      if (Math.abs(cross) < 1e-12 && point.lng >= Math.min(a.lng, b.lng) && point.lng <= Math.max(a.lng, b.lng)
        && point.lat >= Math.min(a.lat, b.lat) && point.lat <= Math.max(a.lat, b.lat)) return true
      if ((a.lat > point.lat) !== (b.lat > point.lat)
        && point.lng < (b.lng - a.lng) * (point.lat - a.lat) / (b.lat - a.lat) + a.lng) inside = !inside
    }
    return inside
  })
}
