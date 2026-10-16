<!-- 今天安排：任务编辑、规划行程、执行与重排合并为单面板。
     取代原 TodayPlanPanel + PlanPage + ExecutionPage 三个跳转页面；
     零路由跳转，「开始执行」只切换面板内部模式。 -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { describeSource, reasonLabel, sourceKindLabel } from '@/domain/sourceExplain'
import { formatClockSeconds, formatDurationSeconds } from '@/domain/time'
import { useExecutionStore } from '@/stores/execution'
import { useMapInteractionStore } from '@/stores/mapInteraction'
import { usePlanStore } from '@/stores/plan'
import { useDialog } from '@/composables/useDialog'
import PlaceSearch from '@/components/PlaceSearch.vue'
import type { PlaceRef } from '@/domain/types'
import { useCommuteStore } from '@/stores/commute'
import { useRoute } from 'vue-router'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (event: 'update:open', value: boolean): void }>()

function close(): void {
  emit('update:open', false)
}

const dialogPanel = ref<HTMLElement | null>(null)
useDialog(computed(() => props.open), dialogPanel, close)

const plan = usePlanStore()
const execution = useExecutionStore()
const mapInteraction = useMapInteractionStore()
const { tasks, result, loading, error, notice, departureClock, deadlineClock, preference } = storeToRefs(plan)
const {
  completedTaskIds, virtualClock, events, replan, beforeFinish, loading: runLoading, error: runError,
} = storeToRefs(execution)

// ---------- 模式 ----------
const mode = ref<'plan' | 'run'>('plan')
function startRun(): void {
  execution.syncFromPlan()
  mode.value = 'run'
}
function backToPlan(): void {
  mode.value = 'plan'
}

// ---------- 方案 ----------
const alternative = computed(() => {
  if (!result.value || result.value.status !== 'ready') return null
  return result.value.alternatives[execution.selectedAltIndex] ?? result.value.alternatives[0] ?? null
})

// 规划成功（含刷新恢复）后取逐段几何，全局地图画单条方案动线。
watch(alternative, (alt) => {
  if (alt) void plan.fetchSelectedGeometries(alt.stops.map((s) => s.placeId))
}, { immediate: true })

function taskServiceMinutes(task: typeof tasks.value[number]): number | '' {
  const services = task.options.map((option) => Math.round(option.serviceSeconds / 60))
  return services.length && services.every((minutes) => minutes === services[0]) ? services[0] : ''
}

function setService(taskId: string, value: string): void {
  if (!value.trim()) {
    plan.error = '请填写停留分钟，填 0 表示不停留'
    return
  }
  const minutes = Number(value)
  if (!Number.isFinite(minutes)) return
  plan.setTaskServiceMinutes(taskId, minutes)
}

// ---------- 高级约束 ----------
const advancedOpen = ref(false)
const manualName = ref('')
const manualMinutes = ref(10)
const manualPlace = ref<PlaceRef | null>(null)
const pickedManualCoord = computed(() => manualPlace.value?.coord)
const commute = useCommuteStore()
const route = useRoute()
function selectManualPlace(place: PlaceRef): void {
  manualPlace.value = place
  manualName.value = place.name
}
watch(() => mapInteraction.selectedFor, target => {
  if (target !== 'manual-plan' || !mapInteraction.selectedPlace) return
  const name = manualName.value.trim()
  selectManualPlace(mapInteraction.selectedPlace)
  if (name) manualName.value = name
})
const awaitingMapPick = ref(false)
function beginManualPick(): void {
  awaitingMapPick.value = true
  mapInteraction.beginPick('manual-plan')
  close()
}
watch(() => mapInteraction.pickTarget, target => {
  if (awaitingMapPick.value && target !== 'manual-plan') {
    awaitingMapPick.value = false
    if (route.name === 'commute') emit('update:open', true)
  }
})

function addManualTask(): void {
  const coord = pickedManualCoord.value
  if (!manualName.value.trim() || !coord) {
    plan.error = '请填写地点名称，并在地图上选择地点'
    return
  }
  if (!Number.isFinite(manualMinutes.value) || manualMinutes.value < 0 || manualMinutes.value > 480) {
    plan.error = '停留时间请填写 0–480 分钟'
    return
  }
  plan.error = ''
  plan.addFixedTask({ ...manualPlace.value, name: manualName.value.trim(), coord, source: manualPlace.value?.source ?? 'user-input' }, manualMinutes.value)
  mapInteraction.clearSelected('manual-plan')
  manualName.value = ''
  manualPlace.value = null
}

