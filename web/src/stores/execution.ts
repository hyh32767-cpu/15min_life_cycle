import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { formatClockSeconds, parseClockToSeconds } from '@/domain/time'
import { reasonLabel } from '@/domain/sourceExplain'
import type { ReplanResult } from '@/providers/contracts'
import { useAppStore } from './app'
import { usePlanStore } from './plan'

export interface SimEvent {
  id: string
  type: 'close_place' | 'route_delay'
  targetId: string
  delaySeconds: number
}

let eventSeq = 0

function setEventSeq(next: number): void {
  if (Number.isFinite(next) && next > eventSeq) eventSeq = Math.floor(next)
}

export const useExecutionStore = defineStore('execution', () => {
  const app = useAppStore()
  const plan = usePlanStore()
  const selectedAltIndex = ref(0)
  const completedTaskIds = ref<string[]>([])
  const skippedTaskIds = ref<string[]>([])
  const completedPlaceIds = ref<string[]>([])
  const currentNodeId = ref('S')
  const currentTimeSeconds = ref<number | null>(null)
  const virtualClock = ref('')
  const events = ref<SimEvent[]>([])
  const replan = ref<ReplanResult | null>(null)
  const beforeFinish = ref<string>('')
  const loading = ref(false)
  const error = ref('')
  const closeTarget = ref('')
  const delayTarget = ref('')
  const delayMinutes = ref(5)
  let replanGeneration = 0

  const provider = computed(() => app.provider)

  const baseAlternative = computed(() => {
    if (replan.value?.status === 'ready') return replan.value.plan.alternatives[0] ?? null
    if (!plan.result || plan.result.status !== 'ready') return null
    return plan.result.alternatives[selectedAltIndex.value]
      ?? plan.result.alternatives[0] ?? null
  })

  const remainingTasks = computed(() =>
    plan.tasks.filter((t) => !completedTaskIds.value.includes(t.id)),
  )

  function syncFromPlan(): void {
    if (!plan.result || plan.result.status !== 'ready') {
      error.value = '请先规划行程'
      return
    }
    error.value = ''
    if (selectedAltIndex.value >= plan.result.alternatives.length) {
      selectedAltIndex.value = 0
    }
    if (!virtualClock.value) {
      virtualClock.value = formatClockSeconds(
        plan.result.alternatives[selectedAltIndex.value]?.departureSeconds
        ?? plan.result.alternatives[0].departureSeconds)
    }
  }

  function stopPlaceForTask(id: string): string | null {
    const stop = baseAlternative.value?.stops.find((s) => s.taskId === id)
    return stop?.placeId ?? null
  }

  function blockReason(id: string): string | null {
    if (replan.value?.status === 'infeasible') return '暂时无法安排，请调整地点或时间'
    const stops = baseAlternative.value?.stops ?? []
    if (!stops.some((s) => s.taskId === id)) return '不在当前执行方案中'
    const unmet = plan.taskPredecessors(id).filter((dep) => !completedTaskIds.value.includes(dep))
    if (unmet.length) {
      return `需先完成：${unmet.map((dep) => plan.tasks.find((t) => t.id === dep)?.label ?? dep).join('、')}`
    }
    const position = new Map(stops.map((s, index) => [s.taskId, index]))
    const myIndex = position.get(id) ?? Number.MAX_SAFE_INTEGER
    const skipped = stops
      .filter((s) => (position.get(s.taskId) ?? Number.MAX_SAFE_INTEGER) < myIndex)
      .map((s) => s.taskId)
      .filter((tid) => tid !== id && !completedTaskIds.value.includes(tid))
    if (skipped.length) {
      return `按方案顺序先完成：${[...new Set(skipped)].map((tid) => plan.tasks.find((t) => t.id === tid)?.label ?? tid).join('、')}`
    }
    return null
  }

  function canComplete(id: string): boolean {
    return blockReason(id) === null
  }

  function completeTask(id: string): void {
    const blocked = blockReason(id)
    if (blocked) {
      error.value = blocked.startsWith('不在当前') ? '这个地点还未加入路线，请先规划行程' : blocked
      return
    }
    const placeId = stopPlaceForTask(id)
    if (!placeId) {
      error.value = '这个地点还未加入路线，请先规划行程'
      return
    }
    error.value = ''
    if (!completedTaskIds.value.includes(id)) {
      completedTaskIds.value = [...completedTaskIds.value, id]
    }
    if (!completedPlaceIds.value.includes(placeId)) {
      completedPlaceIds.value = [...completedPlaceIds.value, placeId]
    }
    currentNodeId.value = placeId
    const stop = baseAlternative.value?.stops.find((s) => s.taskId === id && s.placeId === placeId)
    if (stop) {
      currentTimeSeconds.value = Math.round(stop.finishSeconds)
      virtualClock.value = formatClockSeconds(stop.finishSeconds)
    }
  }

  function reopenTask(id: string): void {
    replanGeneration += 1
    replan.value = null
    completedTaskIds.value = completedTaskIds.value.filter((t) => t !== id)
    skippedTaskIds.value = skippedTaskIds.value.filter((t) => t !== id)
    const remainingPlaces = completedTaskIds.value.flatMap((tid) => {
      const placeId = stopPlaceForTask(tid)
      return placeId ? [placeId] : []
    })
    completedPlaceIds.value = remainingPlaces
    currentNodeId.value = remainingPlaces.at(-1) ?? 'S'
    currentTimeSeconds.value = null
  }
  function skipTask(id: string): void {
    if (!plan.tasks.some((task) => task.id === id) || completedTaskIds.value.includes(id)) return
    replanGeneration += 1
    replan.value = null
    completedTaskIds.value = [...completedTaskIds.value, id]
    skippedTaskIds.value = [...skippedTaskIds.value, id]
  }
  function addCloseEvent(): void {
    if (!closeTarget.value.trim()) {
      error.value = '请选择关店目标地点'
      return
    }
    eventSeq += 1
    events.value = [...events.value, {
      id: `ev-${eventSeq}`, type: 'close_place',
      targetId: closeTarget.value.trim(), delaySeconds: 0,
    }]
    closeTarget.value = ''
  }

  function addDelayEvent(): void {
    if (!delayTarget.value.trim() || !(delayMinutes.value > 0)) {
      error.value = '请填写延误目标与分钟数'
      return
    }
    eventSeq += 1
    events.value = [...events.value, {
      id: `ev-${eventSeq}`, type: 'route_delay',
      targetId: delayTarget.value.trim(), delaySeconds: Math.round(delayMinutes.value * 60),
    }]
    delayTarget.value = ''
  }

  function removeEvent(id: string): void {
    events.value = events.value.filter((e) => e.id !== id)
  }

  function resetExecution(): void {
    replanGeneration += 1
    completedTaskIds.value = []
    skippedTaskIds.value = []
    completedPlaceIds.value = []
    currentNodeId.value = 'S'
    currentTimeSeconds.value = null
    events.value = []
    replan.value = null
    beforeFinish.value = ''
    error.value = ''
    loading.value = false
    virtualClock.value = ''
    selectedAltIndex.value = 0
    closeTarget.value = ''
    delayTarget.value = ''
  }

  async function runReplan(currentTimeClock: string): Promise<void> {
    error.value = ''
    const base = baseAlternative.value
    if (!base || !plan.result) {
      error.value = '请先规划行程'
      return
    }
    const clockSeconds = parseClockToSeconds(currentTimeClock)
    if (clockSeconds == null) {
      error.value = '预演时间请按 18:30 的格式填写'
      return
    }
    // 用户手动改过虚拟时钟则以输入为准；否则用完成任务推进的 stored 时刻。
    const effectiveTimeSeconds = currentTimeClock.trim() === virtualClock.value.trim() && currentTimeSeconds.value != null
      ? currentTimeSeconds.value
      : clockSeconds
    const generation = ++replanGeneration
    beforeFinish.value = formatClockSeconds(base.finishSeconds)
    loading.value = true
    try {
      const result: ReplanResult = await provider.value.createReplan({
        endId: 'H',
        deadlineSeconds: base.deadlineSeconds,
        tasks: plan.tasks.map((t) => ({
          id: t.id,
          options: t.options.map((o) => ({
            placeId: o.placeId,
            serviceSeconds: o.serviceSeconds,
            serviceSourceKind: o.serviceSourceKind,
            windowSourceKind: o.windowSourceKind ?? 'unknown',
            ...(o.window ? { window: o.window }
              : (o.opensSeconds != null && o.closesSeconds != null
                ? { window: { opensSeconds: o.opensSeconds, closesSeconds: o.closesSeconds } }
                : {})),
            ...('windows' in o && Array.isArray((o as { windows?: unknown }).windows)
              ? { windows: (o as { windows: { opensSeconds: number; closesSeconds: number }[] }).windows }
              : {}),
          })),
          required: t.required,
          precedenceIds: plan.taskPredecessors(t.id),
        })),
        travelTimes: plan.travelTimes,
        preference: plan.preference,
        currentNodeId: currentNodeId.value,
        currentTimeSeconds: effectiveTimeSeconds,
        completedTaskIds: completedTaskIds.value,
        events: events.value,
      })
      if (generation !== replanGeneration) return
      replan.value = result
      if (result.status === 'ready' && result.plan.alternatives[0]) {
        await plan.fetchLegGeometries([
          currentNodeId.value,
          ...result.plan.alternatives[0].stops.map((stop) => stop.placeId),
          'H',
        ])
      }
      if (result.status === 'infeasible') {
        error.value = `后续路线暂时无法安排：${Object.keys(result.plan.infeasibleReasons).map(reasonLabel).join('；') || reasonLabel(result.reason)}`
      }
    } catch (err) {
      if (generation !== replanGeneration) return
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      if (generation === replanGeneration) loading.value = false
    }
  }

  return {
    selectedAltIndex, completedTaskIds, skippedTaskIds, completedPlaceIds, currentNodeId,
    currentTimeSeconds, virtualClock, events,
    replan, beforeFinish, loading, error,
    closeTarget, delayTarget, delayMinutes,
    baseAlternative, remainingTasks,
    syncFromPlan, completeTask, skipTask, reopenTask, canComplete, blockReason,
    addCloseEvent, addDelayEvent, removeEvent,
    resetExecution, runReplan, setEventSeq,
  }
})
