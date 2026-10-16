<script setup lang="ts">
import { computed, onDeactivated, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { formatClockSeconds, formatDurationSeconds, parseClockToSeconds } from '@/domain/time'
import { reasonLabel } from '@/domain/sourceExplain'
import type { PlaceRef } from '@/domain/types'
import { useCommuteStore } from '@/stores/commute'
import { usePlanStore } from '@/stores/plan'
import { usePlacesStore } from '@/stores/places'
import { useMapInteractionStore } from '@/stores/mapInteraction'
import { useExecutionStore } from '@/stores/execution'
import PlaceSearch from '@/components/PlaceSearch.vue'
import PlanSheet from './PlanSheet.vue'
import RouteBandPanel from './RouteBandPanel.vue'
import RouteAssistant from './RouteAssistant.vue'
import { useRouteBandStore } from '@/stores/routeBand'
import WaypointPicker from './WaypointPicker.vue'
import { useDialog } from '@/composables/useDialog'
import { commuteCategories, shortcutCategoryIds, commuteCategoryGroups, commuteCategoryLabel } from '@/domain/commuteCategories'

const store = useCommuteStore()
const band = useRouteBandStore()
const plan = usePlanStore()
const places = usePlacesStore()
const mapInteraction = useMapInteractionStore()
const execution = useExecutionStore()
const { company, home, companyQuery, homeQuery, companyCandidates, homeCandidates,
  city, category, departureClock, deadlineClock, extraBudgetMinutes, stayMinutes,
  route, rankedPois, loading, error, stage, selectedPoiIndex } = storeToRefs(store)
const picker = ref<'company' | 'home' | null>(null)
const pickerPanel = ref<HTMLElement | null>(null)
useDialog(computed(() => picker.value !== null), pickerPanel, () => { picker.value = null })
onDeactivated(() => { picker.value = null })
const moreCategories = ref(false)
const settings = ref(false)
const planOpen = ref(false)
const waypointOpen = ref(false)
const waypointSeed = ref<PlaceRef | null>(null)
const editingWaypoint = ref<string | null>(null)
const waypointMinutes = ref(10)
const waypointRows = ref<HTMLElement | null>(null)
const draggedWaypoint = ref<string | null>(null)
function openWaypoint(id: string | null = null, place: PlaceRef | null = null): void {
  const task = id ? plan.tasks.find(task => task.id === id) : null
  const option = task?.options[0]
  waypointSeed.value = place ?? (option?.coord ? { name: task!.label, coord: option.coord, source: 'user-input' } : null)
  waypointMinutes.value = option ? option.serviceSeconds / 60 : stayMinutes.value
  editingWaypoint.value = id
  picker.value = null
  planOpen.value = false
  waypointOpen.value = true
}
function confirmWaypoint(place: PlaceRef, minutes: number): void {
  execution.resetExecution()
  if (editingWaypoint.value) {
    const seed = waypointSeed.value
    const unchanged = seed && place.uid === seed.uid && place.name === seed.name && place.coord.crs === seed.coord.crs && place.coord.lng === seed.coord.lng && place.coord.lat === seed.coord.lat
    if (unchanged) plan.setTaskServiceMinutes(editingWaypoint.value, minutes)
    else plan.replaceFixedTask(editingWaypoint.value, place, minutes)
  }
  else if (plan.tasks.length < 5) plan.addFixedTask(place, minutes)
  else { plan.error = '最多添加 5 个途经点'; return }
  plan.setVisitOrder(plan.tasks.map(task => task.id))
  mapInteraction.editingWaypoints = true
  savedMessage.value = '途经点已更新，确认顺序后规划路线'
}
function moveWaypoint(id: string, to: number): void {
  const ids = plan.tasks.map(task => task.id)
  const from = ids.indexOf(id)
  if (from < 0 || to < 0 || to >= ids.length || from === to) return
  ids.splice(from, 1)
  ids.splice(to, 0, id)
  plan.setVisitOrder(ids)
  execution.resetExecution()
}
function dragWaypoint(event: PointerEvent): void {
  if (!draggedWaypoint.value) return
  const row = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>('[data-waypoint-id]')
  if (!row || !waypointRows.value?.contains(row)) return
  const index = plan.tasks.findIndex(task => task.id === row.dataset.waypointId)
  if (index >= 0) moveWaypoint(draggedWaypoint.value, index)
}
async function confirmWaypoints(): Promise<void> {
  plan.setVisitOrder(plan.tasks.map(task => task.id))
  await plan.runPlan()
  if (plan.result?.status === 'ready') mapInteraction.editingWaypoints = false
  if (plan.error || plan.result?.status === 'infeasible') planOpen.value = true
}
watch(() => mapInteraction.waypointRequest, request => {
  if (!request) return
  openWaypoint(null, request.place)
  mapInteraction.waypointRequest = null
})
const placeName = ref('')
const savedMessage = ref('')
watch([company, home, departureClock, deadlineClock], () => {
  plan.invalidatePlan('路径已更改')
  execution.resetExecution()
}, { flush: 'sync' })
const visibleCategories = computed(() => shortcutCategoryIds.includes(category.value) ? shortcutCategoryIds : [...shortcutCategoryIds, category.value])
const query = computed({
  get: () => picker.value === 'home' ? homeQuery.value : companyQuery.value,
  set: (value: string) => { if (picker.value === 'home') homeQuery.value = value; else companyQuery.value = value },
})
const currentPlace = computed(() => picker.value === 'home' ? home.value : company.value)
const selected = computed(() => selectedPoiIndex.value == null ? null : rankedPois.value[selectedPoiIndex.value])
const displayedPois = computed(() => rankedPois.value.map((item, index) => ({ item, index }))
  .filter(({ item }) => !band.onlyMeasured || band.includes(item.place.naviCoord ?? item.place.coord)))
const arrival = computed(() => {
  const start = parseClockToSeconds(departureClock.value)
  return start == null || !route.value ? '' : formatClockSeconds(start + route.value.route.durationSeconds)
})
const status = computed(() => ({ route: '正在查找步行路线…', corridor: '正在查找顺路地点…', matrix: '正在核对绕行时间…' }[stage.value] ?? '正在计算…'))
function detourLabel(seconds: number | null): string {
  if (seconds == null) return '绕行时间未知'
  return (seconds < 0 ? '少走 ' : '绕行 ') + formatDurationSeconds(Math.abs(seconds))
}
function choose(place: PlaceRef): void {
  if (picker.value === 'home') { home.value = place; homeQuery.value = place.name; homeCandidates.value = [place] }
  else { company.value = place; companyQuery.value = place.name; companyCandidates.value = [place] }
  picker.value = null
  if (company.value && home.value) store.scheduleReplan(0)
}
function openPicker(slot: 'company' | 'home'): void {
  moreCategories.value = false
  settings.value = false
  mapInteraction.pickTarget = null
  picker.value = picker.value === slot ? null : slot
  placeName.value = ''
  savedMessage.value = ''
}
function toggleSettings(): void {
  moreCategories.value = false
  picker.value = null
  mapInteraction.pickTarget = null
  savedMessage.value = ''
  settings.value = !settings.value
}
function savePlace(place: PlaceRef): void {
  places.save({ label: placeName.value.trim() || place.name, place })
  savedMessage.value = '地点已保存'
}
function toggleCategories(): void {
  picker.value = null
  settings.value = false
  moreCategories.value = !moreCategories.value
  if (moreCategories.value) mapInteraction.panelExpandRequested = true
}
watch(planOpen, open => {
  if (!open) return
  picker.value = null
  settings.value = false
  moreCategories.value = false
})
function pickOnMap(): void {
  mapInteraction.beginPick(picker.value === 'home' ? 'route-end' : 'route-start')
  picker.value = null
  savedMessage.value = ''
}
watch(() => mapInteraction.selectedFor, (target) => {
  if (target !== 'route-start' && target !== 'route-end') return
  const coord = mapInteraction.selected(target)
  if (!coord) return
  const picked = mapInteraction.selectedPlace
  const place: PlaceRef = { ...picked, name: placeName.value.trim() || picked?.name || '地图地点', coord, source: placeName.value.trim() ? 'user-input' : picked?.source ?? 'user-input' }
  const slot = target === 'route-start' ? 'company' : 'home'
  places.use(place, slot)
  picker.value = null
  savedMessage.value = '已选择地点，可在我的地点保存'
  mapInteraction.clearSelected(target)
})
function reverse(): void {
  if (plan.visitOrder.length) plan.setVisitOrder(plan.tasks.map(task => task.id).reverse())
  const start = company.value
  company.value = home.value
  home.value = start
  const text = companyQuery.value
  companyQuery.value = homeQuery.value
  homeQuery.value = text
  companyCandidates.value = company.value ? [company.value] : []
  homeCandidates.value = home.value ? [home.value] : []
  picker.value = null
  if (company.value && home.value) store.scheduleReplan(0)
}
function select(index: number): void {
  void store.selectPoi(selectedPoiIndex.value === index ? null : index, false)
}
function add(): void {
  if (selectedPoiIndex.value == null) return
  plan.importFromCommute(selectedPoiIndex.value, 'fixed')
  savedMessage.value = '已加入今天安排'
}
watch(() => store.poiFocusIndex, (index) => {
  if (index != null) { void store.selectPoi(index, false); store.poiFocusIndex = null }
})
</script>

<template>
  <section class="commute">
    <div class="route-card">
      <div class="route-box">
        <div class="endpoints">
          <button
            class="endpoint"
            @click="openPicker('company')"
          >
            <i class="dot start" /><span><small>起点</small><strong>{{ company?.name || '选择起点' }}</strong></span>
          </button>
          <button
            class="endpoint"
            @click="openPicker('home')"
          >
            <i class="dot end" /><span><small>终点</small><strong>{{ home?.name || '选择终点' }}</strong></span>
          </button>
        </div>
        <button
          class="reverse"
          aria-label="反向路径"
          @click="reverse"
        >
          ⇅
        </button>
      </div>
      <section
        class="waypoints"
        :class="{ 'waypoints--editing': mapInteraction.editingWaypoints }"
        aria-label="途经点与顺序"
      >
        <div class="waypoints__head">
          <strong>途经点</strong>
          <button
            v-if="plan.tasks.length"
            type="button"
            @click="mapInteraction.editingWaypoints = !mapInteraction.editingWaypoints"
          >
            {{ mapInteraction.editingWaypoints ? '收起编辑' : '调整顺序' }}
          </button>
          <button
            type="button"
            :disabled="plan.tasks.length >= 5"
            @click="openWaypoint()"
          >
            ＋ 添加途经点
          </button>
        </div>
        <div
          ref="waypointRows"
          class="waypoints__rows"
        >
          <article
            v-for="(task, index) in plan.tasks"
            :key="task.id"
            :data-waypoint-id="task.id"
            class="waypoints__row"
            :class="{ 'waypoints__row--dragging': draggedWaypoint === task.id }"
          >
            <button
              type="button"
              class="waypoints__drag"
              :aria-label="'拖动途经点 ' + task.label"
              @pointerdown="draggedWaypoint = task.id; ($event.currentTarget as HTMLElement).setPointerCapture($event.pointerId)"
              @pointermove="dragWaypoint"
              @pointerup="draggedWaypoint = null"
              @pointercancel="draggedWaypoint = null"
            >
              ⠿
            </button>
            <button
              type="button"
              class="waypoints__place"
              @click="openWaypoint(task.id)"
            >
              <small>途经点 {{ index + 1 }}</small><strong>{{ task.label }}</strong>
            </button>
            <div class="waypoints__order">
              <button
                type="button"
                :aria-label="'上移途经点 ' + task.label"
                :disabled="index === 0"
                @click="moveWaypoint(task.id, index - 1)"
              >
                ↑
              </button><button
                type="button"
                :aria-label="'下移途经点 ' + task.label"
                :disabled="index === plan.tasks.length - 1"
                @click="moveWaypoint(task.id, index + 1)"
              >
                ↓
              </button>
            </div>
            <button
              type="button"
              :aria-label="'删除途经点 ' + task.label"
              @click="plan.removeTask(task.id); execution.resetExecution()"
            >
              ×
            </button>
          </article>
        </div>
        <template v-if="plan.tasks.length">
          <small>从上到下依次经过</small>
          <button
            type="button"
            class="primary"
            :disabled="plan.loading || !company || !home"
            @click="confirmWaypoints"
          >
            {{ plan.loading ? '规划中…' : '安排路线' }}
          </button>
          <button
            v-if="plan.result?.status === 'ready'"
            type="button"
            @click="planOpen = true"
          >
            查看行程
          </button>
          <p
            v-if="plan.error"
            role="alert"
          >
            {{ plan.error }}
          </p>
        </template>
      </section>
    </div>
    <RouteAssistant />
    <WaypointPicker
      v-model:open="waypointOpen"
      :initial-place="waypointSeed"
      :initial-minutes="waypointMinutes"
      :editing="Boolean(editingWaypoint)"
      @confirm="confirmWaypoint"
    />
    <div class="toolbar">
      <button
        :aria-expanded="settings"
        @click="toggleSettings"
      >
        出发设置
      </button>
      <button
        :aria-pressed="band.enabled"
        :disabled="!route || loading"
        @click="band.toggle"
      >
        沿途生活圈
      </button>
      <span v-if="route">{{ formatDurationSeconds(route.route.durationSeconds) }} · {{ arrival }} 到达</span>
    </div>
    <RouteBandPanel />

    <Teleport to="body">
      <div
        v-if="picker"
        class="endpoint-modal"
        role="dialog"
        aria-modal="true"
        :aria-label="picker === 'home' ? '选择终点' : '选择起点'"
        @click.self="picker = null"
      >
        <section
          ref="pickerPanel"
          class="endpoint-picker"
          tabindex="-1"
        >
          <header class="endpoint-picker__head">
            <strong>{{ picker === 'home' ? '选择终点' : '选择起点' }}</strong>
            <button
              aria-label="关闭地点选择"
              data-dialog-close
              @click="picker = null"
            >
              ✕
            </button>
          </header>
          <PlaceSearch
            :key="picker"
            v-model="query"
            placeholder="搜索任意地点"
            :city="city"
            allow-save
            @select="choose"
            @save="savePlace"
          />
          <div class="endpoint-picker__tools">
            <button @click="pickOnMap">
              <span aria-hidden="true">⌖</span> 地图选位置
            </button>
            <label>城市
              <input
                v-model="city"
                class="city"
                aria-label="城市"
                placeholder="城市"
              >
            </label>
          </div>
          <details
            class="endpoint-picker__save"
          >
            <summary>保存时命名</summary>
            <div class="search-row">
              <input
                v-model="placeName"
                aria-label="地点名称"
                placeholder="地点名称（可选）"
              >
              <button
                v-if="currentPlace"
                @click="savePlace(currentPlace)"
              >
                保存地点
              </button>
            </div>
          </details>
          <div
            v-if="places.places.length"
            class="chips"
          >
            <span
              v-for="favorite in places.places"
              :key="favorite.id"
            >
              <button @click="places.use(favorite.place, picker!); picker = null">{{ favorite.label }}</button>
              <button
                :aria-label="'删除地点 ' + favorite.label"
                @click="places.remove(favorite.id)"
              >×</button>
            </span>
          </div>
        </section>
      </div>
    </Teleport>

    <div
      v-if="settings"
      class="panel settings"
    >
      <label>出发时间<input
        v-model="departureClock"
        type="time"
      ></label>
      <label>最晚到达<input
        v-model="deadlineClock"
        type="time"
      ></label>
      <label>最多绕行（分钟）<input
        v-model.number="extraBudgetMinutes"
        type="number"
        min="0"
      ></label>
      <label>停留时间（分钟）<input
        v-model.number="stayMinutes"
        type="number"
        min="0"
        max="480"
      ></label>
      <p class="muted">
        含排队和办事，可在每个地点单独调整。
      </p>
      <button
        class="primary"
        :disabled="loading || !company || !home"
        @click="store.planCommute(); settings = false"
      >
        更新路径
      </button>
    </div>

    <div class="category-picker">
      <div class="category-picker__head">
        <strong>顺路办什么</strong>
      </div>
      <div class="category-picker__strip">
        <div
          class="category-row"
          aria-label="沿途地点类别"
        >
          <button
            v-for="value in visibleCategories"
            :key="value"
            :class="{ active: category === value }"
            :aria-pressed="category === value"
            :disabled="loading"
            @click="category = value"
          >
            {{ commuteCategoryLabel(value) }}
          </button>
        </div>
        <button
          class="category-more"
          aria-label="更多类别"
          :aria-expanded="moreCategories"
          @click="toggleCategories"
        >
          {{ moreCategories ? '收起' : '更多' }} <span aria-hidden="true">{{ moreCategories ? '⌃' : '⌄' }}</span>
        </button>
      </div>
      <div
        v-if="moreCategories"
        class="more-categories"
        aria-label="更多地点类别"
      >
        <section
          v-for="group in commuteCategoryGroups"
          :key="group"
          class="category-group"
        >
          <h3>{{ group }}</h3>
          <div>
            <button
              v-for="item in commuteCategories.filter(item => item.group === group)"
              :key="item.id"
              :disabled="loading"
              :aria-pressed="category === item.id"
              @click="category = item.id; moreCategories = false"
            >
              {{ item.label }}
            </button>
          </div>
        </section>
      </div>
    </div>
    <p
      v-if="loading"
      class="muted"
      role="status"
    >
      {{ status }}
    </p>
    <div
      v-else-if="error"
      role="alert"
      class="panel"
    >
      <p>{{ error }}</p><button @click="store.planCommute">
        重试
      </button>
    </div>
    <p
      v-if="savedMessage"
      class="notice"
      role="status"
    >
      {{ savedMessage }}
    </p>
    <p
      v-if="!loading && !error && !route"
      class="muted"
    >
      选择起点和终点，看看沿途有哪些顺路地点。
    </p>
    <div
      v-if="route && !loading && !error"
      class="recommendations"
    >
      <div class="list-title">
        <strong>顺路{{ category }}</strong><span>{{ displayedPois.length }} 个地点</span>
      </div>
      <p
        v-if="!displayedPois.length"
        class="muted"
      >
        {{ band.onlyMeasured ? '已测范围内暂时没有地点，可以关闭筛选查看。' : '这条路径附近暂时没找到，可以换个类别。' }}
      </p>
      <article
        v-for="{ item, index } in displayedPois"
        :key="item.place.uid || index"
        class="poi"
        :class="{ selected: selectedPoiIndex === index }"
      >
        <button
          class="poi-main"
          :aria-expanded="selectedPoiIndex === index"
          @click="select(index)"
        >
          <strong>{{ item.place.name }}</strong>
          <small v-if="band.includes(item.place.naviCoord ?? item.place.coord)">已测范围内</small>
          <span>{{ detourLabel(item.extraTravelSeconds) }} · {{ item.finishSeconds == null ? '到达时间未知' : formatClockSeconds(item.finishSeconds) + ' 到达终点' }}</span>
          <small v-if="!item.feasible">{{ item.reasons.map(reasonLabel).join(' · ') }}</small>
        </button>
        <div
          v-if="selectedPoiIndex === index && selected"
          class="poi-detail"
        >
          <p>{{ item.place.address }}</p><p>{{ item.place.shopHours || '营业时间待确认' }}</p>
          <button
            class="primary"
            :disabled="!item.feasible"
            @click="add"
          >
            加入今天安排
          </button>
          <button @click="savePlace(item.place)">
            保存地点
          </button>
        </div>
      </article>
    </div>
    <PlanSheet v-model:open="planOpen" />
  </section>
</template>

<style scoped>
.commute{display:grid;gap:12px;color:#26344c}
.waypoints{display:grid;gap:8px;background:#f4f7fc;border-radius:16px;padding:10px;font-size:13px}.waypoints__head{display:flex;justify-content:space-between;align-items:center}.waypoints__row{display:flex;align-items:center;gap:4px;border-top:1px solid #e1e7f0;padding-top:6px}.waypoints__row--dragging{background:#e5edff}.waypoints__row button{padding:6px;min-width:32px}.waypoints__place{display:grid;gap:3px;flex:1;min-width:0;text-align:left;border:0!important;background:transparent!important}.waypoints__place strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.waypoints small{color:#718098;line-height:1.5}.waypoints__order{display:flex}.waypoints__drag{touch-action:none;cursor:grab}.waypoints p{margin:0;color:#b45309}
button,input{font:inherit}
button{cursor:pointer;border:1px solid #e4e9f2;background:#fff;border-radius:12px;padding:10px 12px;color:inherit;min-height:44px}
button:disabled{opacity:.45;cursor:default}
button:focus-visible,input:focus-visible{outline:3px solid #8cafff;outline-offset:2px}
input{min-width:0;width:100%;box-sizing:border-box;border:1px solid #dfe5ef;border-radius:10px;padding:10px;background:#fff;color:inherit}
.route-box{display:flex;align-items:center;padding:4px 8px;background:#f4f7fc;border-radius:18px}
.endpoints{flex:1;min-width:0}
.endpoint{display:flex;align-items:center;gap:12px;width:100%;border:0;background:transparent;text-align:left}
.endpoint span{display:flex;gap:12px;min-width:0;align-items:center}
.endpoint small{flex:none}
.endpoint strong{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.endpoint small,.muted,.toolbar span,.list-title span{color:#7b879c;font-size:12px}
.dot{width:8px;height:8px;border-radius:50%;flex:none}.start{background:#4689f5}.end{background:#9a74e2}
.reverse{font-size:24px;background:white;border:0}
.toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.toolbar button{font-size:12px;padding:6px 10px;min-height:36px}.toolbar span{margin-left:auto}
.panel{background:#f6f8fc;border-radius:14px;padding:12px;display:grid;gap:10px}
.search-row{display:flex;gap:8px;align-items:center}.search-row button{flex:none;font-size:12px}.city{max-width:64px}
.results{list-style:none;padding:0;margin:0}.results li{display:flex;align-items:center;border-bottom:1px solid #e6ebf3;gap:8px}.result{flex:1;min-width:0;display:grid;gap:4px;text-align:left;border:0;background:transparent}.result small{font-size:11px;color:#8490a3}.quiet{justify-self:end}
.chips{display:flex;gap:6px;flex-wrap:wrap}.chips span{display:flex}.chips button{font-size:12px;padding:6px;min-height:36px}
.settings{grid-template-columns:1fr 1fr}.settings label{display:grid;gap:6px;font-size:12px}.settings button{align-self:end}
.category-row{display:flex;gap:8px;overflow:auto;padding:2px 0}.category-row button{flex:none;padding:8px 16px;border-radius:24px;font-size:13px}.category-row .active{background:#e9f0ff;color:#386ddd;border-color:#cbdcff}
.primary{background:#477beb;color:#fff;border-color:#477beb}.notice{color:#386ddd;font-size:12px;margin:0}.muted{line-height:1.7;margin:4px 0}
.list-title{display:flex;justify-content:space-between;align-items:center;margin:4px 0 8px}.list-title strong{font-size:14px}
.poi{border-bottom:1px solid #edf0f6;padding:2px 0}.poi.selected{border-radius:14px;background:#f3f6fe;border:1px solid #d9e4ff;padding:4px 8px}
.poi-main{width:100%;text-align:left;display:grid;gap:7px;border:0;background:transparent}.poi-main strong{font-size:14px}.poi-main span,.poi-main small,.poi-detail p{font-size:12px;color:#79869b;line-height:1.5}.poi-main small{color:#ae7743}.poi-detail{padding:0 12px 12px}.poi-detail button{font-size:12px;margin-right:8px}.poi-detail p{margin:4px 0 8px}
.more-categories{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:10px;border-radius:14px;background:#f6f8fc}.more-categories button{font-size:12px;padding:8px 4px}.more-categories button[aria-pressed="true"]{color:#386ddd;background:#e9f0ff}

.commute{gap:11px;padding:0;padding-bottom:70px}.route-box{padding:10px 11px;border:1px solid #e1e8f2;background:white;border-radius:14px}.endpoints{gap:3px}.endpoint{padding:7px 0;min-height:38px}.endpoint strong{font-size:14px}.endpoint small{font-size:10px}.endpoint span{gap:10px}.reverse{font-size:22px}.toolbar{gap:5px}.toolbar button{min-height:34px;padding:6px 8px;font-size:11px;border-radius:9px}.toolbar span{font-size:10px;margin-left:0}.waypoints{background:#fafcff;padding:10px;border:1px solid #e2e8f2;border-radius:13px}.waypoints__head{gap:5px}.waypoints__head strong{font-size:12px}.waypoints__head button{min-height:32px;font-size:10.5px;padding:5px 7px}.waypoints:not(.waypoints--editing) .waypoints__drag,.waypoints:not(.waypoints--editing) .waypoints__order,.waypoints:not(.waypoints--editing) .waypoints__row>button:last-child{display:none}.waypoints__row{padding:4px 0;gap:6px}.waypoints__place strong{font-size:13px}.waypoints__place small{font-size:10px}.waypoints>.primary{font-size:12px;min-height:38px;padding:8px;margin-top:6px}.waypoints>small{font-size:10px}.category-row{gap:5px}.category-row button{padding:6px 11px;min-height:34px;font-size:11px}.list-title strong{font-size:12px}.poi-main{padding:9px 2px;gap:4px;min-height:70px}.poi-main strong{font-size:13px}.poi-main span,.poi-main small{font-size:11px}.poi-detail button{font-size:11px;min-height:34px}.muted{font-size:11px}.panel{padding:10px}.more-categories button{font-size:11px}
.commute{padding-bottom:0}
.route-card{background:#fff;border:1px solid #e1e8f2;border-radius:16px;overflow:hidden;padding:0 12px}
.route-card .route-box{padding:4px 0;border:0;border-radius:0;background:transparent}
.route-card .endpoint{min-height:48px;padding:8px 0;gap:10px}
.route-card .endpoint span{flex:1;gap:9px;min-width:0}
.route-card .endpoint small{font-size:11px;min-width:24px}
.route-card .endpoint strong{font-size:14px;font-weight:600}
.route-card .endpoint+.endpoint{border-top:1px solid #f0f3f8;border-radius:0}
.route-card .reverse{width:40px;min-height:44px;margin-left:10px;font-size:22px;color:#62748f;background:#f5f7fb;border-radius:12px}
.route-card .waypoints{padding:7px 0 9px;border:0;border-top:1px solid #e9edf4;border-radius:0;background:transparent;gap:5px}
.route-card .waypoints__head strong{font-size:11px;font-weight:500;color:#7b879c}
.route-card .waypoints__head button{border:0;background:transparent;color:#386ddd;min-height:38px;padding:6px;font-size:12px}
.toolbar{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0;padding:0 0 4px;border-bottom:1px solid #edf0f6}
.toolbar button{border:0;background:transparent;border-radius:8px;min-height:44px;padding:5px 2px;font-size:11px;color:#61738e;white-space:nowrap}
.toolbar button[aria-expanded="true"],.toolbar button[aria-pressed="true"]{color:#356ce2;background:#eff4ff}
.toolbar span{grid-column:1/-1;padding:3px 0;text-align:center}
.endpoint-modal{position:fixed;inset:0;z-index:60;background:#10243b55;display:flex;align-items:flex-end;justify-content:center}
.endpoint-picker{width:min(480px,100%);box-sizing:border-box;max-height:85dvh;overflow:auto;border-radius:22px 22px 0 0;padding:16px 16px max(18px,env(safe-area-inset-bottom));background:white;display:grid;gap:14px;color:#26344c;font-size:14px;box-shadow:0 -12px 40px #17243a18}
.endpoint-picker__head{display:flex;align-items:center;justify-content:space-between;font-size:16px}
.endpoint-picker__head button{border:0;background:#f3f6fa;border-radius:50%;width:36px;min-height:36px;padding:6px;color:#718098}
.endpoint-picker__tools{display:flex;justify-content:space-between;align-items:center;gap:12px}
.endpoint-picker__tools>button{border:0;background:#eff5ff;color:#356ce2;min-height:44px;padding:8px 12px;font-size:13px}
.endpoint-picker__tools label{display:flex;align-items:center;gap:6px;color:#7b879c;font-size:12px}
.endpoint-picker__tools .city{max-width:80px;min-height:40px;border:0;background:#f5f7fb;padding:8px;text-align:center}
.endpoint-picker__save{font-size:12px;color:#718098}.endpoint-picker__save summary{cursor:pointer;padding:7px 0}.endpoint-picker__save .search-row{padding-top:6px}
.poi{padding:13px;border-radius:16px;background:white;transition:border-color .18s,background .18s,box-shadow .18s}.poi.selected{border-color:#2563eb;background:#f6faff;box-shadow:0 0 0 1px #2563eb,0 4px 14px #2563eb0d}.poi .poi-main{gap:7px}.poi-main strong{font-size:15px;line-height:1.5}.poi-main span{font-size:13px;color:#62758e;line-height:1.5}.poi-main small{font-size:12px}.poi-detail p{font-size:13px}.poi-detail button{min-height:40px;padding:8px 12px;font-size:13px}.route-card .endpoint strong{font-size:15px}.commute>header strong{font-size:15px}@media(prefers-reduced-motion:reduce){.poi{transition:none}}
.endpoint-picker :deep(.place-search form){gap:8px}.endpoint-picker :deep(.place-search input){min-height:46px;background:#f5f7fb;border-color:#e8edf4;font-size:14px}.endpoint-picker :deep(.place-search form button){min-height:46px;font-size:13px;padding:8px 12px}
@media(min-width:821px){.endpoint-modal{align-items:center;padding:20px}.endpoint-picker{border-radius:20px}}
.category-picker{display:grid;gap:8px;padding:2px 0 7px}.category-picker__head strong{font-size:12px;font-weight:600;color:#556782}.category-picker__strip{display:flex;align-items:center;gap:5px;min-width:0}.category-picker .category-row{flex:1;min-width:0;gap:3px;padding:2px;background:#f3f6fa;border-radius:11px;scrollbar-width:none}.category-picker .category-row::-webkit-scrollbar{display:none}.category-picker .category-row button{flex:1;min-height:40px;padding:6px 8px;font-size:12px;border:0;background:transparent;border-radius:9px;white-space:nowrap;color:#66758b}.category-picker .category-row button.active{background:white;color:#2863df;font-weight:650;box-shadow:0 1px 5px #24375414}.category-picker .category-more{flex:none;min-height:44px;border:0;background:transparent;padding:6px;font-size:11px;color:#5f718c}.category-picker .category-more[aria-expanded="true"]{color:#2863df}.category-picker .more-categories{display:grid;grid-template-columns:1fr;gap:13px;border:1px solid #e9edf4;background:#fafbfd;padding:12px;border-radius:12px}.category-group h3{margin:0 0 7px;color:#7b879b;font-size:10px;font-weight:500}.category-group>div{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px}.category-picker .category-group button{font-size:11px;min-height:40px;padding:5px 2px;border:0;border-radius:8px;background:white}.category-picker .category-group button[aria-pressed="true"]{color:#2863df;background:#eaf1ff;font-weight:600}
</style>
