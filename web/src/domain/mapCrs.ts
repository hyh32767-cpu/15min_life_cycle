import type { NamedCoord } from './types'

/**
 * T110：地图 CRS 单一出口。所有进入同一 bounds 的坐标必须同系，
 * 混系时直接抛错，不静默混算。调用方（RouteMap）在 bounds 前先过这一关。
 */
export function assertSameCrs(points: NamedCoord[]): void {
  const seen = new Set<string>()
  for (const point of points) {
    if (point?.crs) seen.add(point.crs)
  }
  if (seen.size > 1) {
    throw new Error(`CRS_MISMATCH: 地图图层坐标系不一致（${[...seen].join(' / ')}），拒绝混系投影`)
  }
}
