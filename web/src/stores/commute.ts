import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import { rankCandidate } from '@/domain/commute'
import { sanitizeMinutes } from '@/domain/numbers'
import { commuteCategoryQueries } from '@/domain/commuteCategories'
import { parseClockToSeconds } from '@/domain/time'
import type {
  CorridorEvidenceResult,
  CorridorPoi,
  IsochroneResult,
  NamedCoord,
  PlaceRef,
} from '@/domain/types'
import { useAppStore } from './app'

export interface RankedPoi {
  place: PlaceRef
  distanceToRouteM: number
  extraTravelSeconds: number | null
  finishSeconds: number | null
  slackSeconds: number | null
  feasible: boolean
  reasons: string[]
  waitSeconds: number
  serviceSeconds: number
}

export interface CommunityGridPoint {
  id: string
  coord: NamedCoord
  covered: boolean
}

export const useCommuteStore = defineStore('commute', () => {
  const restoring = ref(false)
  const app = useAppStore()
  const companyQuery = ref('北京市昌平区回龙观')
  const homeQuery = ref('北京市昌平区龙泽园')
  const city = ref('北京')
  const category = ref('药店')
  const departureClock = ref('18:00')
  const deadlineClock = ref('19:30')
  const extraBudgetMinutes = ref(10)
  const serviceMinutes = ref(10)
  const waitMinutes = ref(0)
  const stayMinutes = computed({
    get: () => serviceMinutes.value + waitMinutes.value,
    set: (value: number) => { serviceMinutes.value = typeof value === 'number' ? value : NaN; waitMinutes.value = 0 },
  })
  const companyCandidates = ref<PlaceRef[]>([])
  const homeCandidates = ref<PlaceRef[]>([])
  const company = ref<PlaceRef | null>(null)
  const home = ref<PlaceRef | null>(null)
  const route = ref<null | Awaited<ReturnType<typeof app.provider.getWalkingRoute>>>(null)
  const rankedPois = ref<RankedPoi[]>([])
  const selectedPoiIndex = ref<number | null>(null)
  const isochrone = ref<IsochroneResult | null>(null)
  const isochroneThreshold = ref(900)
  const isochroneLoading = ref(false)
  const evidence = ref<CorridorEvidenceResult | null>(null)
  const evidenceLoading = ref(false)
  const corridorPois = ref<CorridorPoi[]>([])
  const inboundDurations = ref<Record<number, number | null>>({})
  const outboundDurations = ref<Record<number, number | null>>({})
  const detourGeometries = ref<NamedCoord[][]>([])
  const compareIndices = ref<number[]>([])
  const compareIsochrones = ref<Record<number, IsochroneResult>>({})
  const compareLoading = ref<Record<number, boolean>>({})
  const communityGridPoints = ref<CommunityGridPoint[]>([])
  const compareTokens = new Map<number, number>()
  let planSeq = 0
  let isoSeq = 0
  let evidenceSeq = 0
  let compareEpoch = 0
  let planTimer: ReturnType<typeof setTimeout> | undefined
  let rankTimer: ReturnType<typeof setTimeout> | undefined
  const retrievalWarnings = ref<string[]>([])
  const loading = ref(false)
  const error = ref('')
  const stage = ref('idle')
  // 地图图标点击 → 页面打开单店详情（消费后置空）。
  const poiFocusIndex = ref<number | null>(null)
  function focusPoiFromMap(index: number): void {
    poiFocusIndex.value = index
  }

  const provider = computed(() => app.provider)

  async function searchCompany(applyFirst = true): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const result = await provider.value.searchLocations(companyQuery.value, city.value || undefined)
      companyCandidates.value = result.candidates
      // 高德式语义：默认自动应用首候选（供启动引导）；点选面板传 false，只列候选不换当前值。
      if (applyFirst) company.value = result.candidates[0] ?? null
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  async function searchHome(applyFirst = true): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const result = await provider.value.searchLocations(homeQuery.value, city.value || undefined)
      homeCandidates.value = result.candidates
      if (applyFirst) home.value = result.candidates[0] ?? null
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  function selectCompany(index: number): void {
    company.value = companyCandidates.value[index] ?? null
  }

  function selectHome(index: number): void {
    home.value = homeCandidates.value[index] ?? null
  }

  function effectiveCoord(place: { coord: NamedCoord; naviCoord?: NamedCoord }): NamedCoord {
    return place.naviCoord ?? place.coord
  }

  function buildRanking(departureSeconds: number, deadlineSeconds: number): RankedPoi[] {
    const currentRoute = route.value
    if (!currentRoute) return []
    return corridorPois.value.map((item, index) => {
      const rank = rankCandidate({
        startToPoiSeconds: inboundDurations.value[index] ?? null,
        poiToEndSeconds: outboundDurations.value[index] ?? null,
        baselineSeconds: currentRoute.route.durationSeconds,
        waitSeconds: waitMinutes.value * 60,
        serviceSeconds: serviceMinutes.value * 60,
        departureSeconds,
        deadlineSeconds,
        maxExtraTravelSeconds: extraBudgetMinutes.value * 60,
        place: item.place,
      })
      return {
        place: item.place,
        distanceToRouteM: item.distanceToRouteM,
        extraTravelSeconds: rank.extraTravelSeconds,
        finishSeconds: rank.finishSeconds,
        slackSeconds: rank.slackSeconds,
        feasible: rank.feasible,
        reasons: rank.reasons,
        waitSeconds: waitMinutes.value * 60,
        serviceSeconds: serviceMinutes.value * 60,
      }
    }).sort((a, b) => {
      if (a.feasible !== b.feasible) return a.feasible ? -1 : 1
      return (a.extraTravelSeconds ?? Infinity) - (b.extraTravelSeconds ?? Infinity)
    })
  }

  function recomputeRanking(): void {
    // F38：watcher 直达 buildRanking，绕过 planCommute 的校验；非法输入直接报错不重算。
    const budget = sanitizeMinutes(extraBudgetMinutes.value, 'extra', { min: 0, max: 120, label: '额外路程预算' })
    if (!budget.ok) { error.value = budget.error.message; return }
    const service = sanitizeMinutes(serviceMinutes.value, 'service', { min: 0, max: 480, label: '停留时间' })
    if (!service.ok) { error.value = service.error.message; return }
    const wait = sanitizeMinutes(waitMinutes.value, 'wait', { min: 0, max: 480, label: '排队时间' })
    if (!wait.ok) { error.value = wait.error.message; return }
    const departureSeconds = parseClockToSeconds(departureClock.value)
    const deadlineSeconds = parseClockToSeconds(deadlineClock.value)
    if (departureSeconds == null || deadlineSeconds == null || deadlineSeconds <= departureSeconds) {
      return
    }
    const selectedPlace = selectedPoiIndex.value == null ? null : rankedPois.value[selectedPoiIndex.value]?.place
    rankedPois.value = buildRanking(departureSeconds, deadlineSeconds)
    if (selectedPlace) {
      const index = rankedPois.value.findIndex(item => placeIdentity(item.place) === placeIdentity(selectedPlace))
      selectedPoiIndex.value = index >= 0 ? index : null
    }
    compareEpoch++
    compareTokens.clear()
    compareIndices.value = []
    compareIsochrones.value = {}
    compareLoading.value = {}
  }

  function placeIdentity(place: PlaceRef): string {
    const coord = effectiveCoord(place)
    return `${place.uid || place.name}:${coord.crs}:${coord.lng}:${coord.lat}`
  }

  function invalidateCandidates(clearRoute = false): void {
    planSeq++
    isoSeq++
    evidenceSeq++
    compareEpoch++
    compareTokens.clear()
    clearTimeout(planTimer)
    clearTimeout(rankTimer)
    rankedPois.value = []
    corridorPois.value = []
    inboundDurations.value = {}
    outboundDurations.value = {}
    selectedPoiIndex.value = null
    poiFocusIndex.value = null
    isochrone.value = null
    isochroneLoading.value = false
    evidence.value = null
    evidenceLoading.value = false
    detourGeometries.value = []
    compareIndices.value = []
    compareIsochrones.value = {}
    compareLoading.value = {}
    retrievalWarnings.value = []
    loading.value = false
    error.value = ''
    stage.value = 'idle'
    if (clearRoute) route.value = null
  }

  async function planCommute(): Promise<void> {
    if (!company.value || !home.value) {
      error.value = '请先搜索并确认起点与终点'
      return
    }
    const budget = sanitizeMinutes(extraBudgetMinutes.value, 'extra', { min: 0, max: 120, label: '额外路程预算' })
    if (!budget.ok) { error.value = budget.error.message; return }
    const service = sanitizeMinutes(serviceMinutes.value, 'service', { min: 0, max: 480, label: '停留时间' })
    if (!service.ok) { error.value = service.error.message; return }
    const wait = sanitizeMinutes(waitMinutes.value, 'wait', { min: 0, max: 480, label: '排队时间' })
    if (!wait.ok) { error.value = wait.error.message; return }
    const departureSeconds = parseClockToSeconds(departureClock.value)
    const deadlineSeconds = parseClockToSeconds(deadlineClock.value)
    if (departureSeconds == null || deadlineSeconds == null || deadlineSeconds <= departureSeconds) {
      error.value = '截止时间必须晚于出发时间'
      return
    }
    const seq = ++planSeq
    ++isoSeq
    // F71：重算同时失效证据与对比子请求，旧证据/旧圈不回写新路线。
    ++evidenceSeq
    compareEpoch++
    compareTokens.clear()
    clearTimeout(planTimer)
    clearTimeout(rankTimer)
    loading.value = true
    error.value = ''
    retrievalWarnings.value = []
    rankedPois.value = []
    route.value = null
    // F48：重算开始即清空旧选中 POI/等时圈/对比，新结果要求用户重新选择，不复用旧 index。
    selectedPoiIndex.value = null
    isochrone.value = null
    compareIsochrones.value = {}
    compareLoading.value = {}
    evidence.value = null
    corridorPois.value = []
    inboundDurations.value = {}
    outboundDurations.value = {}
    detourGeometries.value = []
    compareIndices.value = []
    try {
      const companyEntry = effectiveCoord(company.value)
      const homeEntry = effectiveCoord(home.value)
      const baseline = await provider.value.getWalkingRoute(companyEntry, homeEntry)
      if (seq !== planSeq) return
      route.value = baseline
      if (!baseline.route.geometry.length) {
        throw new Error('路线信息不完整，请重新规划')
      }
      stage.value = 'corridor'
      const selectedCategory = category.value
      const corridor = await provider.value.getCorridorPois({
        routeGeometry: baseline.route.geometry,
        queryTerms: commuteCategoryQueries(selectedCategory),
        category: selectedCategory,
        corridorBufferM: 1200,
        windowRadiusM: 800,
        maxPagesPerWindow: 3,
        maxUnique: 60,
        detailLimit: 10,
      })
      if (seq !== planSeq) return
      retrievalWarnings.value = [...retrievalWarnings.value, ...corridor.warnings]
      const pois = corridor.pois
      if (!pois.length) {
        rankedPois.value = []
        return
      }
      stage.value = 'matrix'
      const coords = pois.map((item) => effectiveCoord(item.place))
      const companyCoord = effectiveCoord(company.value)
      const homeCoord = effectiveCoord(home.value)
      const [inbound, outbound] = await Promise.all([
        provider.value.getTravelMatrix([companyCoord], coords),
        provider.value.getTravelMatrix(coords, [homeCoord]),
      ])
      if (seq !== planSeq) return
      const inDurations: Record<number, number | null> = {}
      for (const cell of inbound.cells) {
        if (cell.fromIndex === 0) inDurations[cell.toIndex] = cell.durationSeconds
      }
      const outDurations: Record<number, number | null> = {}
      for (const cell of outbound.cells) {
        if (cell.toIndex === 0) outDurations[cell.fromIndex] = cell.durationSeconds
      }
      corridorPois.value = pois
      inboundDurations.value = inDurations
      outboundDurations.value = outDurations
      rankedPois.value = buildRanking(departureSeconds, deadlineSeconds)
      stage.value = 'ready'
    } catch (err) {
      if (seq === planSeq) {
        error.value = err instanceof Error ? err.message : String(err)
        stage.value = 'error'
      }
    } finally {
      if (seq === planSeq) loading.value = false
    }
  }

  async function loadIsochrone(thresholdSeconds: number): Promise<void> {
    const index = selectedPoiIndex.value
    if (index == null) return
    const poi = rankedPois.value[index]
    if (!poi) return
    const seq = ++isoSeq
    isochroneLoading.value = true
    error.value = ''
    try {
      isochroneThreshold.value = thresholdSeconds
      if (compareIndices.value.length) {
        void reloadCompare(thresholdSeconds)
      }
      const result = await provider.value.createIsochrone({
        placeId: poi.place.uid,
        origin: effectiveCoord(poi.place),
        thresholdSeconds,
        maxPairs: 64,
      })
      if (seq === isoSeq) isochrone.value = result
    } catch (err) {
      if (seq === isoSeq) {
        isochrone.value = null
        error.value = err instanceof Error ? err.message : String(err)
      }
    } finally {
      if (seq === isoSeq) isochroneLoading.value = false
    }
  }

  async function loadEvidence(): Promise<void> {
    const index = selectedPoiIndex.value
    const currentRoute = route.value
    if (index == null || !currentRoute) return
    const poi = rankedPois.value[index]
    if (!poi) return
    const seq = ++evidenceSeq
    evidenceLoading.value = true
    error.value = ''
    try {
      const result = await provider.value.getCorridorEvidence({
        placeId: poi.place.uid,
        poi: effectiveCoord(poi.place),
        routeGeometry: currentRoute.route.geometry,
        baselineDurationSeconds: currentRoute.route.durationSeconds,
        thresholdSeconds: isochroneThreshold.value,
        sampleM: 200,
        maxSamples: 12,
      })
      if (seq !== evidenceSeq) return
      evidence.value = result
      detourGeometries.value = []
      if (result.bestAccess) {
        const entry = result.samples[result.bestAccess.entryIndex]
        const exit = result.samples[result.bestAccess.returnIndex]
        if (entry && exit) {
          try {
            const poiCoord = effectiveCoord(poi.place)
            const [inboundLeg, outboundLeg] = await Promise.all([
              provider.value.getWalkingRoute(entry.coord, poiCoord),
              provider.value.getWalkingRoute(poiCoord, exit.coord),
            ])
            if (seq === evidenceSeq) {
              detourGeometries.value = [
                inboundLeg.route.geometry,
                outboundLeg.route.geometry,
              ]
            }
          } catch (err) {
            if (seq === evidenceSeq) {
              retrievalWarnings.value = [
                ...retrievalWarnings.value,
                `绕行路线几何失败: ${err instanceof Error ? err.message : String(err)}`,
              ]
            }
          }
        }
      }
    } catch (err) {
      if (seq === evidenceSeq) {
        evidence.value = null
        error.value = err instanceof Error ? err.message : String(err)
      }
    } finally {
      if (seq === evidenceSeq) evidenceLoading.value = false
    }
  }

  async function selectPoi(index: number | null, withIsochrone = true, withEvidence = true): Promise<void> {
    isoSeq += 1
    evidenceSeq += 1
    selectedPoiIndex.value = index
    evidence.value = null
    isochrone.value = null
    isochroneLoading.value = false
    evidenceLoading.value = false
    detourGeometries.value = []
    if (index == null) return
    await Promise.all([withIsochrone ? loadIsochrone(isochroneThreshold.value) : Promise.resolve(), withEvidence ? loadEvidence() : Promise.resolve()])
  }

  async function loadCompareIsochrone(index: number, thresholdSeconds: number): Promise<void> {
    const poi = rankedPois.value[index]
    if (!poi) return
    const token = (compareTokens.get(index) ?? 0) + 1
    const epoch = compareEpoch
    compareTokens.set(index, token)
    compareLoading.value = { ...compareLoading.value, [index]: true }
    try {
      const result = await provider.value.createIsochrone({
        placeId: poi.place.uid,
        origin: effectiveCoord(poi.place),
        thresholdSeconds,
        maxPairs: 64,
      })
      if (compareEpoch === epoch && compareTokens.get(index) === token) {
        compareIsochrones.value = { ...compareIsochrones.value, [index]: result }
      }
    } catch (err) {
      if (compareEpoch === epoch && compareTokens.get(index) === token) {
        const next = { ...compareIsochrones.value }
        delete next[index]
        compareIsochrones.value = next
        error.value = err instanceof Error ? err.message : String(err)
      }
    } finally {
      if (compareEpoch === epoch && compareTokens.get(index) === token) {
        compareLoading.value = { ...compareLoading.value, [index]: false }
      }
    }
  }

  async function toggleCompare(index: number): Promise<void> {
    if (compareIndices.value.includes(index)) {
      compareTokens.set(index, (compareTokens.get(index) ?? 0) + 1)
      compareIndices.value = compareIndices.value.filter((item) => item !== index)
      const nextIsochrones = { ...compareIsochrones.value }
      const nextLoading = { ...compareLoading.value }
      delete nextIsochrones[index]
      delete nextLoading[index]
      compareIsochrones.value = nextIsochrones
      compareLoading.value = nextLoading
      return
    }
    if (compareIndices.value.length >= 3) {
      error.value = '最多对比 3 个地点'
      return
    }
    compareIndices.value = [...compareIndices.value, index]
    await loadCompareIsochrone(index, isochroneThreshold.value)
  }

  async function reloadCompare(thresholdSeconds = isochroneThreshold.value): Promise<void> {
    await Promise.all(compareIndices.value.map((index) => loadCompareIsochrone(index, thresholdSeconds)))
  }

  function scheduleReplan(delayMs = 300): void {
    clearTimeout(planTimer)
    planTimer = setTimeout(() => {
      void planCommute()
    }, delayMs)
  }

  function setCommunityGridPoints(points: CommunityGridPoint[]): void {
    communityGridPoints.value = points
  }

  function scheduleRanking(delayMs = 120): void {
    clearTimeout(rankTimer)
    rankTimer = setTimeout(() => {
      recomputeRanking()
    }, delayMs)
  }

  function resetState(): void {
    // F50：复位即递增全部 sequence/token，在途旧响应按序号丢弃，不回写已清空页面。
    planSeq += 1
    isoSeq += 1
    evidenceSeq += 1
    compareEpoch++
    compareTokens.clear()
    clearTimeout(planTimer)
    clearTimeout(rankTimer)
    companyCandidates.value = []
    homeCandidates.value = []
    company.value = null
    home.value = null
    route.value = null
    rankedPois.value = []
    selectedPoiIndex.value = null
    isochrone.value = null
    evidence.value = null
    corridorPois.value = []
    inboundDurations.value = {}
    outboundDurations.value = {}
    detourGeometries.value = []
    compareIndices.value = []
    compareIsochrones.value = {}
    compareLoading.value = {}
    communityGridPoints.value = []
    retrievalWarnings.value = []
    loading.value = false
    error.value = ''
    stage.value = 'idle'
  }

  watch(category, () => {
    if (restoring.value) return
    invalidateCandidates()
    if (company.value && home.value) scheduleReplan()
  }, { flush: 'sync' })
  watch([extraBudgetMinutes, serviceMinutes, waitMinutes, departureClock, deadlineClock], () => {
    if (!restoring.value && corridorPois.value.length) scheduleRanking()
  })
  watch([company, home], () => {
    if (restoring.value) return
    invalidateCandidates(true)
    if (company.value && home.value) scheduleReplan()
  }, { flush: 'sync' })
  return {
    restoring,
    companyQuery, homeQuery, city, category,
    departureClock, deadlineClock,
    extraBudgetMinutes, serviceMinutes, waitMinutes, stayMinutes,
    companyCandidates, homeCandidates, company, home, route,
    rankedPois, selectedPoiIndex, isochrone, isochroneThreshold, isochroneLoading,
    evidence, evidenceLoading, detourGeometries,
    compareIndices, compareIsochrones, compareLoading,
    communityGridPoints, setCommunityGridPoints,
    corridorPois, inboundDurations, outboundDurations,
    retrievalWarnings, loading, error, stage, poiFocusIndex, focusPoiFromMap,
    searchCompany, searchHome, selectCompany, selectHome, planCommute, scheduleReplan,
    selectPoi, loadIsochrone, loadEvidence, recomputeRanking,
    toggleCompare, reloadCompare, resetState, placeIdentity,
  }
})
