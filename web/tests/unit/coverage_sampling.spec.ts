import { expect, it, vi } from 'vitest'
import { measureCoverage } from '@/domain/coverageSampling'
import type { NamedCoord } from '@/domain/types'
import type { TravelMatrixResult } from '@/providers/contracts'

const point = (lng: number): NamedCoord => ({ lng, lat: 40, crs: 'BD09' })
const grids = Array.from({ length: 9 }, (_, index) => ({ id: `g${index}`, coord: point(index) }))
const facilities = Array.from({ length: 5 }, (_, index) => ({ id: `f${index}`, coord: point(100 + index) }))
function matrix(values: (number | null)[]): TravelMatrixResult {
  return { traceId: 'test', mode: 'live', sourceKind: 'derived', cacheHit: false, warnings: [],
    cells: values.map((durationSeconds, fromIndex) => ({ fromIndex, toIndex: 0, durationSeconds,
      distanceM: null, status: durationSeconds == null ? 'no_route' : 'ok', sourceKind: 'derived' })) }
}

it('proves full coverage with nine pairs instead of forty-five', async () => {
  const measure = vi.fn(async (origins: NamedCoord[]) => matrix(origins.map(() => 600)))
  const times = await measureCoverage(grids, facilities, 900, measure)
  expect(times).toHaveLength(9)
  expect(measure).toHaveBeenCalledTimes(1)
})

it('matches exhaustive directed matrix oracle on 40 varied small graphs', async () => {
  for (let seed = 0; seed < 40; seed++) {
    const dense = grids.map((_grid, i) => facilities.map((_facility, j) => {
      const value = (seed * 53 + i * 137 + j * 239) % 1700
      return value % 11 === 0 ? null : value
    }))
    let pairs = 0
    const measured = await measureCoverage(grids, facilities, 900, async (origins, destinations) => {
      pairs += origins.length * destinations.length
      return matrix(origins.map(origin => dense[origin.lng]![destinations[0]!.lng - 100]!))
    })
    for (const [index, grid] of grids.entries()) {
      const expected = dense[index]!.some(time => time != null && time <= 900)
      expect(measured.some(cell => cell.fromGrid === grid.id && cell.status === 'ok' && cell.durationSeconds! <= 900)).toBe(expected)
      if (!expected) expect(measured.filter(cell => cell.fromGrid === grid.id)).toHaveLength(5)
    }
    expect(pairs).toBeLessThanOrEqual(45)
  }
})

it('unknown measurement cannot prove absence, but another reachable candidate proves coverage', async () => {
  const broken = async () => ({ ...matrix([null]), cells: [{ ...matrix([null]).cells[0]!, status: 'error' as const }] })
  await expect(measureCoverage(grids.slice(0, 1), facilities.slice(0, 1), 900, broken)).rejects.toThrow('未查明')
  let round = 0
  const times = await measureCoverage(grids.slice(0, 1), facilities.slice(0, 2), 900, async () => ++round === 1 ? broken() : matrix([600]))
  expect(times.some(cell => cell.durationSeconds === 600)).toBe(true)
})

it('stale generation stops before another upstream request', async () => {
  let current = true
  const measure = vi.fn(async () => { current = false; return matrix([1200]) })
  expect(await measureCoverage(grids.slice(0, 1), facilities, 900, measure, () => current)).toEqual([])
  expect(measure).toHaveBeenCalledTimes(1)
})
