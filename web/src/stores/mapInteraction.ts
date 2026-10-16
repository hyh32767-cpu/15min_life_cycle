import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { NamedCoord, PlaceRef } from '@/domain/types'

export type MapPickTarget = 'manual-plan' | 'waypoint' | 'community-center' | 'community-facility' | 'route-start' | 'route-end' | 'saved-place' | null

export const useMapInteractionStore = defineStore('mapInteraction', () => {
  const pickTarget = ref<MapPickTarget>(null)
  const selectedCoord = ref<NamedCoord | null>(null)
  const selectedFor = ref<MapPickTarget>(null)
  const selectedPlace = ref<PlaceRef | null>(null)
  const waypointRequest = ref<{ place: PlaceRef } | null>(null)
  const editingWaypoints = ref(false)
  const showFacilities = ref(true)
  const showBlindSpots = ref(false)
  const placePickerRequested = ref(false)
  const panelExpandRequested = ref(false)

  function beginPick(target: Exclude<MapPickTarget, null>): void {
    pickTarget.value = target
    selectedFor.value = null
    selectedPlace.value = null
    waypointRequest.value = null
  }

  function completePick(coord: NamedCoord, place?: PlaceRef): MapPickTarget {
    const target = pickTarget.value
    if (target) {
      selectedCoord.value = coord
      selectedPlace.value = place ?? { name: '地图地点', coord, source: 'user-input' }
      selectedFor.value = target
      pickTarget.value = null
    }
    return target
  }

  function selected(target: Exclude<MapPickTarget, null>): NamedCoord | null {
    return selectedFor.value === target ? selectedCoord.value : null
  }

  function clearSelected(target: Exclude<MapPickTarget, null>): void {
    if (selectedFor.value === target) {
      selectedCoord.value = null
      selectedFor.value = null
      selectedPlace.value = null
    }
  }

  function reset(): void {
    pickTarget.value = null
    selectedCoord.value = null
    selectedFor.value = null
    selectedPlace.value = null
    waypointRequest.value = null
    editingWaypoints.value = false
    panelExpandRequested.value = false
  }

  return { showFacilities, showBlindSpots, placePickerRequested, panelExpandRequested, pickTarget, selectedCoord, selectedFor, selectedPlace, waypointRequest, editingWaypoints, beginPick, completePick, selected, clearSelected, reset }
})
