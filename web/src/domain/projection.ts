import type { NamedCoord } from './types'

export interface MapBounds {
  minLng: number
  minLat: number
  maxLng: number
  maxLat: number
}

export function boundsOf(points: NamedCoord[]): MapBounds | null {
  if (!points.length) {
    return null
  }
  let minLng = Infinity
  let minLat = Infinity
  let maxLng = -Infinity
  let maxLat = -Infinity
  for (const point of points) {
    minLng = Math.min(minLng, point.lng)
    minLat = Math.min(minLat, point.lat)
    maxLng = Math.max(maxLng, point.lng)
    maxLat = Math.max(maxLat, point.lat)
  }
  return { minLng, minLat, maxLng, maxLat }
}

export function projectPoint(
  point: NamedCoord,
  bounds: MapBounds,
  width: number,
  height: number,
  padding = 12,
): { x: number; y: number } {
  const midLat = (bounds.minLat + bounds.maxLat) / 2
  const cos = Math.cos((midLat * Math.PI) / 180)
  const xSpan = Math.max((bounds.maxLng - bounds.minLng) * cos, 1e-9)
  const ySpan = Math.max(bounds.maxLat - bounds.minLat, 1e-9)
  const innerWidth = Math.max(width - padding * 2, 1)
  const innerHeight = Math.max(height - padding * 2, 1)
  const scale = Math.min(innerWidth / xSpan, innerHeight / ySpan)
  const drawnWidth = xSpan * scale
  const drawnHeight = ySpan * scale
  const offsetX = (width - drawnWidth) / 2
  const offsetY = (height - drawnHeight) / 2
  const x = offsetX + (point.lng - bounds.minLng) * cos * scale
  const y = height - (offsetY + (point.lat - bounds.minLat) * scale)
  return { x, y }
}

export function projectPolyline(
  points: NamedCoord[],
  bounds: MapBounds,
  width: number,
  height: number,
): string {
  return points
    .map((point) => {
      const { x, y } = projectPoint(point, bounds, width, height)
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
}
