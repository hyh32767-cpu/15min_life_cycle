import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { NamedCoord, PlaceRef } from '@/domain/types'

export const useCommunityRadiusStore = defineStore('communityRadius', () => {
  const focus = ref<NamedCoord | null>(null)
  const serviceId = ref('')
  const serviceLabel = ref('')
  const facilities = ref<PlaceRef[]>([])
  const selectedPlaceKey = ref('')
  function placeKey(place: PlaceRef): string {
    const coord = place.naviCoord ?? place.coord
    return `${serviceId.value}:${place.uid ?? place.name}:${coord.crs}:${coord.lng}:${coord.lat}`
  }
  const selectedFacility = computed(() => facilities.value.find(place => placeKey(place) === selectedPlaceKey.value) ?? null)
  function setFacilities(id: string, label: string, places: PlaceRef[]): void {
    serviceId.value = id
    serviceLabel.value = label
    facilities.value = places
    closeFacility()
  }
  function selectFacility(key: string): void {
    const place = facilities.value.find(item => placeKey(item) === key)
    if (!place) return
    selectedPlaceKey.value = key
    focus.value = place.naviCoord ?? place.coord
  }
  function closeFacility(): void { selectedPlaceKey.value = ''; focus.value = null }
  function clear(): void { closeFacility(); serviceId.value = ''; serviceLabel.value = ''; facilities.value = [] }
  return { focus, serviceId, serviceLabel, facilities, selectedFacility, setFacilities, selectFacility, closeFacility, placeKey, clear }
})
