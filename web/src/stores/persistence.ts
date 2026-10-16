import { nextTick, watch } from 'vue'
import { defineStore } from 'pinia'

import { useCommuteStore } from './commute'
import { useExecutionStore } from './execution'
import { usePlanStore } from './plan'
const STORAGE_KEY = 'shunshou-v1'
const SNAPSHOT_VERSION = 4

export const HYDRATION_EVENT = 'shunshou:hydrated'

export function notifyHydrated(restored: boolean): void {
  window.dispatchEvent(new CustomEvent(HYDRATION_EVENT, { detail: { restored } }))
}

export const usePersistenceStore = defineStore('persistence', () => {
  function snapshot(): string {
    const commute = useCommuteStore()
    const plan = usePlanStore()
    const execution = useExecutionStore()
    return JSON.stringify({
      version: SNAPSHOT_VERSION,
      commute: {
        companyQuery: commute.companyQuery,
        homeQuery: commute.homeQuery,
        city: commute.city,
        category: commute.category,
        departureClock: commute.departureClock,
        deadlineClock: commute.deadlineClock,
        extraBudgetMinutes: commute.extraBudgetMinutes,
        serviceMinutes: commute.serviceMinutes,
        waitMinutes: commute.waitMinutes,
        company: commute.company,
        home: commute.home,
        route: commute.route,
        rankedPois: commute.rankedPois,
        selectedPoiIndex: commute.selectedPoiIndex,
        isochrone: commute.isochrone,
        isochroneThreshold: commute.isochroneThreshold,
        evidence: commute.evidence,
        detourGeometries: commute.detourGeometries,
        compareIndices: commute.compareIndices,
        compareIsochrones: commute.compareIsochrones,
        corridorPois: commute.corridorPois,
        inboundDurations: commute.inboundDurations,
        outboundDurations: commute.outboundDurations,
        retrievalWarnings: commute.retrievalWarnings,
        stage: commute.stage,
      },
      plan: {
        tasks: plan.tasks,
        visitOrder: plan.visitOrder,
        departureClock: plan.departureClock,
        deadlineClock: plan.deadlineClock,
        preference: plan.preference,
        result: plan.result,
        travelTimes: plan.travelTimes,
        nodeCoords: plan.nodeCoords,
        nodePlaceNames: plan.nodePlaceNames,
        nextTaskSeq: nextTaskSeq(plan.tasks),
      },
      execution: {
        selectedAltIndex: execution.selectedAltIndex,
        completedTaskIds: execution.completedTaskIds,
        skippedTaskIds: execution.skippedTaskIds,
        completedPlaceIds: execution.completedPlaceIds,
        currentNodeId: execution.currentNodeId,
        currentTimeSeconds: execution.currentTimeSeconds,
        virtualClock: execution.virtualClock,
        events: execution.events,
        nextEventSeq: nextEventSeq(execution.events),
        replan: execution.replan,
        beforeFinish: execution.beforeFinish,
      },
    })
  }

  function nextTaskSeq(tasks: { id: string }[]): number {
    let max = 0
    for (const task of tasks) {
      const match = /^task-(\d+)$/.exec(task.id)
      if (match) max = Math.max(max, Number(match[1]))
    }
    return max + 1
  }

  function nextEventSeq(events: { id: string }[]): number {
    let max = 0
    for (const event of events) {
      const match = /^ev-(\d+)$/.exec(event.id)
      if (match) max = Math.max(max, Number(match[1]))
    }
    return max + 1
  }

  function restore(): boolean {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return false
      const data = JSON.parse(raw) as {
        version?: number
        commute?: Record<string, never>
        plan?: {
          tasks?: never[]
          departureClock?: string
          deadlineClock?: string
          preference?: 'fastest' | 'least_walk'
          visitOrder?: string[]
          result?: Record<string, never> | null
          travelTimes?: never[]
          nodeCoords?: Record<string, never>
          nodePlaceNames?: Record<string, string>
          nextTaskSeq?: number
        }
        execution?: {
          selectedAltIndex?: number
          completedTaskIds?: string[]
          skippedTaskIds?: string[]
          completedPlaceIds?: string[]
          currentNodeId?: string
          currentTimeSeconds?: number | null
          virtualClock?: string
          events?: never[]
          nextEventSeq?: number
          replan?: Record<string, never> | null
          beforeFinish?: string
        }
      }
      if (data.version !== 3 && data.version !== SNAPSHOT_VERSION) return false
      const commute = useCommuteStore()
      const plan = usePlanStore()
      const execution = useExecutionStore()
      if (data.commute) {
        commute.restoring = true
        Object.assign(commute, data.commute)
        void nextTick(() => { commute.restoring = false })
      }
      if (data.plan) {
        if (data.plan.tasks) plan.tasks = data.plan.tasks as typeof plan.tasks
        if (data.plan.visitOrder) plan.visitOrder = data.plan.visitOrder.filter(id => plan.tasks.some(task => task.id === id))
        if (!data.commute?.departureClock && data.plan.departureClock) plan.departureClock = data.plan.departureClock
        if (!data.commute?.deadlineClock && data.plan.deadlineClock) plan.deadlineClock = data.plan.deadlineClock
        if (data.plan.preference) plan.preference = data.plan.preference
        if (data.plan.result !== undefined) plan.result = data.plan.result as typeof plan.result
        if (data.plan.travelTimes) plan.travelTimes = data.plan.travelTimes as typeof plan.travelTimes
        if (data.plan.nodeCoords) plan.nodeCoords = data.plan.nodeCoords as typeof plan.nodeCoords
        if (data.plan.nodePlaceNames) plan.nodePlaceNames = data.plan.nodePlaceNames
        if (data.plan.nextTaskSeq != null) plan.setTaskSeq(data.plan.nextTaskSeq)
      }
      if (data.execution) {
        if (data.execution.selectedAltIndex != null) execution.selectedAltIndex = data.execution.selectedAltIndex
        if (data.execution.completedTaskIds) execution.completedTaskIds = data.execution.completedTaskIds
        if (data.execution.skippedTaskIds) execution.skippedTaskIds = data.execution.skippedTaskIds
        if (data.execution.completedPlaceIds) execution.completedPlaceIds = data.execution.completedPlaceIds
        if (data.execution.currentNodeId) execution.currentNodeId = data.execution.currentNodeId
        if (data.execution.currentTimeSeconds !== undefined) {
          execution.currentTimeSeconds = data.execution.currentTimeSeconds
        }
        if (data.execution.virtualClock) execution.virtualClock = data.execution.virtualClock
        if (data.execution.events) execution.events = data.execution.events as typeof execution.events
        if (data.execution.nextEventSeq != null) execution.setEventSeq(data.execution.nextEventSeq)
        if (data.execution.replan !== undefined) execution.replan = data.execution.replan as typeof execution.replan
        if (data.execution.beforeFinish !== undefined) execution.beforeFinish = data.execution.beforeFinish
      }
      return true
    } catch {
      return false
    }
  }

  function persistNow(): void {
    try {
      localStorage.setItem(STORAGE_KEY, snapshot())
    } catch {
      // storage full/blocked: keep app usable
    }
  }

  function resetAppState(): void {
    const commute = useCommuteStore()
    const plan = usePlanStore()
    const execution = useExecutionStore()
    commute.resetState()
    plan.resetState()
    execution.resetExecution()
    execution.selectedAltIndex = 0
    execution.virtualClock = ''
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {
      // ignore
    }
  }

  function startAutoPersist(): void {
    const commute = useCommuteStore()
    const plan = usePlanStore()
    const execution = useExecutionStore()
    watch(
      [() => commute.$state, () => plan.$state, () => execution.$state],
      () => { persistNow() },
      { deep: true },
    )
  }

  return { snapshot, restore, persistNow, resetAppState, startAutoPersist }
})
