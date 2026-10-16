import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { useAppStore } from '@/stores/app'
import { useMapRouteStore } from '@/stores/mapRoute'
import type { WalkingRouteResult } from '@/providers/contracts'

const coord = { lng: 116.3, lat: 40, crs: 'BD09' as const }
const place = { uid: 'a', name: '甲', coord, source: 'api-cache' as const }
const route: WalkingRouteResult = { traceId: 't', mode: 'live', sourceKind: 'api-cache', cacheHit: true, warnings: [], route: { durationSeconds: 300, distanceM: 400, geometry: [coord, { ...coord, lng: 116.4 }], steps: [] } }
beforeEach(() => setActivePinia(createPinia()))
it('drops a late route after closing and deduplicates repeated clicks while pending', async () => {
  let finish!: (value: WalkingRouteResult) => void
  const request = vi.spyOn(useAppStore().provider, 'getWalkingRoute').mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const store = useMapRouteStore()
  const pending = store.open(place, coord)
  await store.open(place, coord)
  expect(request).toHaveBeenCalledTimes(1)
  store.clear()
  finish(route)
  await pending
  expect(store.destination).toBeNull()
  expect(store.result).toBeNull()
})
it('resolves base-map POI details before routing to the actual entrance', async () => {
  const app = useAppStore()
  const detailed = { ...place, name: '甲入口', naviCoord: { ...coord, lng: 116.35 } }
  vi.spyOn(app.provider, 'getLocationDetail').mockResolvedValue({ traceId: 'detail', place: detailed })
  const request = vi.spyOn(app.provider, 'getWalkingRoute').mockResolvedValue(route)
  const store = useMapRouteStore()
  await store.open(place, coord, true)
  expect(request).toHaveBeenCalledWith(coord, detailed.naviCoord)
  expect(store.destination?.name).toBe('甲入口')
  expect(store.result).toEqual(route)
})
