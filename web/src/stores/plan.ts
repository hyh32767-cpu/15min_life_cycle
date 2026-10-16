import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import { resolveOpeningWindows } from '@/domain/openingHours'
import { reasonLabel } from '@/domain/sourceExplain'
import { parseClockToSeconds } from '@/domain/time'
import type {
  NamedCoord,
  PlanOptionDraft,
  PlanResult,
  PlanTravelTime,
  PlaceRef,
} from '@/domain/types'
import { useAppStore } from './app'
import { useCommuteStore } from './commute'

export interface PlanTaskDraft {
  id: string
  label: string
  options: PlanOptionDraft[]
  required: boolean
  precedenceIds: string[]
  category?: string
}

let taskSeq = 0

function nextTaskId(): string {
  taskSeq += 1
  return `task-${taskSeq}`
}

function setTaskSeq(next: number): void {
  if (Number.isFinite(next) && next > taskSeq) taskSeq = Math.floor(next)
}

export const usePlanStore = defineStore('plan', () => {
  const app = useAppStore()
  const commute = useCommuteStore()

  const tasks = ref<PlanTaskDraft[]>([])
  const visitOrder = ref<string[]>([])
  const timeLimitSeconds = ref<number | null>(null)
  watch(() => [commute.company,commute.home,commute.departureClock,commute.deadlineClock], () => { timeLimitSeconds.value = null }, {flush:'sync'})
  function taskPredecessors(id: string): string[] {
    const task = tasks.value.find(task => task.id === id)
    const ordered = visitOrder.value.filter(taskId => tasks.value.some(task => task.id === taskId))
    const position = ordered.indexOf(id)
    return [...new Set([...(task?.precedenceIds ?? []), ...(position > 0 ? [ordered[position - 1]!] : [])])]
  }

  function setVisitOrder(ids: string[]): void {
    if (ids.length !== tasks.value.length || new Set(ids).size !== ids.length || ids.some(id => !tasks.value.some(task => task.id === id))) {
      error.value = '途经点已变化，请重新调整顺序'
      return
    }
    visitOrder.value = [...ids]
    const byId = new Map(tasks.value.map(task => [task.id, task]))
    tasks.value = ids.map(id => byId.get(id)!)
    invalidatePlan('途经点顺序已修改')
  }
  const departureClock = computed({
    get: () => commute.departureClock,
    set: (value: string) => { commute.departureClock = value },
  })
  const deadlineClock = computed({
    get: () => commute.deadlineClock,
    set: (value: string) => { commute.deadlineClock = value },
  })
  const preference = ref<'fastest' | 'least_walk'>('fastest')
  const result = ref<PlanResult | null>(null)
  const travelTimes = ref<PlanTravelTime[]>([])
  const nodeCoords = ref<Record<string, NamedCoord>>({})
  const legGeometries = ref<Record<string, NamedCoord[]>>({})
  // 方案动线（S→各停站→H 按序拼接的单条折线）；方案失效时与 legGeometries 一起清空。
  const planRouteGeometry = ref<NamedCoord[]>([])
  const geometryLoading = ref(false)
  let geometryGeneration = 0
  const loading = ref(false)
  const error = ref('')
  const notice = ref('')
  // F51：规划请求 generation；在途旧响应不得覆盖新约束结果。
  let planGeneration = 0
  const nodePlaceNames = ref<Record<string, string>>({})

  const provider = computed(() => app.provider)

  type WindowedPlace = PlaceRef & {
    opensSeconds?: number
    closesSeconds?: number
    windows?: { opensSeconds: number; closesSeconds: number }[]
    windowSource?: 'structured' | 'text'
  }

  // F35：窗口来源跟随 POI 自身来源；live-api 只给实时，其余按 place.source 诚实标注。
  function windowSourceKind(place: PlaceRef, hasWindow: boolean): string {
    if (!hasWindow) return 'unknown'
    if (place.source === 'live-api' || place.source === 'api-cache') return place.source
    return 'unknown'
  }

  function addFixedTask(place: WindowedPlace, serviceMinutes: number): string {
    if (!Number.isFinite(serviceMinutes) || serviceMinutes < 0 || serviceMinutes > 480) {
      throw new Error('停留时间请填写 0–480 分钟')
    }
    const id = nextTaskId()
    const entry = place.naviCoord ?? place.coord
    const placeId = place.uid ?? `${place.name}-${entry.lng.toFixed(5)},${entry.lat.toFixed(5)}`
    const windows = place.windows?.length
      ? place.windows
      : (place.opensSeconds != null && place.closesSeconds != null
        ? [{ opensSeconds: place.opensSeconds, closesSeconds: place.closesSeconds }]
        : [])
    const hasWindow = windows.length > 0
    tasks.value = [...tasks.value, {
      id,
      label: place.name,
      options: [{
        placeId,
        placeName: place.name,
        coord: entry,
        serviceSeconds: Math.max(0, Math.round(serviceMinutes * 60)),
        serviceSourceKind: 'user-input',
        windowSourceKind: windowSourceKind(place, hasWindow),
        ...(windows[0] ? { opensSeconds: windows[0].opensSeconds, closesSeconds: windows[0].closesSeconds } : {}),
        ...(windows[0] ? { window: { opensSeconds: windows[0].opensSeconds, closesSeconds: windows[0].closesSeconds } } : {}),
        ...(windows.length > 1 ? { windows } : {}),
      }],
      required: true,
      precedenceIds: [],
    }]
    if (visitOrder.value.length) visitOrder.value = [...visitOrder.value, id]
    if (entry) nodeCoords.value = { ...nodeCoords.value, [placeId]: entry }
    nodePlaceNames.value = { ...nodePlaceNames.value, [placeId]: place.name }
    invalidatePlan('地点已添加')
    notice.value = `已加入：${place.name}`
    return id
  }

  function addFlexibleTask(category: string, candidates: WindowedPlace[], serviceMinutes: number): string {
    if (!Number.isFinite(serviceMinutes) || serviceMinutes < 0 || serviceMinutes > 480) {
      throw new Error('停留时间请填写 0–480 分钟')
    }
    const id = nextTaskId()
    const picks = candidates.slice(0, 3)
    const coords: Record<string, NamedCoord> = {}
    const names: Record<string, string> = {}
    const options = picks.map((place) => {
      const entry = place.naviCoord ?? place.coord
      const placeId = place.uid ?? `${place.name}-${entry.lng.toFixed(5)},${entry.lat.toFixed(5)}`
      if (entry) coords[placeId] = entry
      names[placeId] = place.name
      const windows = place.windows?.length
        ? place.windows
        : (place.opensSeconds != null && place.closesSeconds != null
          ? [{ opensSeconds: place.opensSeconds, closesSeconds: place.closesSeconds }]
          : [])
      const hasWindow = windows.length > 0
      return {
        placeId,
        placeName: place.name,
        coord: entry,
        serviceSeconds: Math.max(0, Math.round(serviceMinutes * 60)),
        serviceSourceKind: 'user-input' as const,
        windowSourceKind: windowSourceKind(place, hasWindow),
        ...(windows[0] ? { opensSeconds: windows[0].opensSeconds, closesSeconds: windows[0].closesSeconds } : {}),
        ...(windows[0] ? { window: { opensSeconds: windows[0].opensSeconds, closesSeconds: windows[0].closesSeconds } } : {}),
        ...(windows.length > 1 ? { windows } : {}),
      }
    })
    tasks.value = [...tasks.value, {
      id, label: `${category}（任选）`, options, required: true, precedenceIds: [], category,
    }]
    nodeCoords.value = { ...nodeCoords.value, ...coords }
    nodePlaceNames.value = { ...nodePlaceNames.value, ...names }
    invalidatePlan('地点已添加')
    notice.value = `已加入${category}（任选 ${options.length} 家）`
    return id
  }

  function importFromCommute(index: number, mode: 'fixed' | 'flexible'): string | null {
    const ranked = commute.rankedPois[index]
    if (!ranked) return null
    const serviceMinutes = commute.stayMinutes
    const attachWindows = (
      place: PlaceRef,
    ): PlaceRef & { opensSeconds?: number; closesSeconds?: number; windows?: { opensSeconds: number; closesSeconds: number }[] } => {
      const resolved = resolveOpeningWindows(place.structuredHours, place.shopHours)
      if (!resolved.windows.length) return place
      const primary = resolved.windows[0]
      if (resolved.source === 'structured') notice.value = `已带入营业时间：${place.name}`
      return {
        ...place,
        opensSeconds: primary.opensSeconds,
        closesSeconds: primary.closesSeconds,
        windows: resolved.windows.map((w) => ({ opensSeconds: w.opensSeconds, closesSeconds: w.closesSeconds })),
      }
    }
    if (mode === 'fixed') {
      return addFixedTask(attachWindows(ranked.place), serviceMinutes)
    }
    const candidates = commute.rankedPois
      .filter((item: { feasible: boolean }) => item.feasible)
      .slice(0, 3)
      .map((item: { place: PlaceRef }) => attachWindows(item.place))
    const list = candidates.length ? candidates : [attachWindows(ranked.place)]
    return addFlexibleTask(commute.category || '同类', list, serviceMinutes)
  }

  function removeTask(id: string): void {
    visitOrder.value = visitOrder.value.filter(taskId => taskId !== id)
    tasks.value = tasks.value.filter((task) => task.id !== id)
    tasks.value = tasks.value.map((task) => ({
      ...task,
      precedenceIds: task.precedenceIds.filter((dep) => dep !== id),
    }))
    invalidatePlan('地点已修改')
  }

  function replaceFixedTask(id: string, place: WindowedPlace, minutes: number): void {
    const previous = tasks.value.find(task => task.id === id)
    if (!previous) return
    const order = [...visitOrder.value]
    const newId = addFixedTask(place, minutes)
    const created = tasks.value.find(task => task.id === newId)!
    tasks.value = tasks.value.filter(task => task.id !== newId).map(task => task.id === id
      ? { ...created, id, required: previous.required, precedenceIds: previous.precedenceIds } : task)
    visitOrder.value = order
    invalidatePlan('途经点已更换')
  }

  // F33/F51：任何影响约束的编辑都使旧方案失效，并递增 generation 让在途旧响应失效。
  function invalidatePlan(reason: string): void {
    const activePlaces = new Set(['S', 'H', ...tasks.value.flatMap(task => task.options.map(option => option.placeId))])
    nodeCoords.value = Object.fromEntries(Object.entries(nodeCoords.value).filter(([id]) => activePlaces.has(id)))
    nodePlaceNames.value = Object.fromEntries(Object.entries(nodePlaceNames.value).filter(([id]) => activePlaces.has(id)))
    planGeneration += 1
    loading.value = false
    geometryGeneration += 1
    legGeometries.value = {}
    planRouteGeometry.value = []
    geometryLoading.value = false
    if (result.value !== null) {
      result.value = null
      notice.value = `${reason}，请重新规划`
    }
  }

  function setRequired(id: string, required: boolean): void {
    tasks.value = tasks.value.map((task) => task.id === id ? { ...task, required } : task)
    invalidatePlan('安排已修改')
  }

  function setConstraint(clock: 'departure' | 'deadline' | 'preference', value: string): void {
    if (clock === 'departure') departureClock.value = value
    else if (clock === 'deadline') deadlineClock.value = value
    else preference.value = value as 'fastest' | 'least_walk'
    planGeneration += 1
    invalidatePlan('时间或目标已修改')
  }

  function setServiceMinutes(id: string, optionIndex: number, minutes: number): void {
    // F38：PlanPage 用 Number(...) 传入，清空/非法文本时为 NaN；此处再守一次，不让 NaN 进入 serviceSeconds。
    if (!Number.isFinite(minutes) || minutes < 0 || minutes > 480) {
      error.value = '停留时间请填写 0–480 分钟'
      return
    }
    tasks.value = tasks.value.map((task) => {
      if (task.id !== id) return task
      return {
        ...task,
        options: task.options.map((option, index) => index === optionIndex
          ? { ...option, serviceSeconds: Math.max(0, Math.round(minutes * 60)), serviceSourceKind: 'user-input' as const }
          : option),
      }
    })
    invalidatePlan('停留时间已修改')
  }

  function setTaskServiceMinutes(id: string, minutes: number): void {
    if (!Number.isFinite(minutes) || minutes < 0 || minutes > 480) {
      error.value = '停留时间请填写 0–480 分钟'
      return
    }
    const serviceSeconds = Math.max(0, Math.round(minutes * 60))
    tasks.value = tasks.value.map((task) => task.id === id
      ? {
          ...task,
          options: task.options.map((option) => ({
            ...option,
            serviceSeconds,
            serviceSourceKind: 'user-input' as const,
          })),
        }
      : task)
    invalidatePlan('停留时间已修改')
  }

  function togglePrecedence(id: string, depId: string): void {
    if (id === depId) return
    tasks.value = tasks.value.map((task) => {
      if (task.id !== id) return task
      const has = task.precedenceIds.includes(depId)
      return {
        ...task,
        precedenceIds: has
          ? task.precedenceIds.filter((dep) => dep !== depId)
          : [...task.precedenceIds, depId],
      }
    })
    invalidatePlan('先后顺序已修改')
  }

  function placeName(placeId: string): string {
    return nodePlaceNames.value[placeId] ?? placeId
  }

  async function buildTravelTimes(
    startCoord: NamedCoord, endCoord: NamedCoord,
  ): Promise<{ cells: PlanTravelTime[]; startId: string; endId: string }> {
    const startId = 'S'
    const endId = 'H'
    const placeIds = [...new Set(tasks.value.flatMap((task) => task.options.map((o) => o.placeId)))]
    const coords: Record<string, NamedCoord> = { [startId]: startCoord, [endId]: endCoord }
    for (const task of tasks.value) {
      for (const option of task.options) {
        if (option.coord) coords[option.placeId] = option.coord
        else if (nodeCoords.value[option.placeId]) coords[option.placeId] = nodeCoords.value[option.placeId]
      }
    }
    const nodeIds = [startId, ...placeIds, endId]
    const originIds = nodeIds.filter((id) => coords[id])
    // Query full originIds x originIds matrix in one call; provider handles batching.
    const matrix = await provider.value.getTravelMatrix(
      originIds.map((id) => coords[id]),
      originIds.map((id) => coords[id]),
    )
    const lookup: Record<string, { duration: number | null; distance: number | null; source: string; error: boolean }> = {}
    for (const cell of matrix.cells) {
      const from = originIds[cell.fromIndex]
      const to = originIds[cell.toIndex]
      if (from == null || to == null) continue
      lookup[`${from}->${to}`] = {
        duration: cell.durationSeconds,
        distance: cell.distanceM,
        source: cell.sourceKind,
        // T212：透传矩阵 error（缺测/上游失败），不降级为 no_route；规划层据此报 OD_UNAVAILABLE。
        error: cell.status === 'error',
      }
    }
    const cells: PlanTravelTime[] = []
    for (const from of nodeIds) {
      for (const to of nodeIds) {
        if (from === to) continue
        const hit = lookup[`${from}->${to}`]
        cells.push({
          fromId: from,
          toId: to,
          durationSeconds: hit?.duration ?? null,
          distanceM: hit?.distance ?? null,
          status: hit ? (hit.duration != null ? 'ok' : (hit.error ? 'error' : 'no_route')) : 'error',
          sourceKind: (hit?.source as PlanTravelTime['sourceKind']) ?? 'derived',
        })
      }
    }
    return { cells, startId, endId }
  }

  async function runPlan(): Promise<void> {
    error.value = ''
    notice.value = ''
    result.value = null
    if (tasks.value.length < 1 || tasks.value.length > 5) {
      error.value = '请添加 1–5 个要去的地点'
      return
    }
    for (const task of tasks.value) {
      if (!task.options.length || task.options.length > 3) {
        error.value = `请为「${task.label}」选择 1–3 个地点`
        return
      }
    }
    const departureSeconds = parseClockToSeconds(departureClock.value)
    const configuredDeadline = parseClockToSeconds(deadlineClock.value)
    const deadlineSeconds = configuredDeadline == null ? null : Math.min(configuredDeadline, timeLimitSeconds.value ?? Infinity)
    if (departureSeconds == null || deadlineSeconds == null || deadlineSeconds <= departureSeconds) {
      error.value = '截止时间必须晚于出发时间'
      return
    }
    if (!commute.company || !commute.home) {
      error.value = '请先确认起点与终点，再规划行程'
      return
    }
    const generation = ++planGeneration
    // F71：请求开始冻结输入快照；矩阵与规划请求都用快照，不读中途被编辑的 live 状态。
    const frozenTasks = tasks.value.map((task) => ({
      ...task,
      options: task.options.map((o) => ({ ...o })),
      precedenceIds: taskPredecessors(task.id),
    }))
    const frozenCompany = commute.company
    const frozenHome = commute.home
    const frozenPreference = preference.value
    loading.value = true
    try {
      const { cells, startId, endId } = await buildTravelTimes(
        frozenCompany.naviCoord ?? frozenCompany.coord,
        frozenHome.naviCoord ?? frozenHome.coord)
      if (generation !== planGeneration) return
      travelTimes.value = cells
      const plan = await provider.value.createPlan({
        startId,
        endId,
        departureSeconds,
        deadlineSeconds,
        tasks: frozenTasks.map((task) => ({
          id: task.id,
          options: task.options.map((o) => ({
            placeId: o.placeId,
            serviceSeconds: o.serviceSeconds,
            serviceSourceKind: o.serviceSourceKind,
            windowSourceKind: o.windowSourceKind ?? 'unknown',
            ...(o.window ? { window: o.window }
              : (o.opensSeconds != null && o.closesSeconds != null
                ? { window: { opensSeconds: o.opensSeconds, closesSeconds: o.closesSeconds } }
                : {})),
            ...('windows' in o && Array.isArray(o.windows)
              ? { windows: o.windows.map((w) => ({ opensSeconds: w.opensSeconds, closesSeconds: w.closesSeconds })) }
              : {}),
          })),
          required: task.required,
          precedenceIds: task.precedenceIds,
        })),
        travelTimes: cells,
        preference: frozenPreference,
        maxAlternatives: 3,
      })
      if (generation !== planGeneration) return
      result.value = plan
      if (plan.status === 'infeasible') {
        error.value = `暂时无法安排：${Object.keys(plan.infeasibleReasons).map(reasonLabel).join('；') || '请调整地点或时间'}`
      }
    } catch (err) {
      if (generation !== planGeneration) return
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      if (generation === planGeneration) loading.value = false
    }
  }

  async function fetchLegGeometries(nodeIds: string[]): Promise<void> {
    const generation = ++geometryGeneration
    const coords = { ...nodeCoords.value }
    geometryLoading.value = true
    try {
      const next: Record<string, NamedCoord[]> = {}
      // 方案动线按访问顺序拼接成一条连续折线（衔接点去重）：
      // 百度步行 API 不支持途经点，只能分段实测后拼接，地图上呈现为单线。
      const merged: NamedCoord[] = []
      for (let i = 0; i + 1 < nodeIds.length; i += 1) {
        const from = coords[nodeIds[i]]
        const to = coords[nodeIds[i + 1]]
        if (!from || !to) throw new Error('部分地点缺少位置，路线暂不可用')
        try {
          const leg = await provider.value.getWalkingRoute(from, to)
          next[`${nodeIds[i]}->${nodeIds[i + 1]}`] = leg.route.geometry
          const geometry = leg.route.geometry
          if (geometry.length >= 2) {
            const last = merged[merged.length - 1]
            const drop = merged.length && last && geometry[0]
              && last.lng === geometry[0].lng && last.lat === geometry[0].lat ? 1 : 0
            merged.push(...geometry.slice(drop))
          }
        } catch {
          throw new Error('部分路线未能加载，请重试')
        }
      }
      if (generation !== geometryGeneration) return
      legGeometries.value = next
      planRouteGeometry.value = merged.length >= 2 ? merged : []
    } catch (err) {
      if (generation !== geometryGeneration) return
      legGeometries.value = {}
      planRouteGeometry.value = []
      notice.value = err instanceof Error ? err.message : '路线暂不可用'
    } finally {
      if (generation === geometryGeneration) geometryLoading.value = false
    }
  }

  async function fetchSelectedGeometries(stopPlaceIds: string[]): Promise<void> {
    const company = commute.company
    const home = commute.home
    if (!company || !home) return
    const coords = { ...nodeCoords.value, S: company.naviCoord ?? company.coord, H: home.naviCoord ?? home.coord }
    nodeCoords.value = coords
    await fetchLegGeometries(['S', ...stopPlaceIds, 'H'])
  }

  function resetState(): void {
    // 复位必须使所有在途 live 请求失效，不能让旧响应重新写入空计划。
    planGeneration += 1
    geometryGeneration += 1
    tasks.value = []
    timeLimitSeconds.value = null
    visitOrder.value = []
    result.value = null
    travelTimes.value = []
    nodeCoords.value = {}
    legGeometries.value = {}
    planRouteGeometry.value = []
    geometryLoading.value = false
    loading.value = false
    error.value = ''
    notice.value = ''
    nodePlaceNames.value = {}
  }

  return {
    tasks, departureClock, deadlineClock, preference, timeLimitSeconds,
    result, travelTimes, nodeCoords, nodePlaceNames,
    legGeometries, planRouteGeometry, geometryLoading,
    loading, error, notice,
    addFixedTask, addFlexibleTask, importFromCommute, visitOrder, setVisitOrder, replaceFixedTask, taskPredecessors,
    removeTask, setRequired, setServiceMinutes, setTaskServiceMinutes, setConstraint, togglePrecedence,
    placeName, runPlan, fetchSelectedGeometries, fetchLegGeometries, resetState, setTaskSeq, invalidatePlan,
  }
})
