export type DataMode = 'live'

export type Crs = 'BD09' | 'GCJ02' | 'WGS84'

export type SourceKind =
  | 'live-api'
  | 'api-cache'
  | 'synthetic-assumption'
  | 'user-input'
  | 'derived'

export interface NamedCoord {
  lng: number
  lat: number
  crs: Crs
}

export interface Provenance {
  sourceKind: SourceKind
  parents: string[]
  note?: string
}

export interface ProviderHealth {
  status: 'ok'
  mode: DataMode
  baiduConfigured: boolean
  warnings: string[]
  features: Record<string, boolean>
}

export interface AppError {
  code: string
  message: string
  details?: unknown
}

export interface PlaceRef {
  uid?: string
  name: string
  address?: string
  tags?: string[]
  coord: NamedCoord
  naviCoord?: NamedCoord
  source: SourceKind
  fetchedAt?: string
  shopHours?: string | null
  structuredHours?: Record<string, unknown>[] | null
  status?: string | null
  detailFetchedAt?: string | null
}

export interface RouteStep {
  distanceM?: number
  durationSeconds?: number
  instructions?: string
  path?: string
}

export interface RouteSummary {
  durationSeconds: number
  distanceM: number
  origin?: { lng: number; lat: number }
  destination?: { lng: number; lat: number }
  geometry: NamedCoord[]
  steps: RouteStep[]
}

export interface TravelMatrixCell {
  fromIndex: number
  toIndex: number
  durationSeconds: number | null
  distanceM: number | null
  status: 'ok' | 'no_route' | 'error'
  sourceKind: SourceKind
}

export interface CorridorRetrieval {
  queryTerms: string[]
  category: string
  windows: number
  pages: number
  rawCount: number
  uniqueCount: number
  truncated: boolean
  truncationReason: string | null
  sourceKind: SourceKind
}

export interface CorridorPoi {
  place: PlaceRef
  distanceToRouteM: number
}

export interface CorridorResult {
  cacheHit?: boolean
  expiresAt?: string | null
  traceId: string
  mode: DataMode
  sourceKind: SourceKind
  retrieval: CorridorRetrieval
  pois: CorridorPoi[]
  warnings: string[]
}

export interface IsochroneResult {
  frontier?: {
    phase: 'boundary' | 'interior-check' | 'finished'
    spacingM: number
    halfM: number
    domainShape?: 'disk' | 'square'
    radiusM?: number
    domainPoints?: number
    maxExternalPoints?: number
    batchCount: number
    currentShellM?: number | null
    pendingCount?: number
    budgetLimited?: boolean
    clipped?: boolean
    interiorEstimated?: boolean
    previewOnly: boolean
    previewContours: NamedCoord[][]
    samples: { x: number; y: number; seconds: number | null; state: 'reachable' | 'outside' | 'unknown' | 'no_route'; coord: NamedCoord }[]
    polygons: { outer: NamedCoord[]; holes: NamedCoord[][] }[]
    fills: NamedCoord[][]
  } | null
  reconstruction?: {
    method: string
    sampleCount: number
    contours: NamedCoord[][]
    clipMarginM: number
    classificationBoundary: 'ray-polygon' | 'grid-frontier-approximation'
    note: string
  } | null
  expiresAt?: string | null
  taskId: string
  status: 'complete' | 'partial' | 'degraded' | 'failed'
  placeId?: string | null
  thresholdSeconds: number
  radiiM: Record<string, number>
  failedBearings: number[]
  skippedBearings: number[]
  algorithmVersion: string
  warnings: string[]
  cacheHit: boolean
  pairsUsed: number
  traceId?: string | null
  // F56：与后端 IsochroneResponse 对齐；缺失时前端回退，不硬编码来源。
  mode?: DataMode
  sourceKind?: SourceKind
  origin?: NamedCoord | null
  report?: Record<string, unknown> | null
  backgroundStatus?: 'idle' | 'running' | 'completed' | 'degraded' | null
}

export interface CorridorEvidenceSample {
  index: number
  coord: NamedCoord
  distanceFromStartM: number
  prefixSeconds: number
  inboundSeconds: number | null
  outboundSeconds: number | null
  inboundReachable: boolean
  outboundReachable: boolean
}

export interface CorridorEvidenceResult {
  traceId: string
  mode: DataMode
  sourceKind: SourceKind
  thresholdSeconds: number
  pairsUsed: number
  samples: CorridorEvidenceSample[]
  evidence: {
    thresholdSeconds: number
    inboundReachableIndices: number[]
    outboundReachableIndices: number[]
    missingInboundIndices: number[]
    missingOutboundIndices: number[]
    symmetricAssumed: boolean
    directionalFeasible: boolean
  }
  bestAccess?: {
    entryIndex: number
    returnIndex: number
    totalTravelSeconds: number
    extraTravelSeconds: number
    finishSeconds: number
  } | null
  warnings: string[]
}
export interface PlanOptionInput {
  placeId: string
  serviceSeconds: number
  serviceSourceKind: SourceKind
  windowSourceKind?: string
  window?: { opensSeconds: number; closesSeconds: number }
  windows?: { opensSeconds: number; closesSeconds: number }[]
}

export interface PlanTaskInput {
  id: string
  options: PlanOptionInput[]
  required: boolean
  precedenceIds: string[]
}

export interface PlanOptionDraft extends PlanOptionInput {
  placeName?: string
  coord?: NamedCoord
  opensSeconds?: number
  closesSeconds?: number
}

export interface PlanTravelTime {
  fromId: string
  toId: string
  durationSeconds: number | null
  distanceM: number | null
  status: 'ok' | 'no_route' | 'error'
  sourceKind: SourceKind
}

export interface PlanStop {
  taskId: string
  placeId: string
  arrivalSeconds: number
  startSeconds: number
  finishSeconds: number
  waitSeconds: number
  travelSeconds: number
  travelSourceKind: string
  serviceSourceKind: string
  windowSourceKind: string
}

export interface PlanTimelineItem {
  kind: string
  label?: string
  startSeconds?: number
  finishSeconds?: number
  durationSeconds?: number
  sourceKind?: string
}

export interface PlanAlternative {
  stops: PlanStop[]
  timeline: PlanTimelineItem[]
  departureSeconds: number
  finishSeconds: number
  deadlineSeconds: number
  slackSeconds: number
  totalTravelSeconds: number
  totalWaitSeconds: number
  totalServiceSeconds: number
  totalWalkingM: number
  returnTravelSeconds: number
  returnTravelSourceKind: string
}

export interface PlanResult {
  status: 'ready' | 'infeasible'
  alternatives: PlanAlternative[]
  infeasibleReasons: Record<string, number>
  warnings: string[]
  suggestions: string[]
}

