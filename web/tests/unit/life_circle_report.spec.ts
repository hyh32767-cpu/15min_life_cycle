import { describe, expect, it } from 'vitest'
import { lifeServices } from '@/domain/lifeServices'
import { buildLifeCircleReport, type ServiceAssessment } from '@/features/community/report'

const coord = { lng: 116.36, lat: 40.09, crs: 'BD09' as const }
const covered = { coveredCount: 1, totalGrids: 1, blindGrids: [], coverage: { p: true } }
const uncovered = { coveredCount: 0, totalGrids: 1, blindGrids: ['p'], coverage: { p: false } }
function input() {
  const profiles: ServiceAssessment[] = ['pharmacy', 'elderly'].map(id => ({ ...lifeServices.find(service => service.id === id)!,
    status: 'ready', facilityCount: id === 'pharmacy' ? 1 : 0, coveredCount: id === 'pharmacy' ? 1 : 0,
    totalGrids: 1, blindCount: id === 'pharmacy' ? 0 : 1 }))
  return { origin: coord, originLabel: '验收地点', thresholdSeconds: 900,
    circle: { taskId: 'test', status: 'complete' as const, thresholdSeconds: 900, origin: coord,
      radiiM: { 0: 500, 90: 500, 180: 500, 270: 500 }, failedBearings: [], skippedBearings: [], pairsUsed: 0,
      algorithmVersion: 'test', warnings: [], cacheHit: false },
    heatLayers: [], samples: [{ id: 'p', coord }], profiles,
    evidence: { pharmacy: { result: covered, facilities: [{ uid: 'pharmacy', name: '药店', coord, source: 'live-api' as const }], candidates: [], times: [] },
      elderly: { result: uncovered, facilities: [], candidates: [], times: [] } },
    activeServiceId: 'elderly', recommendations: [], recommendationsLoading: false, simulation: null }
}
describe('complete life-circle report', () => {
  it('exports independent service baselines and marks unselected services without inventing zero coverage', () => {
    const report = buildLifeCircleReport(input())
    expect(report.summary.averageCoveragePercent).toBe(50)
    expect(report.services.find(service => service.id === 'elderly')?.baseline?.blindGrids).toEqual(['p'])
    expect(report.services.find(service => service.id === 'pharmacy')?.facilities[0]?.name).toBe('药店')
    expect(report.serviceCatalog.find(service => service.id === 'primary-school')?.selection).toBe('not-selected')
    expect(report.services.some(service => service.id === 'primary-school')).toBe(false)
    expect(report.charts.bars).toHaveLength(2)
    expect(report.scope.officialComplianceAssessment).toBe(false)
  })
  it('preserves unknown results and omits a complete average', () => {
    const data = input()
    data.profiles[1] = { ...data.profiles[1]!, status: 'error', coveredCount: null, totalGrids: null, blindCount: null,
      facilityCount: null, error: '类型尚未确认' }
    Reflect.deleteProperty(data.evidence, 'elderly')
    const report = buildLifeCircleReport(data)
    expect(report.status).toBe('partial')
    expect(report.summary.averageCoveragePercent).toBeNull()
    expect(report.services[1]?.baseline).toBeNull()
    expect(report.services[1]?.coveragePercent).toBeNull()
  })
  it('exports simulations separately without replacing the original category or average', () => {
    const report = buildLifeCircleReport({ ...input(), simulation: { serviceId: 'elderly', name: '模拟养老中心', coord,
      result: { ...covered, delta: { before: 0, after: 1 } }, times: [] } })
    expect(report.summary.averageCoveragePercent).toBe(50)
    expect(report.services[1]?.baseline?.coveredCount).toBe(0)
    expect(report.map.baselineCoverage).toEqual({ p: false })
    expect(report.map.displayedCoverage).toEqual({ p: true })
    expect(report.simulation?.changesBaseline).toBe(false)
    expect(report.simulation?.sourceKind).toBe('synthetic-assumption')
  })
})
