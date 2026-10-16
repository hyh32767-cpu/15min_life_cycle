import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { NamedCoord, PlaceRef } from '@/domain/types'
import type { WalkingRouteResult } from '@/providers/contracts'
import { useAppStore } from './app'

export const useMapRouteStore = defineStore('mapRoute', () => {
  const app = useAppStore()
  const destination = ref<PlaceRef | null>(null)
  const origin = ref<NamedCoord | null>(null)
  const result = ref<WalkingRouteResult | null>(null)
  const loading = ref(false)
  const error = ref('')
  let sequence = 0
  let pendingKey = ''
  function clear(): void {
    sequence++
    pendingKey = ''
    destination.value = null
    origin.value = null
    result.value = null
    loading.value = false
    error.value = ''
  }
  async function open(place: PlaceRef, start: NamedCoord | null, fetchDetail = false): Promise<void> {
    const key = JSON.stringify([place.uid, place.coord, start])
    if (loading.value && pendingKey === key) return
    const current = ++sequence
    pendingKey = key
    destination.value = place
    origin.value = start
    result.value = null
    error.value = ''
    loading.value = true
    try {
      if (fetchDetail && place.uid) {
        if (!app.provider.getLocationDetail) throw new Error('地点详情暂时不可用，请搜索这个地点后重试')
        const detail = await app.provider.getLocationDetail(place.uid)
        if (current !== sequence) return
        destination.value = detail.place
      }
      if (!start) { error.value = '先选择起点，再规划去这里的路线'; return }
      const target = destination.value!
      const route = await app.provider.getWalkingRoute(start, target.naviCoord ?? target.coord)
      if (current === sequence) result.value = route
    } catch (err) {
      if (current === sequence) error.value = err instanceof Error ? err.message : String(err)
    } finally { if (current === sequence) loading.value = false }
  }
  return { destination, origin, result, loading, error, open, clear }
})
