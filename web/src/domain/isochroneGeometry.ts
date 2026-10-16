import type { IsochroneResult, NamedCoord } from './types'
import { polygonFromRays } from './geo'
import { inLifeCircle, lifeCircleSamples } from './lifeCircle'

export function isochroneRings(origin: NamedCoord, result: IsochroneResult): { outer: NamedCoord[]; holes: NamedCoord[][] }[] {
  if (result.frontier) return result.frontier.polygons
  const outer = polygonFromRays(origin, result.radiiM)
  return outer.length >= 3 ? [{ outer, holes: [] }] : []
}

export function isochroneContains(origin: NamedCoord, result: IsochroneResult, point: NamedCoord): boolean {
  return isochroneRings(origin, result).some(p => inLifeCircle(point, p.outer) && !p.holes.some(h => inLifeCircle(point, h)))
}

export function isochroneSamples(origin: NamedCoord, result: IsochroneResult): { id: string; coord: NamedCoord }[] {
  if (!result.frontier) return lifeCircleSamples(origin, polygonFromRays(origin, result.radiiM))
  const polygons = isochroneRings(origin, result)
  const points = polygons.flatMap(p => p.outer)
  if (!points.length) return []
  const minLng = Math.min(...points.map(p => p.lng)), maxLng = Math.max(...points.map(p => p.lng))
  const minLat = Math.min(...points.map(p => p.lat)), maxLat = Math.max(...points.map(p => p.lat))
  const samples: NamedCoord[] = []
  if (isochroneContains(origin, result, origin)) samples.push(origin)
  for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) {
    const coord = { lng: minLng + (x + .5) / 5 * (maxLng - minLng), lat: minLat + (y + .5) / 5 * (maxLat - minLat), crs: origin.crs }
    if (isochroneContains(origin, result, coord)) samples.push(coord)
  }
  return samples.slice(0, 25).map((coord, i) => ({ id: `circle-${i}`, coord }))
}
