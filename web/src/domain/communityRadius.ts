import type { NamedCoord } from './types'

export interface RadiusFacilityGroup {
  label: string
  coords: NamedCoord[]
  complete: boolean
}
export interface RadiusCell {
  id: string
  coord: NamedCoord
  ring: NamedCoord[]
  missing: string[]
  unknown: string[]
  status: 'covered' | 'blind' | 'unknown'
  sizeM?: number
  boundary?: boolean
}

export const RADIUS_QUERY_M = 2200

function offset(origin: NamedCoord, east: number, north: number): NamedCoord {
  return { lng: origin.lng + east / (111320 * Math.cos(origin.lat * Math.PI / 180)),
    lat: origin.lat + north / 111320, crs: 'BD09' }
}

export function distanceM(a: NamedCoord, b: NamedCoord): number {
  const rad = Math.PI / 180
  const dLat = (b.lat - a.lat) * rad
  const dLng = (b.lng - a.lng) * rad
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2
  return 6371000 * 2 * Math.asin(Math.min(1, Math.sqrt(h)))
}

/** 500m 格的中心采样；1km 是周边地理半径，不替代步行等时圈。 */
export function createCommunitySamples(origin: NamedCoord): RadiusCell[] {
  return [-500, 0, 500].flatMap((east, x) => [-500, 0, 500].map((north, y) => {
    const coord = offset(origin, east, north)
    return { id: `radius-${x}-${y}`, coord,
      ring: [[-250, -250], [250, -250], [250, 250], [-250, 250]].map(([e, n]) => offset(coord, e, n)),
      missing: [], unknown: [], status: 'unknown' }
  }))
}

/** 整格距离上下界判定；边界格细分至62.5m，仍不确定则保留未知。 */
export function assessRadius(origin: NamedCoord, groups: RadiusFacilityGroup[]): RadiusCell[] {
  const cells: RadiusCell[] = []
  function visit(east: number, north: number, size: number, id: string): void {
    const coord = offset(origin, east, north)
    const half = size / 2
    const ring = [[-half, -half], [half, -half], [half, half], [-half, half]].map(([e, n]) => offset(coord, e, n))
    // 经线+纬线路径的保守上界，任意格内位置到中心的距离不大于该值。
    const radius = Math.max(...ring.map(p => 6371000 * Math.PI / 180 * (Math.abs(p.lat - coord.lat) + Math.abs(p.lng - coord.lng)))) + 0.1
    const missing: string[] = []
    const unknown: string[] = []
    let boundary = false
    for (const group of groups) {
      const nearest = Math.min(...group.coords.map(place => distanceM(coord, place)))
      if (nearest + radius <= 1000) continue
      if (group.complete && nearest - radius > 1000) missing.push(group.label)
      else {
        unknown.push(group.label)
        if (group.coords.length && nearest - radius <= 1000) boundary = true
      }
    }
    if (!missing.length && boundary && size > 62.5) {
      for (const [index, [dx, dy]] of [[-1, -1], [1, -1], [1, 1], [-1, 1]].entries()) {
        visit(east + dx * size / 4, north + dy * size / 4, size / 2, `${id}-${index}`)
      }
      return
    }
    cells.push({ id, coord, ring, sizeM: size, boundary, missing, unknown,
      status: missing.length ? 'blind' : !groups.length || unknown.length ? 'unknown' : 'covered' })
  }
  for (let x = 0; x < 6; x++) {
    for (let y = 0; y < 6; y++) visit(-625 + x * 250, -625 + y * 250, 250, `area-${x}-${y}`)
  }
  return cells
}
