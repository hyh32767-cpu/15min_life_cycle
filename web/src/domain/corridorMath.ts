import type { NamedCoord } from './types'

const M_PER_DEG = 111320.0

/** T108：走廊召回的纯几何部分（与后端 api/app/services/corridor.py 同语义，平面近似，2km 尺度误差可忽略）。 */
export function haversineM(lng1: number, lat1: number, lng2: number, lat2: number): number {
  const rad = Math.PI / 180
  const dLat = (lat2 - lat1) * rad
  const dLng = (lng2 - lng1) * rad
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2
  return 2 * 6371000 * Math.asin(Math.sqrt(a))
}

function interpolate(a: NamedCoord, b: NamedCoord, ratio: number): NamedCoord {
  return {
    lng: a.lng + (b.lng - a.lng) * ratio,
    lat: a.lat + (b.lat - a.lat) * ratio,
    crs: a.crs,
  }
}

export function sampleCenters(points: NamedCoord[], spacingM: number, radiusM: number): NamedCoord[] {
  if (points.length < 2) return [...points]
  const spacing = spacingM > 0 ? spacingM : radiusM
  let total = 0
  for (let i = 0; i + 1 < points.length; i += 1) {
    total += haversineM(points[i].lng, points[i].lat, points[i + 1].lng, points[i + 1].lat)
  }
  if (total <= 0) return [points[0]]
  const centers: NamedCoord[] = []
  let distance = 0
  let travelled = 0
  let segIndex = 0
  let segLen = haversineM(points[0].lng, points[0].lat, points[1].lng, points[1].lat)
  while (distance <= total) {
    while (segIndex < points.length - 2 && travelled + segLen < distance) {
      travelled += segLen
      segIndex += 1
      segLen = haversineM(
        points[segIndex].lng, points[segIndex].lat,
        points[segIndex + 1].lng, points[segIndex + 1].lat,
      )
    }
    const remain = distance - travelled
    const ratio = segLen > 0 ? remain / segLen : 0
    centers.push(interpolate(points[segIndex], points[segIndex + 1], Math.min(1, Math.max(0, ratio))))
    distance += spacing
  }
  const last = points[points.length - 1]
  const tail = centers[centers.length - 1]
  if (!tail || tail.lng !== last.lng || tail.lat !== last.lat) centers.push(last)
  return centers
}

function pointToSegmentM(p: NamedCoord, a: NamedCoord, b: NamedCoord): number {
  const latRef = ((a.lat + b.lat) / 2) * (Math.PI / 180)
  const bx = (b.lng - a.lng) * M_PER_DEG * Math.cos(latRef)
  const by = (b.lat - a.lat) * M_PER_DEG
  const px = (p.lng - a.lng) * M_PER_DEG * Math.cos(latRef)
  const py = (p.lat - a.lat) * M_PER_DEG
  const ab2 = bx * bx + by * by
  if (ab2 <= 0) return Math.hypot(px, py)
  const t = Math.min(1, Math.max(0, (px * bx + py * by) / ab2))
  return Math.hypot(px - bx * t, py - by * t)
}

export function pointToPolylineM(p: NamedCoord, points: NamedCoord[]): number {
  if (!points.length) return Infinity
  if (points.length === 1) {
    return haversineM(p.lng, p.lat, points[0].lng, points[0].lat)
  }
  let best = Infinity
  for (let i = 0; i + 1 < points.length; i += 1) {
    best = Math.min(best, pointToSegmentM(p, points[i], points[i + 1]))
  }
  return best
}
