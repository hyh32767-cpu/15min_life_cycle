import type { PlanResult, ProviderHealth } from '@/domain/types'
import { ApiError, apiErrorMessages } from './errors'
import type {
  CorridorEvidenceResult,
  CorridorResult,
  IsochroneResult,
  NamedCoord,
} from '@/domain/types'
import type {
  AppProvider,
  CorridorEvidenceRequest,
  CorridorRequest,
  CoverageResult,
  CoverageTimeInput,
  CreatePlanRequest,
  CreateReplanRequest,
  ExploreCheckResult,
  ExploreLegInput,
  IsochronePoisRequest,
  IsochronePoisResult,
  IsochroneRequest,
  RouteBandRequest,
  RouteBandResult,
  CaseSummary,
  MapsConfig,
  LocationSearchResult,
  LocationResolveResult,
  ReplanResult,
  TravelMatrixResult,
  WalkingRouteResult,
} from './contracts'

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    const timeout = AbortSignal.timeout(45_000)
    response = await fetch(url, { ...init, signal: init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'TimeoutError') throw new ApiError('查询超时，请稍后重试', 'CLIENT_TIMEOUT', 0, true)
    if (error instanceof DOMException && error.name === 'AbortError') throw new ApiError('查询已取消', 'CANCELLED')
    throw new ApiError('网络连接失败，请检查网络后重试', 'NETWORK_ERROR', 0, true)
  }
  let text: string
  try { text = await response.text() }
  catch { throw new ApiError('连接中断，请稍后重试', 'NETWORK_OR_TIMEOUT', response.status, true) }
  let body: unknown
  try {
    body = text ? (JSON.parse(text) as unknown) : {}
  } catch {
    throw new ApiError('服务暂时无法响应，请稍后重试', 'INVALID_RESPONSE', response.status, true)
  }
  if (!response.ok) {
    const error = (body as { error?: { message?: string; code?: string; retryable?: boolean; retryAfterSeconds?: number } })?.error
    const message = error?.message ?? ''
    if (error?.code && apiErrorMessages[error.code]) {
      throw new ApiError(apiErrorMessages[error.code], error.code, response.status, error.retryable === true,
        error.retryAfterSeconds ?? null)
    }
    if (error?.code === 'CONFIG_ERROR') throw new Error('地图服务尚未配置，请联系维护者')
    if (/quota|配额|302/i.test(message)) throw new Error('地图查询额度暂时用尽，请稍后重试')
    if (/Parameter Invalid/i.test(message)) throw new Error('地点查询失败，请填写完整地址或改用地图选点')
    if (Array.from(message).every((char) => char.charCodeAt(0) < 128)) throw new Error('查询未完成，请稍后重试')
    throw new Error(message || '查询未完成，请稍后重试')
  }
  return body as T
}

