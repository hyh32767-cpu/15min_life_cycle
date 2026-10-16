import type {
  CorridorEvidenceResult,
  CorridorResult,
  DataMode,
  IsochroneResult,
  NamedCoord,
  PlaceRef,
  PlanResult,
  PlanTaskInput,
  PlanTravelTime,
  ProviderHealth,
  RouteSummary,
  TravelMatrixCell,
} from '@/domain/types'

export interface LocationSearchResult {
  traceId: string
  mode: DataMode
  candidates: PlaceRef[]
  warnings: string[]
}

export interface LocationResolveResult {
  traceId: string
  place: PlaceRef
}

export interface WalkingRouteResult {
  traceId: string
  mode: DataMode
  sourceKind: string
  cacheHit: boolean
  route: RouteSummary
  warnings: string[]
}

export interface TravelMatrixResult {
  traceId: string
  mode: DataMode
  sourceKind: string
  cacheHit: boolean
  expiresAt?: string | null
  cells: TravelMatrixCell[]
  warnings: string[]
}

export interface CorridorRequest {
  routeGeometry: NamedCoord[]
  queryTerms: string[]
  category?: string
  corridorBufferM?: number
  windowRadiusM?: number
  windowSpacingM?: number
  maxPagesPerWindow?: number
  maxUnique?: number
  detailLimit?: number
}

export interface IsochroneRequest {
  placeId?: string
  origin: NamedCoord
  thresholdSeconds: number
  bearings?: number[]
  loM?: number
  hiM?: number
  initialM?: number
  tolM?: number
  maxPairs?: number
  l2First?: boolean
  adaptive?: boolean
  frontier?: boolean
  allowL2Fallback?: boolean
}

export interface RouteBandRequest {
  routeGeometry: NamedCoord[]
  thresholdSeconds: number
  cacheOnly: boolean
  centerIndex?: number
  maxCenters?: number
  maxPairs?: number
  taskIds?: Record<number, string>
}

export interface RouteBandResult {
  routeHash: string
  thresholdSeconds: number
  status: 'complete' | 'partial' | 'unknown'
  completeCount: number
  nodes: { index: number; origin: NamedCoord; status: string; cached: boolean; warnings: string[]; taskId?: string | null; backgroundStatus?: string; previewContours?: NamedCoord[][] }[]
  fills: NamedCoord[][]
  boundaries: NamedCoord[][]
  displayContours?: NamedCoord[][]
  maxGapM: number
  cacheHit: boolean
  cost: { liveRequests: number; cacheHits: number; pairs: number; livePairs: number }
}

export interface CorridorEvidenceRequest {
  placeId?: string
  poi: NamedCoord
  routeGeometry: NamedCoord[]
  baselineDurationSeconds: number
  thresholdSeconds: number
  sampleM?: number
  maxSamples?: number
}

export interface CreatePlanRequest {
  startId: string
  endId: string
  departureSeconds: number
  deadlineSeconds: number
  tasks: PlanTaskInput[]
  travelTimes: PlanTravelTime[]
  preference: 'fastest' | 'least_walk'
  maxAlternatives?: number
}

export interface ReplanEventInput {
  id: string
  type: string
  targetId: string
  delaySeconds?: number
}

export interface CreateReplanRequest {
  endId: string
  deadlineSeconds: number
  tasks: PlanTaskInput[]
  travelTimes: PlanTravelTime[]
  preference: 'fastest' | 'least_walk'
  completedTaskIds: string[]
  currentNodeId: string
  currentTimeSeconds: number
  events: ReplanEventInput[]
}

export interface ReplanResult {
  status: string
  plan: PlanResult
  lockedCompleted: string[]
  appliedEvents: string[]
  reason: string
}

export interface ExploreLegInput {
  candidateId: string
  durationSecondsStart: number | null
  durationSecondsReturn: number | null
  statusStart: string
  statusReturn: string
  sourceKind: string
}

