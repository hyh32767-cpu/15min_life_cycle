import type { NamedCoord } from '@/domain/types'

/** Local display-only corner rounding. Never use these points for reachability. */
export function roundContour(coords: NamedCoord[]): NamedCoord[] {
  if (coords.length < 3) return coords
  const origin = coords[0]!
  const sx = 111320 * Math.cos(origin.lat * Math.PI / 180), sy = 111320
  type XY = [number, number]
  const points: XY[] = coords.map(p => [(p.lng - origin.lng) * sx, (p.lat - origin.lat) * sy])
  const same = (a: XY, b: XY) => Math.hypot(a[0] - b[0], a[1] - b[1]) < .01
  const closed = same(points[0]!, points.at(-1)!), compact: XY[] = []
  for (const p of closed ? points.slice(0, -1) : points) {
    if (compact.length && same(compact.at(-1)!, p)) continue
    while (compact.length >= 2) {
      const a = compact.at(-2)!, b = compact.at(-1)!, dx = p[0] - a[0], dy = p[1] - a[1], length = Math.hypot(dx, dy)
      if (!length || Math.abs(dx * (b[1] - a[1]) - dy * (b[0] - a[0])) / length > .25
        || (b[0] - a[0]) * (p[0] - b[0]) + (b[1] - a[1]) * (p[1] - b[1]) < 0) break
      compact.pop()
    }
    compact.push(p)
  }
  if (compact.length < 3) return coords
  const rounded: XY[] = []
  compact.forEach((p, i) => {
    if (!closed && (i === 0 || i === compact.length - 1)) { rounded.push(p); return }
    const a = compact[(i - 1 + compact.length) % compact.length]!, b = compact[(i + 1) % compact.length]!
    const before = Math.hypot(a[0] - p[0], a[1] - p[1]), after = Math.hypot(b[0] - p[0], b[1] - p[1])
    const cut = Math.min(25, before * .35, after * .35)
    if (!cut) { rounded.push(p); return }
    const entry: XY = [p[0] + (a[0] - p[0]) * cut / before, p[1] + (a[1] - p[1]) * cut / before]
    const exit: XY = [p[0] + (b[0] - p[0]) * cut / after, p[1] + (b[1] - p[1]) * cut / after]
    rounded.push(entry)
    for (let j = 1; j <= 8; j++) {
      const t = j / 8, u = 1 - t
      rounded.push([u*u*entry[0]+2*u*t*p[0]+t*t*exit[0], u*u*entry[1]+2*u*t*p[1]+t*t*exit[1]])
    }
  })
  if (closed) rounded.push(rounded[0]!)
  return rounded.map(([x, y]) => ({ lng: origin.lng + x / sx, lat: origin.lat + y / sy, crs: origin.crs }))
}
