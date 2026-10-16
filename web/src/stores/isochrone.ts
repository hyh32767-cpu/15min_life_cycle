// F55 独立等时圈 store + F57 圈内 POI：任意起点（地图点选/地址搜索/自定位）+ 阈值切换，
// 支持 L2 降级链先行生成 + 后台全量路网渐进升级；请求序号防旧覆盖，复位清状态。
import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import type { IsochroneResult, NamedCoord } from '@/domain/types'
import { estimateL2Circle, saveUserPrefs } from '@/domain/lifeCircle'
import { ResultCache } from '@/domain/resultCache'
import type { IsochronePoiRow } from '@/providers/contracts'
import { useAppStore } from '@/stores/app'

export const ISOCHRONE_THRESHOLDS = [300, 600, 900] as const

export const useIsochroneStore = defineStore('isochrone', () => {
  const app = useAppStore()
  const circleCache = new ResultCache<IsochroneResult>()
  const rangeReused = ref(false)
  function circleKey(coord: NamedCoord, seconds: number): string {
    return JSON.stringify(['grid-frontier-barrier-v4-measured-delaunay-v1', coord.crs, coord.lng, coord.lat, seconds, 1100, 376, 100])
  }
  async function getCircle(coord: NamedCoord, seconds: number): Promise<{ response: IsochroneResult; reused: boolean }> {
    const key = circleKey(coord, seconds)
    const cached = circleCache.get(key)
    if (cached) return { response: cached, reused: true }
    const response = await app.provider.createIsochrone({ origin: coord, thresholdSeconds: seconds, maxPairs: 376, frontier: true, l2First: true })
    if (response.status === 'complete' && response.backgroundStatus !== 'running' && response.thresholdSeconds === seconds) {
      circleCache.put(key, response, [response.expiresAt])
      if (response.origin) circleCache.put(circleKey(response.origin, seconds), response, [response.expiresAt])
    }
    return { response, reused: response.status === 'complete' && (response.cacheHit || response.sourceKind === 'api-cache') }
  }

  const origin = ref<NamedCoord | null>(null)
  // Track deliberate selections separately from the backend's normalized origin.
  // Selecting the same coordinate should regenerate via cache without response loops.
  const originSelection = ref(0)
  const originLabel = ref('')
  const thresholdSeconds = ref<number>(900)
  const result = ref<IsochroneResult | null>(null)
  const l2Preview = ref<IsochroneResult | null>(null)
  const backgroundStatus = ref<'idle' | 'running' | 'completed' | 'degraded' | null>(null)
  const loading = ref(false)
  const error = ref('')
  const heatLayers = ref<IsochroneResult[]>([])
  const heatLoading = ref(false)
  const heatError = ref('')
  const busy = computed(() => loading.value || backgroundStatus.value === 'running' || heatLoading.value)
  let heatSeq = 0

  function clearHeat(): void {
    heatSeq++
    heatLayers.value = []
    heatLoading.value = false
    heatError.value = ''
  }

  async function loadHeatLayers(): Promise<void> {
    if (busy.value) return
    if (!origin.value || !result.value) return
    if (result.value.thresholdSeconds !== 900) return
    const current = ++heatSeq
    const center = { ...origin.value }
    const threshold = 900
    const layers: IsochroneResult[] = result.value.expiresAt && Date.parse(result.value.expiresAt) <= Date.now() ? [] : [result.value]
    heatLayers.value = [...layers]
    heatLoading.value = true
    heatError.value = ''
    async function measuredLayer(seconds: number): Promise<IsochroneResult> {
      let layer = (await getCircle(center, seconds)).response
      for (let attempt = 0; layer.backgroundStatus === 'running' && attempt < 120; attempt++) {
        if (current !== heatSeq) throw new Error('已取消')
        if (!app.provider.getIsochroneTaskStatus) throw new Error('步行范围查询暂不可用')
        await new Promise(resolve => setTimeout(resolve, 1500))
        layer = await app.provider.getIsochroneTaskStatus(layer.taskId)
      }
      if (layer.backgroundStatus === 'running') throw new Error('时间分层仍在生成，请稍后重试')
      if (layer.status === 'complete') {
        circleCache.put(circleKey(center, seconds), layer, [layer.expiresAt])
      }
      return layer
    }
    try {
      if (!layers.length) layers.push(await measuredLayer(threshold))
      for (const seconds of ISOCHRONE_THRESHOLDS.filter(value => value < threshold)) {
        if (current !== heatSeq) return
        layers.push(await measuredLayer(seconds))
        if (current === heatSeq) heatLayers.value = [...layers].sort((a, b) => b.thresholdSeconds - a.thresholdSeconds)
      }
      if (current === heatSeq) {
        heatLayers.value = layers.sort((a, b) => b.thresholdSeconds - a.thresholdSeconds)
        if (layers.some(layer => layer.status !== 'complete')) heatError.value = '部分时间层未测完整，地图仅填色显示完整时间层。'
      }
    } catch (error) {
      if (current === heatSeq) heatError.value = error instanceof Error ? error.message : String(error)
    } finally {
      if (current === heatSeq) heatLoading.value = false
    }
  }
  // F57：圈内 POI（区域召回 + 起点有向矩阵过滤），与圈请求独立序号。
  const poiTerms = ref('药店 便利店')
  const reachable = ref<IsochronePoiRow[]>([])
  const unreachable = ref<IsochronePoiRow[]>([])
  const poisLoading = ref(false)
  const poisLoaded = ref(false)
  const poisError = ref('')
  const pairsUsedPois = ref(0)
  // F67：百度可检索截断标记，展示用。
  const poiTruncated = ref(false)
  const poiTruncationReason = ref<string | null>(null)
  let seq = 0
  let poiSeq = 0
  watch(thresholdSeconds, () => {
    seq++
    clearHeat()
    result.value = null
    l2Preview.value = null
    backgroundStatus.value = null
    loading.value = false
    poiSeq++
    reachable.value = []
    unreachable.value = []
    poisLoaded.value = false
    poisLoading.value = false
    error.value = ''
    poisError.value = ''
    poiTruncated.value = false
    poiTruncationReason.value = null
    pairsUsedPois.value = 0
  }, { flush: 'sync' })

  const hasOrigin = computed(() => origin.value != null)

  function setOrigin(coord: NamedCoord, label = ''): void {
    clearHeat()
    // 起点变更会使在途等时圈和 POI 请求失效，避免旧响应回写新起点。
    seq += 1
    poiSeq += 1
    origin.value = { ...coord }
    originLabel.value = label
    rangeReused.value = false
    result.value = null
    l2Preview.value = null
    backgroundStatus.value = null
    error.value = ''
    loading.value = false
    reachable.value = []
    unreachable.value = []
    poisError.value = ''
    poisLoading.value = false
    poisLoaded.value = false
    pairsUsedPois.value = 0
    poiTruncated.value = false
    poiTruncationReason.value = null
    originSelection.value++
  }

  async function pollBackgroundUpgrade(taskId: string, currentSeq: number, coord: NamedCoord, seconds: number): Promise<void> {
    if (!app.provider.getIsochroneTaskStatus) throw new Error('步行范围查询暂不可用，请重试')
    let failures = 0
    for (let attempt = 0; attempt < 180; attempt++) {
      await new Promise(resolve => setTimeout(resolve, attempt < 5 ? 600 : 1500))
      if (currentSeq !== seq) return
      try {
        const updated = await app.provider.getIsochroneTaskStatus(taskId)
        if (currentSeq !== seq) return
        failures = 0
        backgroundStatus.value = updated.backgroundStatus ?? null
        if (updated.status === 'complete' || updated.status === 'partial') {
          result.value = updated
          l2Preview.value = null
        }
        if (updated.backgroundStatus !== 'running') {
          result.value = updated
          l2Preview.value = null
          if (updated.status === 'complete' && updated.thresholdSeconds === seconds) {
            const key = circleKey(coord, seconds)
            circleCache.put(key, updated, [updated.expiresAt])
            if (updated.origin) circleCache.put(circleKey(updated.origin, seconds), updated, [updated.expiresAt])
          }
          return
        }
      } catch (err) {
        if (++failures >= 3) throw err
      }
    }
    if (currentSeq === seq) throw new Error('步行范围生成较久，请稍后重试，已完成的范围会保留')
  }

  async function run(threshold?: number): Promise<void> {
    if (busy.value) return
    clearHeat()
    const current = origin.value
    if (!current) {
      error.value = '请先选择地点'
      return
    }
    if (threshold != null) {
      thresholdSeconds.value = threshold
      saveUserPrefs({ thresholdSeconds: threshold })
    }
    const currentSeq = ++seq
    // F71：切阈值同时失效旧圈内 POI 结果，不把旧阈值 POI 显示在新阈值下。
    ++poiSeq
    poisLoaded.value = false
    poisLoading.value = false
    poiTruncated.value = false
    poiTruncationReason.value = null
    pairsUsedPois.value = 0
    reachable.value = []
    unreachable.value = []
    poisError.value = ''
    loading.value = true
    result.value = null
    rangeReused.value = false
    error.value = ''
    // L2 降级链先行生成：0ms 立即在地图和面板提供 L2 预估圈，随后后台实测真实路网并平滑升级。
    l2Preview.value = estimateL2Circle(current, thresholdSeconds.value, originLabel.value)
    backgroundStatus.value = 'running'
    try {
      const { response, reused } = await getCircle(current, thresholdSeconds.value)
      if (currentSeq === seq) {
        result.value = response
        l2Preview.value = response.backgroundStatus === 'running' && response.status === 'degraded' ? response : null
        backgroundStatus.value = response.backgroundStatus ?? (response.status === 'complete' ? 'completed' : 'degraded')
        rangeReused.value = reused
        // 后端会把 WGS84/GCJ02 起点统一转换为百度 BD09；地图只接受 BD09，
        // 因此用同一响应中的 origin 回写地图中心，避免自定位后底图报 CRS 错误。
        if (response.origin?.crs === 'BD09') origin.value = response.origin
        if (response.backgroundStatus === 'running' && response.taskId) {
          await pollBackgroundUpgrade(response.taskId, currentSeq, current, thresholdSeconds.value)
        }
        if (currentSeq === seq && result.value?.status !== 'complete') error.value = '部分步行范围未能查到，请稍后重试或更换地点'
      }
    } catch (err) {
      if (currentSeq === seq) {
        l2Preview.value = null
        backgroundStatus.value = 'degraded'
        error.value = err instanceof Error ? err.message : String(err)
      }
    } finally {
      if (currentSeq === seq) loading.value = false
    }
  }

  async function generateLifeCircle(): Promise<void> {
    if (busy.value) return
    const pending = run(900)
    const current = seq
    await pending
    if (current !== seq) return
    if (result.value?.status === 'complete' && result.value.thresholdSeconds === 900 && !error.value) await loadHeatLayers()
  }

  async function loadPois(): Promise<void> {
    const current = origin.value
    if (!current) {
      poisError.value = '请先选择地点，再查询附近设施'
      return
    }
    const terms = poiTerms.value.split(/\s+/).map((term) => term.trim()).filter(Boolean)
    if (!terms.length) {
      poisError.value = '请输入设施类别，如：药店'
      return
    }
    const currentSeq = ++poiSeq
    poisLoaded.value = false
    poisLoading.value = true
    poisError.value = ''
    try {
      const response = await app.provider.getIsochronePois({
        origin: current,
        thresholdSeconds: thresholdSeconds.value,
        queryTerms: terms,
        radiiM: (result.value ?? l2Preview.value)?.radiiM,
      })
      if (currentSeq === poiSeq) {
        reachable.value = response.reachable
        poisLoaded.value = true
        unreachable.value = response.unreachable
        pairsUsedPois.value = response.pairsUsed
        // F67：截断与转换追踪随响应透传展示，不静默丢弃。
        poiTruncated.value = response.retrieval?.truncated === true
        poiTruncationReason.value = typeof response.retrieval?.truncationReason === 'string'
          ? response.retrieval.truncationReason
          : null
      }
    } catch (err) {
      if (currentSeq === poiSeq) {
        reachable.value = []
        unreachable.value = []
        poisError.value = err instanceof Error ? err.message : String(err)
        poiTruncated.value = false
        poiTruncationReason.value = null
      }
    } finally {
      if (currentSeq === poiSeq) poisLoading.value = false
    }
  }

  function reset(): void {
    clearHeat()
    seq += 1
    poiSeq += 1
    origin.value = null
    originLabel.value = ''
    rangeReused.value = false
    result.value = null
    l2Preview.value = null
    backgroundStatus.value = null
    error.value = ''
    loading.value = false
    thresholdSeconds.value = 900
    reachable.value = []
    unreachable.value = []
    poisError.value = ''
    poisLoading.value = false
    poisLoaded.value = false
    pairsUsedPois.value = 0
    poiTruncated.value = false
    poiTruncationReason.value = null
  }

  return {
    rangeReused,
    origin,
    originSelection,
    originLabel,
    thresholdSeconds,
    result,
    l2Preview,
    backgroundStatus,
    loading,
    busy,
    error,
    heatLayers, heatLoading, heatError, loadHeatLayers, clearHeat, generateLifeCircle,
    hasOrigin,
    setOrigin,
    run,
    reset,
    poiTerms,
    reachable,
    unreachable,
    poisLoading,
    poisLoaded,
    poisError,
    pairsUsedPois,
    poiTruncated,
    poiTruncationReason,
    loadPois,
  }
})