function skipTask(task: typeof tasks.value[number]): void {
  if (task.required && !window.confirm(`跳过必去地点「${task.label}」？后续路线将不再经过这里。`)) return
  execution.skipTask(task.id)
  void runReplan()
}

// ---------- 执行模式 ----------
const { closeTarget, delayTarget, delayMinutes } = storeToRefs(execution)
const eventPlaceOptions = computed(() => {
  const options: { id: string; label: string }[] = [
    { id: 'H', label: '到达终点' },
  ]
  for (const task of tasks.value) {
    for (const option of task.options) {
      options.push({ id: option.placeId, label: `${task.label} · ${option.placeName}` })
    }
  }
  return options
})

function taskDone(id: string): boolean {
  return completedTaskIds.value.includes(id)
}

// 行程视图的「下一步」：第一个未办结任务；全部办结则为返程到达终点。
const nextStep = computed(() => {
  if (replan.value?.status === 'infeasible') return null
  const active = execution.baseAlternative
  const stops = active?.stops ?? []
  const stop = stops.find((s) => !completedTaskIds.value.includes(s.taskId))
  if (stop) {
    return {
      title: plan.placeName(stop.placeId),
      time: `${formatClockSeconds(stop.arrivalSeconds)} 到达`,
      hint: `办理 ${formatClockSeconds(stop.startSeconds)}–${formatClockSeconds(stop.finishSeconds)}`,
      done: false,
    }
  }
  const finish = active?.finishSeconds
  return finish != null
    ? { title: '前往终点', time: `${formatClockSeconds(finish)} 到达终点`, hint: '已完成所有地点', done: true }
    : null
})

const replanInfeasible = computed(() =>
  replan.value && replan.value.plan.status === 'infeasible'
    ? Object.entries(replan.value.plan.infeasibleReasons)
    : [])

async function runReplan(): Promise<void> {
  await execution.runReplan(virtualClock.value)
}