export interface ExploreCheckResult {
  placeId: string
  feasible: boolean
  totalSeconds: number | null
  reason: string
}

export interface CoverageTimeInput {
  fromGrid: string
  toFacility: string
  durationSeconds: number | null
  status: string
}

export interface CoverageResult {
  coverage: Record<string, boolean>
  coveredCount: number
  totalGrids: number
  blindGrids: string[]
  delta?: { before: number; after: number }
}

export interface CaseSummary {
  id: string
  title: string
  region: string
  summary: string
}

export interface MapsConfig {
  configured: boolean
  ak: string
  version: string
  note?: string
}

export interface IsochronePoisRequest {
  origin: NamedCoord
  thresholdSeconds: number
  queryTerms: string[]
  radiiM?: Record<string, number>
  searchRadiusM?: number
  maxPagesPerTerm?: number
  maxUnique?: number
}

export interface IsochronePoiRow {
  uid?: string | null
  name?: string
  walkSeconds?: number | null
  reason?: string
  [key: string]: unknown
}

export interface IsochronePoisResult {
  traceId: string
  mode: DataMode
  sourceKind: string
  reachable: IsochronePoiRow[]
  unreachable: IsochronePoiRow[]
  pairsUsed: number
  retrieval: Record<string, unknown>
  warnings: string[]
}

export interface AppProvider {
  parseRouteIntent?(text: string, signal?: AbortSignal): Promise<{tasks: {categoryId: string; serviceMinutes: number | null}[]; totalMinutes: number | null; extraMinutes: number | null; keepOrder: boolean}>
  getCommunityInsight?(services: {id: string; covered: number; total: number; facilities: number}[], signal?: AbortSignal): Promise<{summary: string; scope: string; score: number; cacheHit: boolean}>
  readonly mode: DataMode
  getHealth(): Promise<ProviderHealth>
  searchLocations(query: string, city?: string): Promise<LocationSearchResult>
  resolveLocation?(coord: NamedCoord): Promise<LocationResolveResult>
  getLocationDetail?(uid: string): Promise<LocationResolveResult>
  getWalkingRoute(origin: NamedCoord, destination: NamedCoord): Promise<WalkingRouteResult>
  getTravelMatrix(origins: NamedCoord[], destinations: NamedCoord[]): Promise<TravelMatrixResult>
  getCorridorPois(request: CorridorRequest): Promise<CorridorResult>
  createIsochrone(request: IsochroneRequest): Promise<IsochroneResult>
  getIsochroneTaskStatus?(taskId: string): Promise<IsochroneResult>
  getRouteBand(request: RouteBandRequest): Promise<RouteBandResult>
  getIsochronePois(request: IsochronePoisRequest): Promise<IsochronePoisResult>
  exportReport?(reportId: string, format: 'json' | 'csv' | 'md'): Promise<{ content: string }>
  getCorridorEvidence(request: CorridorEvidenceRequest): Promise<CorridorEvidenceResult>
  createPlan(request: CreatePlanRequest): Promise<PlanResult>
  createReplan(request: CreateReplanRequest): Promise<ReplanResult>
  checkExplore(request: {
    budgetSeconds: number
    serviceSeconds: number
    waitSeconds: number
    candidates: { placeId: string; placeName?: string }[]
    legs: ExploreLegInput[]
  }): Promise<ExploreCheckResult[]>
  checkCoverage(request: {
    thresholdSeconds: number
    gridIds: string[]
    facilityIds: string[]
    times: CoverageTimeInput[]
    newFacilityId?: string
    newFacilityTimes?: CoverageTimeInput[]
  }): Promise<CoverageResult>
  listCases(): Promise<CaseSummary[]>
  getCase(id: string): Promise<unknown>
  /** T110/UI-M：浏览器端地图 AK 配置（只下发浏览器端 AK，不含 Server AK/SK）。 */
  getMapsConfig(): Promise<MapsConfig>
}
