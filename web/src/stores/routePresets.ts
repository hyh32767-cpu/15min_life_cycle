// 命名常用路线：把当前确认的公司/家保存为「家到公司」「学校到家」等预设，
// 一键切换并触发真实重算。独立 localStorage 键保存，属于用户数据，
// 不随全局复位（复位只清应用模拟状态）一起删除。
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import type { PlaceRef } from '@/domain/types'
import { useCommuteStore } from './commute'
import { usePlanStore, type PlanTaskDraft } from './plan'

export interface RoutePreset {
  id: string
  name: string
  company: PlaceRef
  home: PlaceRef
  companyQuery: string
  homeQuery: string
  createdAt: string
  waypointTasks?: PlanTaskDraft[]
  visitOrder?: string[]
}

const STORAGE_KEY = 'shunshou-route-presets-v1'

function readPresets(): RoutePreset[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const data = JSON.parse(raw) as { presets?: RoutePreset[] }
    if (!Array.isArray(data.presets)) return []
    return data.presets.filter((preset) => preset && preset.company?.coord && preset.home?.coord)
  } catch {
    return []
  }
}

export const useRoutePresetsStore = defineStore('routePresets', () => {
  const presets = ref<RoutePreset[]>(readPresets())

  watch(presets, (value) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ presets: value }))
    } catch {
      // storage full/blocked: keep app usable
    }
  }, { deep: true })

  function save(input: {
    name: string
    company: PlaceRef
    home: PlaceRef
    companyQuery: string
    homeQuery: string
    waypointTasks?: PlanTaskDraft[]
    visitOrder?: string[]
  }): RoutePreset | null {
    const name = input.name.trim()
    if (!name || !input.company?.coord || !input.home?.coord) return null
    // 同名覆盖：用户改名重存时更新而非堆叠。
    const next = presets.value.filter((preset) => preset.name !== name)
    const preset: RoutePreset = {
      id: `route-${Date.now().toString(36)}`,
      name,
      company: input.company,
      home: input.home,
      companyQuery: input.companyQuery,
      homeQuery: input.homeQuery,
      createdAt: new Date().toISOString(),
      ...(input.waypointTasks ? { waypointTasks: JSON.parse(JSON.stringify(input.waypointTasks)) as PlanTaskDraft[], visitOrder: [...(input.visitOrder ?? [])] } : {}),
    }
    presets.value = [...next, preset]
    return preset
  }

  function remove(id: string): void {
    presets.value = presets.value.filter((preset) => preset.id !== id)
  }

  function apply(preset: RoutePreset): void {
    const commute = useCommuteStore()
    commute.companyQuery = preset.companyQuery
    commute.homeQuery = preset.homeQuery
    commute.companyCandidates = [preset.company]
    commute.homeCandidates = [preset.home]
    commute.company = preset.company
    commute.home = preset.home
    if (preset.waypointTasks) {
      const plan = usePlanStore()
      plan.tasks = JSON.parse(JSON.stringify(preset.waypointTasks)) as PlanTaskDraft[]
      plan.visitOrder = (preset.visitOrder ?? []).filter(id => plan.tasks.some(task => task.id === id))
      plan.nodeCoords = Object.fromEntries(plan.tasks.flatMap(task => task.options.filter(option => option.coord).map(option => [option.placeId, option.coord!])))
      plan.nodePlaceNames = Object.fromEntries(plan.tasks.flatMap(task => task.options.map(option => [option.placeId, option.placeName ?? task.label])))
      const maxId = Math.max(0, ...plan.tasks.map(task => Number(/^task-(\d+)$/.exec(task.id)?.[1] ?? 0)))
      plan.setTaskSeq(maxId + 1)
      plan.invalidatePlan('路径已切换')
    }
    // 同步赋值只触发一次 [company, home] watcher；scheduleReplan 会清掉旧定时器，
    // 无论此前是否已有基准路线都只重算一次。
    commute.scheduleReplan(0)
  }

  return { presets, save, remove, apply }
})
