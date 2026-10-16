import type { NamedCoord } from './types'

const METERS_PER_DEGREE = 111320

export function destAt(
  origin: NamedCoord,
  bearingDeg: number,
  distanceM: number,
): NamedCoord {
  const safeDist = Number.isFinite(distanceM) && distanceM >= 0 ? distanceM : 0
  const latRad = (origin.lat * Math.PI) / 180
  const dLat = (safeDist * Math.cos((bearingDeg * Math.PI) / 180)) / METERS_PER_DEGREE
  const dLng = (safeDist * Math.sin((bearingDeg * Math.PI) / 180))
    / (METERS_PER_DEGREE * Math.cos(latRad))
  return { lng: origin.lng + dLng, lat: origin.lat + dLat, crs: origin.crs }
}

export function polygonFromRays(
  center: NamedCoord,
  radiiByBearing: Record<string, number | null | undefined>,
): NamedCoord[] {
  return Object.entries(radiiByBearing)
    .map(([bearing, radius]) => ({ bearing: Number(bearing), radius }))
    .filter((item) => Number.isFinite(item.bearing)
      && item.radius != null && Number.isFinite(item.radius) && item.radius > 0)
    .sort((a, b) => a.bearing - b.bearing)
    .map((item) => destAt(center, item.bearing, item.radius as number))
}

