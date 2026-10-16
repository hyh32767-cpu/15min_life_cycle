import { describe, expect, it } from 'vitest'
import { assessRadius, createCommunitySamples, distanceM, RADIUS_QUERY_M } from '@/domain/communityRadius'
import type { NamedCoord } from '@/domain/types'

const center: NamedCoord = { lat: 40, lng: 116, crs: 'BD09' }
describe('一公里三类设施判定', () => {
  it('旧九点快检保持独立，区域评估细分服务边界而非铺满九格', () => {
    expect(createCommunitySamples(center)).toHaveLength(9)
    const cells = assessRadius(center, ['菜市场', '药店', '小学'].map(label => ({ label, coords: [center], complete: true })))
    expect(cells.length).toBeGreaterThan(36)
    expect(cells.some(cell => cell.status === 'unknown' && cell.boundary)).toBe(true)
    expect(cells.some(cell => cell.sizeM === 62.5)).toBe(true)
    expect(cells.every(cell => cell.ring.length === 4)).toBe(true)
    expect(cells.reduce((sum, cell) => sum + cell.sizeM! ** 2, 0)).toBe(1500 ** 2)
    for (const cell of cells.filter(cell => cell.status === 'covered')) {
      expect(cell.ring.every(corner => distanceM(center, corner) <= 1000)).toBe(true)
    }
  })
  it('检索错误或分页截断不能冒充缺少设施', () => {
    const cells = assessRadius(center, [{ label: '药店', coords: [], complete: false }])
    expect(cells.every(cell => cell.status === 'unknown' && cell.missing.length === 0)).toBe(true)
  })
  it('完整检索后缺少任意一类标为盲区，保留其他未知类', () => {
    const cells = assessRadius(center, [{ label: '小学', coords: [], complete: true }, { label: '药店', coords: [], complete: false }])
    expect(cells.every(cell => cell.status === 'blind' && cell.missing[0] === '小学' && cell.unknown[0] === '药店')).toBe(true)
    expect(cells).toHaveLength(36)
  })
  it('一公里外的设施不计入供给', () => {
    const far = { ...center, lat: center.lat + 0.03 }
    expect(distanceM(center, far)).toBeGreaterThan(3000)
    expect(assessRadius(center, [{ label: '菜市场', coords: [far], complete: true }]).every(cell => cell.status === 'blind')).toBe(true)
  })
  it('任何已判定格的角点和内部点均满足其整格判定，未检索全不能证明缺失', () => {
    const facility = { ...center, lng: center.lng + 0.007 }
    const cells = assessRadius(center, [{ label: '药店', coords: [facility], complete: true }])
    expect(cells.some(cell => cell.status === 'covered')).toBe(true)
    expect(cells.some(cell => cell.status === 'blind')).toBe(true)
    for (const cell of cells) {
      for (const x of [0, 0.25, 0.5, 0.75, 1]) {
        for (const y of [0, 0.25, 0.5, 0.75, 1]) {
          const p = { ...center, lng: cell.ring[0].lng + (cell.ring[1].lng - cell.ring[0].lng) * x,
            lat: cell.ring[0].lat + (cell.ring[2].lat - cell.ring[0].lat) * y }
          if (cell.status === 'covered') expect(distanceM(p, facility)).toBeLessThanOrEqual(1000)
          if (cell.status === 'blind') expect(distanceM(p, facility)).toBeGreaterThan(1000)
        }
      }
    }
    expect(assessRadius(center, [{ label: '药店', coords: [facility], complete: false }]).some(cell => cell.status === 'blind')).toBe(false)
  })
  it('检索缓冲包含区域外仍能服务边缘的设施，不能遗漏后误判缺失', () => {
    const facility = { ...center, lng: center.lng + 1700 / (111320 * Math.cos(center.lat * Math.PI / 180)), lat: center.lat + 750 / 111320 }
    expect(distanceM(center, facility)).toBeGreaterThan(1800)
    expect(distanceM(center, facility)).toBeLessThan(RADIUS_QUERY_M)
    const cells = assessRadius(center, [{ label: '药店', coords: [facility], complete: true }])
    expect(cells.every(cell => cell.ring.every(corner => distanceM(center, corner) + 1000 < RADIUS_QUERY_M))).toBe(true)
    const servedEdges = cells.filter(cell => cell.ring.some(corner => distanceM(corner, facility) <= 1000))
    expect(servedEdges.length).toBeGreaterThan(0)
    expect(servedEdges.every(cell => cell.status !== 'blind')).toBe(true)
  })
})