export class LiveApiProvider implements AppProvider {
  async parseRouteIntent(text: string, signal?: AbortSignal): Promise<{tasks: {categoryId: string; serviceMinutes: number | null}[]; totalMinutes: number | null; extraMinutes: number | null; keepOrder: boolean}> {
    return requestJson('/api/route/intent', {method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify({text}),signal})
  }
  async getCommunityInsight(services: {id: string; covered: number; total: number; facilities: number}[], signal?: AbortSignal): Promise<{summary: string; scope: string; score: number; cacheHit: boolean}> {
    return requestJson('/api/community/insight', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({services}), signal })
  }
  async exportReport(reportId: string, format: 'json' | 'csv' | 'md'): Promise<{ content: string }> {
    return requestJson('/api/reports/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reportId, format }) })
  }
  readonly mode = 'live' as const

  private planTravelTimesWire(times: CreatePlanRequest['travelTimes']): Array<Record<string, unknown>> {
    return times.map((time) => ({
      from: time.fromId,
      to: time.toId,
      durationSeconds: time.durationSeconds,
      distanceM: time.distanceM,
      status: time.status,
      sourceKind: time.sourceKind,
    }))
  }

  async getHealth(): Promise<ProviderHealth> {
    return requestJson<ProviderHealth>('/api/health')
  }

  async searchLocations(query: string, city?: string): Promise<LocationSearchResult> {
    const params = new URLSearchParams({ q: query })
    if (city) {
      params.set('city', city)
    }
    return requestJson<LocationSearchResult>(`/api/locations/search?${params.toString()}`)
  }

  async resolveLocation(coord: NamedCoord): Promise<LocationResolveResult> {
    return requestJson('/api/locations/resolve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ coord }) })
  }

  async getLocationDetail(uid: string): Promise<LocationResolveResult> {
    return requestJson(`/api/locations/poi/${encodeURIComponent(uid)}`)
  }

  async getWalkingRoute(origin: NamedCoord, destination: NamedCoord): Promise<WalkingRouteResult> {
    return requestJson<WalkingRouteResult>('/api/routes/walking', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ origin, destination }),
    })
  }

  async getTravelMatrix(origins: NamedCoord[], destinations: NamedCoord[]): Promise<TravelMatrixResult> {
    return requestJson<TravelMatrixResult>('/api/travel-matrix', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ origins, destinations }),
    })
  }

  async getCorridorPois(request: CorridorRequest): Promise<CorridorResult> {
    return requestJson<CorridorResult>('/api/pois/corridor', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  }

  async getRouteBand(request: RouteBandRequest): Promise<RouteBandResult> {
    return requestJson('/api/route-bands', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request) })
  }

  async createIsochrone(request: IsochroneRequest): Promise<IsochroneResult> {
    return requestJson<IsochroneResult>('/api/isochrones', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  }

  async getIsochroneTaskStatus(taskId: string): Promise<IsochroneResult> {
    return requestJson<IsochroneResult>(`/api/isochrones/${encodeURIComponent(taskId)}/status`)
  }

  async getIsochronePois(request: IsochronePoisRequest): Promise<IsochronePoisResult> {
    return requestJson<IsochronePoisResult>('/api/isochrones/pois', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  }
  async getCorridorEvidence(request: CorridorEvidenceRequest): Promise<CorridorEvidenceResult> {
    return requestJson<CorridorEvidenceResult>('/api/pois/corridor/evidence', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  }

  async createPlan(request: CreatePlanRequest): Promise<PlanResult> {
    return requestJson<PlanResult>('/api/plans', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...request, travelTimes: this.planTravelTimesWire(request.travelTimes) }),
    })
  }

  async createReplan(request: CreateReplanRequest): Promise<ReplanResult> {
    return requestJson<ReplanResult>('/api/replan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...request, travelTimes: this.planTravelTimesWire(request.travelTimes) }),
    })
  }

  async checkExplore(request: {
    budgetSeconds: number
    serviceSeconds: number
    waitSeconds: number
    candidates: { placeId: string; placeName?: string }[]
    legs: ExploreLegInput[]
  }): Promise<ExploreCheckResult[]> {
    const body = await requestJson<{ results: ExploreCheckResult[] }>('/api/explore/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
    return body.results
  }

  async checkCoverage(request: {
    thresholdSeconds: number
    gridIds: string[]
    facilityIds: string[]
    times: CoverageTimeInput[]
    newFacilityId?: string
    newFacilityTimes?: CoverageTimeInput[]
  }): Promise<CoverageResult> {
    return requestJson<CoverageResult>('/api/community/coverage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    })
  }

  async listCases(): Promise<CaseSummary[]> {
    const body = await requestJson<{ cases: CaseSummary[] }>('/api/cases')
    return body.cases
  }

  async getCase(id: string): Promise<unknown> {
    return requestJson<unknown>(`/api/cases/${encodeURIComponent(id)}`)
  }

  async getMapsConfig(): Promise<MapsConfig> {
    return requestJson<MapsConfig>('/api/maps/config')
  }
}
