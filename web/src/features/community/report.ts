import { lifeServices, serviceGroups, serviceQueries, SERVICE_MATCH_VERSION, SERVICE_MATCH_NOTE, type LifeService } from '@/domain/lifeServices'
import type { IsochroneResult, NamedCoord, PlaceRef } from '@/domain/types'
import type { CoverageResult, CoverageTimeInput } from '@/providers/contracts'

export interface ServiceAssessment extends LifeService {
  status: 'idle' | 'loading' | 'ready' | 'error'
  facilityCount: number | null
  coveredCount: number | null
  totalGrids: number | null
  blindCount: number | null
  error?: string
  retrievalLimited?: boolean
  reused?: boolean
}
export interface ServiceEvidence {
  result: CoverageResult
  times: CoverageTimeInput[]
  facilities: PlaceRef[]
  candidates: PlaceRef[]
}
export interface ServiceRecommendation {
  k: number
  names: string[]
  coveredCount: number
  gain: number
  status: 'ready' | 'unavailable'
  error?: string
}
export interface FacilitySimulation {
  serviceId: string
  name: string
  coord: NamedCoord
  result: CoverageResult
  times: CoverageTimeInput[]
}

export function averageServiceCoverage(profiles: ServiceAssessment[]): number | null {
  if (!profiles.length || profiles.some(item => item.status !== 'ready' || !item.totalGrids || item.coveredCount == null)) return null
  return Math.round(profiles.reduce((sum, item) => sum + item.coveredCount! / item.totalGrids!, 0) / profiles.length * 100)
}

export function buildLifeCircleReport(input: {
  origin: NamedCoord | null
  originLabel: string
  thresholdSeconds: number
  circle: IsochroneResult | null
  heatLayers: IsochroneResult[]
  samples: { id: string; coord: NamedCoord }[]
  profiles: ServiceAssessment[]
  evidence: Record<string, ServiceEvidence>
  activeServiceId: string
  recommendations: ServiceRecommendation[]
  recommendationsLoading: boolean
  simulation: FacilitySimulation | null
}) {
  const average = averageServiceCoverage(input.profiles)
  const selectedIds = input.profiles.map(item => item.id)
  return {
    schemaVersion: 'life-circle-report-v2',
    serviceMatching: { version: SERVICE_MATCH_VERSION, note: SERVICE_MATCH_NOTE },
    generatedAt: new Date().toISOString(),
    status: input.circle?.status !== 'complete' ? 'partial-circle'
      : input.profiles.every(item => item.status === 'idle') ? 'not-checked'
        : average == null ? 'partial' : 'complete',
    scope: {
      origin: input.origin, originLabel: input.originLabel, thresholdSeconds: input.thresholdSeconds,
      boundary: input.circle?.frontier ? 'grid-frontier-approximation' : 'measured-ray-approximation', samples: input.samples,
      maximumSamples: 25, maximumFacilitiesPerService: 5,
      coverageMeaning: 'sampled-points-only', officialComplianceAssessment: false,
    },
    policyReferences: [
      'https://www.mofcom.gov.cn/zwgk/gztz/art/2021/art_04807f8fe711403485c7d962a83a1172.html',
      'https://www.mofcom.gov.cn/gztz/art/2025/art_989b4d7d0d5842db8177a7ea4d29236a.html',
    ],
    assessment: { title: '设施社区评分', score: average, maximumScore: 100,
      meaning: '所选服务采样点平均覆盖率；未覆盖位置与补点建议属于同一评价', officialRating: false },
    summary: { selectedServiceIds: selectedIds, completedServices: input.profiles.filter(item => item.status === 'ready').length,
      averageCoveragePercent: average, aggregation: 'arithmetic-mean-of-selected-service-sample-coverage' },
    serviceCatalog: lifeServices.map(service => ({ ...service, groupLabel: serviceGroups.find(group => group.id === service.group)?.label,
      selection: selectedIds.includes(service.id) ? 'selected' : 'not-selected' })),
    services: input.profiles.map(profile => {
      const evidence = input.evidence[profile.id]
      return {
        id: profile.id, label: profile.label, group: profile.group, terms: profile.terms,
        queries: serviceQueries(profile), status: profile.status, error: profile.error ?? null,
        retrievalLimited: profile.retrievalLimited ?? false,
        reused: profile.reused ?? false,
        coveragePercent: profile.status === 'ready' && profile.totalGrids && profile.coveredCount != null
          ? Math.round(profile.coveredCount / profile.totalGrids * 100) : null,
        baseline: evidence?.result ?? null, facilities: evidence?.facilities ?? [],
        candidates: evidence?.candidates ?? [], measuredTimes: evidence?.times ?? [],
      }
    }),
    charts: {
      bars: input.profiles.map(item => ({ serviceId: item.id, label: item.label, status: item.status,
        coveredPoints: item.coveredCount, totalPoints: item.totalGrids })),
      radarServiceIds: input.profiles.length >= 3 && input.profiles.length <= 8 ? selectedIds : [],
      timeHeatLayers: input.heatLayers,
    },
    map: { serviceId: input.activeServiceId || null,
      classificationBoundary: input.circle?.frontier ? 'isochrone.frontier.polygons' : 'isochrone.radiiM',
      previewUsedForAnalysis: false,
      boundaryStroke: input.circle?.reconstruction?.contours.length ? 'isochrone.reconstruction.contours' : 'isochrone.radiiM',
      visibleMarkers: 'selected-service-facilities',
      facilities: input.evidence[input.activeServiceId]?.facilities ?? [],
      baselineCoverage: input.evidence[input.activeServiceId]?.result.coverage ?? null,
      displayedCoverage: input.simulation?.serviceId === input.activeServiceId
        ? input.simulation.result.coverage : input.evidence[input.activeServiceId]?.result.coverage ?? null },
    improvementSuggestions: { serviceId: input.activeServiceId || null,
      status: input.recommendationsLoading ? 'loading' : input.recommendations.length ? 'evaluated' : 'not-evaluated',
      candidateScope: 'retrieved-same-service-candidates-only', items: input.recommendations },
    simulation: input.simulation ? { ...input.simulation, sourceKind: 'synthetic-assumption', changesBaseline: false } : null,
    isochrone: input.circle,
    limitations: ['未选择服务未检查，不表示缺失。', '类型不明、缺测或失败保持未知，不填零。',
      '仅反映有限设施及采样点，不能证明整个区域或人口覆盖。', '改善建议只针对当前服务的有限候选，模拟新增不计入真实基线或平均覆盖率。'],
  }
}
