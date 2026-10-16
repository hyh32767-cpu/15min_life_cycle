import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import type { NamedCoord } from '@/domain/types'
import type { RouteBandResult } from '@/providers/contracts'
import { inMeasuredBand } from '@/domain/routeBand'
import { useAppStore } from './app'
import { useCommuteStore } from './commute'

export const useRouteBandStore = defineStore('route-band', () => {
  const app = useAppStore()
  const commute = useCommuteStore()
  const enabled = ref(false)
  const thresholdSeconds = ref(900)
  const result = ref<RouteBandResult | null>(null)
  const loading = ref(false)
  const supplementing = ref(false)
  const onlyMeasured = ref(false)
  const selectedIndex = ref(0)
  const error = ref('')
  let sequence = 0
  const routeKey = computed(() => JSON.stringify([commute.route?.route.geometry ?? [], commute.company?.coord, commute.home?.coord]))
  const focus = computed(() => enabled.value ? result.value?.nodes[selectedIndex.value]?.origin ?? null : null)
  const pendingCount = computed(() => result.value?.nodes.filter(node => node.status !== 'complete').length ?? 0)
  function includes(point: NamedCoord): boolean { return enabled.value && inMeasuredBand(point, result.value?.fills ?? []) }
  function clear(): void {
    sequence++
    result.value = null
    error.value = ''
    loading.value = false
    supplementing.value = false
    onlyMeasured.value = false
    selectedIndex.value = 0
  }
  async function preview(): Promise<void> {
    const geometry = commute.route?.route.geometry
    if (!enabled.value || !geometry?.length) return
    const current = ++sequence
    loading.value = true
    error.value = ''
    try {
      const next = await app.provider.getRouteBand({ routeGeometry: geometry, thresholdSeconds: thresholdSeconds.value,
        maxCenters: 5, maxPairs: 1880, cacheOnly: true })
      if (current === sequence) result.value = next
    } catch (err) {
      if (current === sequence) error.value = err instanceof Error ? err.message : String(err)
    } finally { if (current === sequence) loading.value = false }
  }
  async function supplement(): Promise<void> {
    const geometry = commute.route?.route.geometry
    if (!geometry || !result.value || loading.value || supplementing.value) return
    const current = ++sequence
    const threshold = thresholdSeconds.value
    const pending = result.value.nodes.filter(node => node.status !== 'complete').map(node => node.index)
    supplementing.value = true
    error.value = ''
    try {
      for (const index of pending) {
        if (current !== sequence) return
        let next = await app.provider.getRouteBand({ routeGeometry: geometry, thresholdSeconds: threshold,
          maxCenters: 5, maxPairs: 1880, cacheOnly: false, centerIndex: index })
        for (let attempt = 0; next.nodes[index]?.backgroundStatus === 'running' && attempt < 200; attempt++) {
          if (current !== sequence) return
          result.value = next
          await new Promise(resolve => setTimeout(resolve, 1500))
          if (current !== sequence) return
          const taskId = next.nodes[index]?.taskId
          if (!taskId) throw new Error('步行范围查询暂不可用')
          next = await app.provider.getRouteBand({ routeGeometry: geometry, thresholdSeconds: threshold,
            maxCenters: 5, maxPairs: 1880, cacheOnly: true, taskIds: { [index]: taskId } })
        }
        if (current !== sequence) return
        result.value = next
        if (next.nodes[index]?.status !== 'complete') {
          error.value = '部分位置暂时无法测量，已保存范围仍可查看，请稍后补齐'
          break
        }
      }
    } catch (err) {
      if (current === sequence) error.value = err instanceof Error ? err.message : String(err)
    } finally { if (current === sequence) supplementing.value = false }
  }
  function toggle(): void {
    enabled.value = !enabled.value
    clear()
    if (enabled.value) void preview()
  }
  function reset(): void { enabled.value = false; thresholdSeconds.value = 900; clear() }
  watch(routeKey, () => { clear(); if (enabled.value && !commute.loading) void preview() }, { flush: 'sync' })
  watch(() => commute.loading, loading => {
    if (!loading && enabled.value && !result.value && !supplementing.value) void preview()
  })
  watch(onlyMeasured, value => {
    const poi = commute.selectedPoiIndex == null ? null : commute.rankedPois[commute.selectedPoiIndex]
    if (value && poi && !includes(poi.place.naviCoord ?? poi.place.coord)) void commute.selectPoi(null, false)
  })
  return { enabled, thresholdSeconds, result, loading, supplementing, onlyMeasured, selectedIndex, error,
    focus, pendingCount, includes, preview, supplement, toggle, reset }
})