// ---------- 来源徽标（紧凑版：title 显示完整解释，不再弹面板） ----------
function sourceTitle(kind: string | null | undefined, value: string): string {
  const detail = describeSource('badge', value, kind)
  return `${detail.source}：${detail.detail}`
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="props.open"
      class="plan-sheet"
      role="dialog"
      aria-modal="true"
      aria-label="今天安排"
      @click.self="close"
    >
      <section
        ref="dialogPanel"
        class="plan-panel plan-sheet__card"
        tabindex="-1"
      >
        <!-- ===== 安排模式 ===== -->
        <template v-if="mode === 'plan'">
          <div class="plan-panel__head">
            <div class="plan-panel__title">
              <span class="plan-panel__eyebrow">今天安排</span>
              <strong>{{ departureClock }} 出发 · 最晚 {{ deadlineClock }} 到达终点</strong>
              <small>{{ tasks.length }}/5 个地点</small>
            </div>
            <button
              type="button"
              class="plan-sheet__close"
              aria-label="关闭今天安排"
              data-dialog-close
              @click="close"
            >
              ✕
            </button>
            <div class="plan-panel__summary">
              <strong v-if="alternative">{{ formatClockSeconds(alternative.finishSeconds) }}</strong>
              <strong v-else>待规划</strong>
              <span v-if="alternative">剩余 {{ formatDurationSeconds(alternative.slackSeconds) }}</span>
              <span v-else>添加要去的地点</span>
            </div>
          </div>

          <p
            v-if="notice"
            class="plan-panel__notice"
          >
            {{ notice }}
          </p>
          <p
            v-if="error"
            class="plan-panel__error"
          >
            {{ error }}
          </p>

          <div
            v-if="tasks.length"
            class="plan-panel__tasks"
          >
            <article
              v-for="task in tasks"
              :key="task.id"
              class="plan-panel__task"
              :class="{ 'plan-panel__task--optional': !task.required }"
            >
              <div class="plan-panel__task-main">
                <span class="plan-panel__task-dot" />
                <div class="plan-panel__task-info">
                  <strong>{{ task.label }}</strong>
                </div>
              </div>
              <label class="plan-panel__service">
                <span>停留</span>
                <input
                  :value="taskServiceMinutes(task)"
                  type="number"
                  min="0"
                  max="480"
                  @change="setService(task.id, ($event.target as HTMLInputElement).value)"
                >
                <span>分</span>
              </label>
              <button
                type="button"
                class="plan-panel__remove"
                :title="task.required ? '移除地点' : '移除可选地点'"
                @click="plan.removeTask(task.id)"
              >
                ×
              </button>
            </article>
          </div>
          <p
            v-else
            class="plan-panel__empty"
          >
            还没有要去的地点
          </p>

          <details
            class="plan-panel__advanced"
            :open="advancedOpen"
            @toggle="advancedOpen = ($event.target as HTMLDetailsElement).open"
          >
            <summary>添加地点</summary>
            <div class="plan-panel__constraints">
              <label>规划偏好
                <select
                  :value="preference"
                  @change="plan.setConstraint('preference', ($event.target as HTMLSelectElement).value)"
                >
                  <option value="fastest">最快完成</option>
                  <option value="least_walk">最少步行</option>
                </select></label>
            </div>
            <div class="plan-panel__manual">
              <PlaceSearch
                :city="commute.city"
                label="搜索任务地点"
                @select="selectManualPlace"
              />
              <input
                v-model="manualName"
                type="text"
                aria-label="任务地点名称"
                placeholder="地点名称"
              >
              <button
                type="button"
                @click="beginManualPick"
              >
                {{ pickedManualCoord ? '重选位置' : '地图选点' }}
              </button>
              <span
                v-if="pickedManualCoord"
                class="plan-panel__picked"
              >{{ manualPlace?.address || manualPlace?.name }}</span>
              <label class="plan-panel__manual-minutes">停留
                <input
                  v-model.number="manualMinutes"
                  type="number"
                  min="0"
                  max="480"
                > 分</label>
              <button
                type="button"
                class="primary"
                :disabled="!manualName.trim() || !pickedManualCoord || tasks.length >= 5"
                @click="addManualTask"
              >
                加入安排
              </button>
            </div>
          </details>

          <div class="plan-panel__actions">
            <button
              type="button"
              class="primary"
              :disabled="loading || !tasks.length"
              @click="plan.runPlan"
            >
              {{ loading ? '规划中…' : alternative ? '重新规划' : '规划行程' }}
            </button>
            <button
              v-if="alternative"
              type="button"
              class="run"
              @click="startRun"
            >
              预演行程
            </button>
          </div>

          <!-- 方案结果 -->
          <article
            v-if="result && result.status === 'ready' && result.alternatives.length > 1"
            class="plan-panel__alts"
          >
            <button
              v-for="(alt, index) in result.alternatives"
              :key="index"
              type="button"
              class="alt-pill"
              :class="{ 'alt-pill--on': execution.selectedAltIndex === index }"
              @click="execution.selectedAltIndex = index"
            >
              方案{{ index + 1 }} · {{ formatClockSeconds(alt.finishSeconds) }}
            </button>
          </article>

          <ol
            v-if="alternative"
            class="plan-panel__timeline"
          >
            <li
              v-for="stop in alternative.stops"
              :key="`${stop.taskId}-${stop.placeId}`"
            >
              <span class="plan-panel__time">{{ formatClockSeconds(stop.startSeconds) }}–{{ formatClockSeconds(stop.finishSeconds) }}</span>
              <strong>{{ plan.placeName(stop.placeId) }}</strong>
              <small>
                {{ formatDurationSeconds(stop.travelSeconds) }} 路程
                <span
                  class="badge"
                  :title="sourceTitle(stop.travelSourceKind, formatDurationSeconds(stop.travelSeconds))"
                >{{ sourceKindLabel(stop.travelSourceKind) }}</span>
                · {{ formatDurationSeconds(stop.finishSeconds - stop.startSeconds) }} 办理
              </small>
            </li>
            <li class="plan-panel__home">
              <span class="plan-panel__time">{{ formatClockSeconds(alternative.finishSeconds) }}</span>
              <strong>到达终点</strong>
              <small>
                返程 {{ formatDurationSeconds(alternative.returnTravelSeconds) }}
                <span
                  class="badge"
                  :title="sourceTitle(alternative.returnTravelSourceKind, formatDurationSeconds(alternative.returnTravelSeconds))"
                >{{ sourceKindLabel(alternative.returnTravelSourceKind) }}</span>
                · 剩余 {{ formatDurationSeconds(alternative.slackSeconds) }}
              </small>
            </li>
          </ol>
          <p
            v-if="result?.warnings?.length"
            class="plan-panel__warning"
          >
            {{ result.warnings.length }} 处营业时间待确认
          </p>
        </template>

        <!-- ===== 执行模式 ===== -->
        <template v-else>
          <div class="plan-panel__head">
            <div class="plan-panel__title">
              <span class="plan-panel__eyebrow">行程预演</span>
              <strong>原计划到达 {{ alternative ? formatClockSeconds(alternative.finishSeconds) : '—' }}</strong>
            </div>
            <div class="plan-panel__head-actions">
              <button
                type="button"
                class="plan-panel__back"
                @click="backToPlan"
              >
                ‹ 调整安排
              </button>
              <button
                type="button"
                class="plan-sheet__close"
                aria-label="关闭今天行程"
                @click="close"
              >
                ✕
              </button>
            </div>
          </div>

          <!-- 下一步大卡：行程进行时的主视觉 -->
          <div
            v-if="nextStep"
            class="plan-sheet__next"
            :class="{ 'plan-sheet__next--done': nextStep.done }"
          >
            <span class="plan-sheet__next-eyebrow">{{ nextStep.done ? '行程收尾' : '下一步' }}</span>
            <strong>{{ nextStep.title }}</strong>
            <small>{{ nextStep.time }} · {{ nextStep.hint }}</small>
          </div>

          <label class="plan-panel__clock">
            预演时间
            <input
              v-model="virtualClock"
              type="text"
              placeholder="例如 18:30"
            >
          </label>
          <p
            v-if="runError"
            class="plan-panel__error"
            role="alert"
          >
            {{ runError }}
          </p>

          <ol class="plan-panel__runlist">
            <li
              v-for="task in tasks"
              :key="task.id"
              :class="{ 'is-done': taskDone(task.id) }"
            >
              <span class="plan-panel__rundot">{{ taskDone(task.id) ? '✓' : '•' }}</span>
              <div class="plan-panel__runmain">
                <strong>{{ task.label }}</strong>
                <small v-if="taskDone(task.id)">{{ execution.skippedTaskIds.includes(task.id) ? '已跳过' : '已完成' }}</small>
                <small v-else-if="execution.blockReason(task.id)">{{ execution.blockReason(task.id) }}</small>
                <small v-else>待完成</small>
              </div>
              <div
                v-if="!taskDone(task.id)"
                class="plan-panel__runbtns"
              >
                <button
                  type="button"
                  :disabled="!execution.canComplete(task.id)"
                  @click="execution.completeTask(task.id)"
                >
                  完成
                </button>
                <button
                  type="button"
                  @click="skipTask(task)"
                >
                  跳过
                </button>
              </div>
              <button
                v-else
                type="button"
                class="plan-panel__reopen"
                @click="execution.reopenTask(task.id)"
              >
                恢复
              </button>
            </li>
          </ol>

          <details class="plan-panel__events">
            <summary>模拟事件</summary>
            <div class="plan-panel__event-row">
              <select
                v-model="closeTarget"
                aria-label="选择关店目标"
              >
                <option
                  value=""
                  disabled
                >
                  选择要模拟关店的地点
                </option>
                <option
                  v-for="option in eventPlaceOptions"
                  :key="option.id"
                  :value="option.id"
                >
                  {{ option.label }}
                </option>
              </select>
              <button
                type="button"
                :disabled="!closeTarget"
                @click="execution.addCloseEvent()"
              >
                模拟关店
              </button>
            </div>
            <div class="plan-panel__event-row">
              <select
                v-model="delayTarget"
                aria-label="选择延误目标"
              >
                <option
                  value=""
                  disabled
                >
                  选择延误地点
                </option>
                <option
                  v-for="option in eventPlaceOptions"
                  :key="option.id"
                  :value="option.id"
                >
                  {{ option.label }}
                </option>
              </select>
              <input
                v-model.number="delayMinutes"
                type="number"
                min="1"
                class="plan-panel__delay-min"
                aria-label="延误时间（分钟）"
              > 分
              <button
                type="button"
                :disabled="!delayTarget"
                @click="execution.addDelayEvent()"
              >
                模拟延误
              </button>
            </div>
            <ul
              v-if="events.length"
              class="plan-panel__event-list"
            >
              <li
                v-for="event in events"
                :key="event.id"
              >
                {{ event.type === 'close_place' ? '关店' : '延误' }} · {{ plan.placeName(event.targetId) }}
                <button
                  type="button"
                  :aria-label="`移除${event.type === 'close_place' ? '关店' : '延误'}事件`"
                  @click="execution.removeEvent(event.id)"
                >
                  ×
                </button>
              </li>
            </ul>
          </details>

          <div class="plan-panel__actions">
            <button
              type="button"
              class="primary"
              :disabled="runLoading"
              @click="runReplan"
            >
              {{ runLoading ? '更新中…' : '更新后续路线' }}
            </button>
          </div>

          <p
            v-if="beforeFinish"
            class="plan-panel__diff"
          >
            原计划到达 {{ beforeFinish }}
            <template v-if="replan">
              → 更新后到达
              <template v-if="replan.status === 'ready' && replan.plan.alternatives[0]">
                {{ formatClockSeconds(replan.plan.alternatives[0].finishSeconds) }}
              </template>
              <template v-else-if="replanInfeasible.length">
                暂时无法安排：{{ replanInfeasible.map(([k]) => reasonLabel(k)).join('；') }}
              </template>
            </template>
          </p>
          <ol
            v-if="replan && replan.status === 'ready' && replan.plan.alternatives[0]"
            class="plan-panel__timeline"
          >
            <li
              v-for="stop in replan.plan.alternatives[0].stops"
              :key="`${stop.taskId}-${stop.placeId}-run`"
            >
              <span class="plan-panel__time">{{ formatClockSeconds(stop.startSeconds) }}–{{ formatClockSeconds(stop.finishSeconds) }}</span>
              <strong>{{ plan.placeName(stop.placeId) }}</strong>
            </li>
            <li class="plan-panel__home">
              <span class="plan-panel__time">{{ formatClockSeconds(replan.plan.alternatives[0].finishSeconds) }}</span>
              <strong>到达终点</strong>
            </li>
          </ol>
        </template>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.plan-sheet {
  position: fixed;
  inset: 0;
  z-index: 70;
  background: rgb(15 23 42 / 55%);
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.plan-sheet__card {
  width: min(480px, 100%);
  max-height: 88dvh;
  padding-bottom: max(.8rem, env(safe-area-inset-bottom));
  overscroll-behavior: contain;
  overflow-y: auto;
  border-radius: 1.1rem 1.1rem 0 0;
  box-shadow: 0 -10px 40px rgb(15 23 42 / 30%);
}

.plan-sheet__close {
  flex: none;
  border: 1px solid #cbd5e1;
  border-radius: 0.45rem;
  background: #fff;
  color: #64748b;
  font-size: 0.8rem;
  width: 1.8rem;
  height: 1.8rem;
  line-height: 1;
}

.plan-panel__head-actions {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.plan-sheet__next {
  display: grid;
  gap: 0.15rem;
  border: 1px solid #bfdbfe;
  border-radius: 0.8rem;
  background: linear-gradient(135deg, #eff6ff, #fff);
  padding: 0.7rem 0.85rem;
}

.plan-sheet__next--done {
  border-color: #a7f3d0;
  background: linear-gradient(135deg, #ecfdf5, #fff);
}

.plan-sheet__next-eyebrow {
  font-size: 0.65rem;
  font-weight: 800;
  color: #2563eb;
  letter-spacing: 0.05em;
}

.plan-sheet__next--done .plan-sheet__next-eyebrow {
  color: #047857;
}

.plan-sheet__next strong {
  font-size: 1.05rem;
  color: #0f172a;
}

.plan-sheet__next small {
  color: #64748b;
  font-size: 0.72rem;
}

.plan-panel {
  display: grid;
  gap: 0.6rem;
  border: 1px solid #dbeafe;
  border-radius: 0.9rem;
  padding: 0.8rem;
  background: linear-gradient(135deg, #eff6ff, #ffffff 74%);
  box-shadow: 0 2px 10px rgb(15 23 42 / 4%);
}

.plan-panel__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.6rem;
}

.plan-panel__title {
  display: grid;
  gap: 0.1rem;
  min-width: 0;
}

.plan-panel__eyebrow {
  color: #2563eb;
  font-size: 0.65rem;
  font-weight: 700;
}

.plan-panel__title strong {
  font-size: 0.85rem;
  color: #0f172a;
}

.plan-panel__title small {
  color: #64748b;
  font-size: 0.68rem;
}

.plan-panel__summary {
  display: grid;
  gap: 0.15rem;
  min-width: 5.4rem;
  padding: 0.4rem 0.55rem;
  border: 1px solid #bfdbfe;
  border-radius: 0.55rem;
  background: rgb(255 255 255 / 82%);
  text-align: right;
}

.plan-panel__summary strong {
  color: #0f172a;
  font-size: 0.95rem;
}

.plan-panel__summary span {
  color: #64748b;
  font-size: 0.62rem;
}

.plan-panel__notice,
.plan-panel__error,
.plan-panel__empty,
.plan-panel__warning,
.plan-panel__diff {
  margin: 0;
  font-size: 0.72rem;
  line-height: 1.4;
}

.plan-panel__notice { color: #2563eb; }
.plan-panel__error { color: #b91c1c; }
.plan-panel__empty { color: #64748b; padding: 0.35rem 0; }
.plan-panel__warning { color: #92400e; }
.plan-panel__diff { color: #0f172a; font-weight: 600; }

.plan-panel__tasks {
  display: grid;
  gap: 0.35rem;
}

.plan-panel__task {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 0.45rem;
  align-items: center;
  padding: 0.45rem 0.5rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.55rem;
  background: rgb(255 255 255 / 86%);
}

.plan-panel__task--optional {
  border-style: dashed;
}

.plan-panel__task-main {
  display: flex;
  gap: 0.4rem;
  align-items: flex-start;
  min-width: 0;
}

.plan-panel__task-dot {
  width: 0.45rem;
  height: 0.45rem;
  flex: none;
  margin-top: 0.25rem;
  border-radius: 999px;
  background: #2563eb;
}

.plan-panel__task--optional .plan-panel__task-dot {
  background: #94a3b8;
}

.plan-panel__task-info {
  min-width: 0;
}

.plan-panel__task-info strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.75rem;
}

.plan-panel__service {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  color: #64748b;
  font-size: 0.62rem;
}

.plan-panel__service input,
.plan-panel__manual-minutes input {
  width: 2.8rem;
  padding: 0.2rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.3rem;
  text-align: center;
  font-size: 0.7rem;
}

.plan-panel__remove,
.plan-panel__reopen {
  border: 0;
  background: transparent;
  color: #94a3b8;
  padding: 0.1rem 0.25rem;
  font-size: 0.95rem;
}

.plan-panel__reopen {
  color: #2563eb;
  font-size: 0.7rem;
}

.plan-panel__advanced {
  border: 1px dashed #cbd5e1;
  border-radius: 0.55rem;
  padding: 0.4rem 0.55rem;
  font-size: 0.72rem;
}

.plan-panel__advanced summary {
  cursor: pointer;
  color: #475569;
  font-weight: 600;
}

.plan-panel__constraints {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  margin-top: 0.45rem;
}

.plan-panel__constraints label {
  display: grid;
  gap: 0.15rem;
  font-size: 0.65rem;
  color: #64748b;
}

.plan-panel__constraints input,
.plan-panel__constraints select {
  font-size: 0.72rem;
  padding: 0.25rem 0.35rem;
}

.plan-panel__manual {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.5rem;
}
.plan-panel__manual > .place-search{width:100%}
.plan-panel__manual > input,.plan-panel__manual > button{min-height:44px}

.plan-panel__manual input[type="text"] {
  flex: 1;
  min-width: 6rem;
  font-size: 0.72rem;
  padding: 0.28rem 0.4rem;
}

.plan-panel__picked {
  font-size: 0.62rem;
  color: #047857;
}

.plan-panel__manual-minutes {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  font-size: 0.65rem;
  color: #64748b;
}

.plan-panel__actions {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.plan-panel__actions .primary {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
  font-weight: 700;
  font-size: 0.78rem;
  padding: 0.45rem 0.8rem;
}

.plan-panel__actions .run {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #047857;
  font-weight: 700;
  font-size: 0.78rem;
  padding: 0.45rem 0.8rem;
  margin-left: auto;
}

.plan-panel__back {
  border: 1px solid #cbd5e1;
  border-radius: 0.45rem;
  background: #fff;
  color: #475569;
  font-size: 0.72rem;
  padding: 0.3rem 0.55rem;
}

.plan-panel__alts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.alt-pill {
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  background: #fff;
  color: #475569;
  font-size: 0.7rem;
  padding: 0.22rem 0.55rem;
}

.alt-pill--on {
  border-color: #2563eb;
  background: #dbeafe;
  color: #1d4ed8;
  font-weight: 700;
}

.plan-panel__timeline {
  display: grid;
  gap: 0.3rem;
  margin: 0;
  padding: 0.35rem 0 0.1rem 0.9rem;
  border-top: 1px solid #dbeafe;
}

.plan-panel__timeline li {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  column-gap: 0.45rem;
  row-gap: 0.05rem;
  font-size: 0.7rem;
}

.plan-panel__time {
  color: #2563eb;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.plan-panel__timeline strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plan-panel__timeline small {
  grid-column: 2;
  color: #64748b;
  font-size: 0.62rem;
}

.plan-panel__home .plan-panel__time {
  color: #047857;
}

.plan-panel__clock {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.72rem;
  color: #475569;
}

.plan-panel__clock input {
  width: 5rem;
  font-size: 0.78rem;
  padding: 0.28rem 0.4rem;
}

.plan-panel__runlist {
  display: grid;
  gap: 0.3rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.plan-panel__runlist li {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.4rem 0.45rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  background: #fff;
  font-size: 0.75rem;
}

.plan-panel__runlist li.is-done {
  opacity: 0.6;
}

.plan-panel__rundot {
  color: #2563eb;
  font-weight: 700;
}

.plan-panel__runmain {
  flex: 1;
  min-width: 0;
}

.plan-panel__runmain small {
  display: block;
  color: #64748b;
  font-size: 0.62rem;
}

.plan-panel__runbtns {
  display: flex;
  gap: 0.3rem;
}

.plan-panel__runbtns button,
.plan-panel__event-row button {
  font-size: 0.68rem;
  padding: 0.25rem 0.5rem;
}

.plan-panel__events {
  border: 1px dashed #fde68a;
  background: #fffbeb;
  border-radius: 0.55rem;
  padding: 0.4rem 0.55rem;
  font-size: 0.7rem;
}

.plan-panel__events summary {
  cursor: pointer;
  color: #92400e;
  font-weight: 600;
}

.plan-panel__event-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.4rem;
  flex-wrap: wrap;
}

.plan-panel__event-row select {
  flex: 1;
  min-width: 8rem;
  font-size: 0.7rem;
  padding: 0.25rem 0.3rem;
}

.plan-panel__delay-min {
  width: 2.8rem;
  text-align: center;
  font-size: 0.7rem;
  padding: 0.25rem;
}

.plan-panel__event-list {
  margin: 0.4rem 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 0.2rem;
  color: #78350f;
  font-size: 0.66rem;
}

.plan-panel__event-list button {
  border: 0;
  background: transparent;
  color: #b45309;
  font-size: 0.75rem;
  padding: 0 0.2rem;
}

.badge {
  border-radius: 999px;
  font-size: 0.6rem;
  padding: 0.05rem 0.35rem;
  font-weight: 600;
  background: var(--color-accent-weak, #dbeafe);
  color: var(--color-accent-strong, #1d4ed8);
  cursor: help;
  white-space: nowrap;
}
</style>
