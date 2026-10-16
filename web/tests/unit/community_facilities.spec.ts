import { beforeEach, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCommunityRadiusStore } from '@/stores/communityRadius'

beforeEach(() => setActivePinia(createPinia()))
it('rejects old category marker clicks and clears facility selection on scope reset', () => {
  const store = useCommunityRadiusStore()
  const place = { uid: 'same-uid', name: '验收店', coord: { lng: 116.36, lat: 40.09, crs: 'BD09' as const }, source: 'live-api' as const }
  store.setFacilities('pharmacy', '药店', [place])
  const oldKey = store.placeKey(place)
  store.selectFacility(oldKey)
  expect(store.selectedFacility?.uid).toBe('same-uid')
  store.setFacilities('breakfast', '早餐', [place])
  store.selectFacility(oldKey)
  expect(store.selectedFacility).toBeNull()
  store.selectFacility(store.placeKey(place))
  store.clear()
  expect(store.facilities).toEqual([])
  expect(store.selectedFacility).toBeNull()
  expect(store.focus).toBeNull()
})
