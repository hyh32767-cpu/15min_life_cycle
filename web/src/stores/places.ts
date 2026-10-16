// 常去地点（高德式「常用地址」）：保存命名地点，一键填入公司/家槽位。
// 独立 localStorage 键，属用户数据，不随全局复位清除。
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import type { PlaceRef } from '@/domain/types'
import { useCommuteStore } from './commute'

export interface FavoritePlace {
  id: string
  label: string
  place: PlaceRef
  createdAt: string
}

export type PlaceSlot = 'company' | 'home'

const STORAGE_KEY = 'shunshou-places-v1'

function readPlaces(): FavoritePlace[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const data = JSON.parse(raw) as { places?: FavoritePlace[] }
    if (!Array.isArray(data.places)) return []
    return data.places.filter((item) => item && item.label && item.place?.coord)
  } catch {
    return []
  }
}

export const usePlacesStore = defineStore('places', () => {
  const places = ref<FavoritePlace[]>(readPlaces())

  watch(places, (value) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ places: value }))
    } catch {
      // storage full/blocked: keep app usable
    }
  }, { deep: true })

  function save(input: { label: string; place: PlaceRef }): FavoritePlace | null {
    const label = input.label.trim()
    if (!label || !input.place?.coord) return null
    // 同名覆盖：重新保存同名地点时更新坐标而不是堆叠。
    const next = places.value.filter((item) => item.label !== label)
    const entry: FavoritePlace = {
      id: `place-${Date.now().toString(36)}`,
      label,
      place: input.place,
      createdAt: new Date().toISOString(),
    }
    places.value = [...next, entry]
    return entry
  }

  function remove(id: string): void {
    places.value = places.value.filter((item) => item.id !== id)
  }

  function use(place: PlaceRef, slot: PlaceSlot): void {
    const commute = useCommuteStore()
    if (slot === 'company') {
      commute.companyQuery = place.name
      commute.companyCandidates = [place]
      commute.company = place
    } else {
      commute.homeQuery = place.name
      commute.homeCandidates = [place]
      commute.home = place
    }
    commute.scheduleReplan(0)
  }

  return { places, save, remove, use }
})
