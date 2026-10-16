import type { NamedCoord } from './types'
import type { CoverageTimeInput, TravelMatrixResult } from '@/providers/contracts'

type Facility = { id: string; coord: NamedCoord }
type Measure = (origins: NamedCoord[], destinations: NamedCoord[]) => Promise<TravelMatrixResult>

/** 覆盖是 OR：一个已测可达设施足以证明覆盖；未覆盖须检查全部候选。 */
export async function measureCoverage(grids: { id: string; coord: NamedCoord }[], facilities: Facility[],
  threshold: number, measure: Measure, isCurrent: () => boolean = () => true): Promise<CoverageTimeInput[]> {
  // 调用方传入按距社区中心排序的候选；统一顺序使一轮合并成一个矩阵请求。
  const pending = grids.map(grid => ({ grid, facilities, done: false, unknown: false }))
  const times: CoverageTimeInput[] = []
  for (let round = 0; round < facilities.length; round++) {
    if (!isCurrent()) return times
    const groups = new Map<string, typeof pending>()
    for (const row of pending.filter(row => !row.done)) {
      const id = row.facilities[round]!.id
      const group = groups.get(id) ?? []
      group.push(row)
      groups.set(id, group)
    }
    for (const rows of groups.values()) {
      if (!isCurrent()) return times
      const facility = rows[0]!.facilities[round]!
      const matrix = await measure(rows.map(row => row.grid.coord), [facility.coord])
      if (!isCurrent()) return times
      rows.forEach((row, index) => {
        const cell = matrix.cells.find(cell => cell.fromIndex === index && cell.toIndex === 0)
        const valid = cell?.status === 'ok' && cell.durationSeconds != null && Number.isFinite(cell.durationSeconds) && cell.durationSeconds >= 0
        times.push({ fromGrid: row.grid.id, toFacility: facility.id, durationSeconds: valid ? cell.durationSeconds : null,
          status: valid ? 'ok' : cell?.status === 'no_route' ? 'no_route' : 'error' })
        if (valid && cell.durationSeconds! <= threshold) row.done = true
        else if (cell?.status !== 'no_route' && !valid) row.unknown = true
      })
    }
  }
  if (pending.some(row => !row.done && row.unknown)) throw new Error('部分步行路线未查明，暂不评分')
  return times
}
