<!-- F55：等时圈体检模块。三种起点（地图点选/地址搜索/自定位）+ 阈值切换 + L2先行降级链预览 + 边界/报告展示。
     现由社区体检页承载；旧 /isochrone 路由仅保留兼容入口。点击时间按钮直接触发圈生成并联动后续民生设施评估。 -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'

import type { PlaceRef } from '@/domain/types'
import type { IsochronePoiRow } from '@/providers/contracts'
import { isochroneStatusLabel, sourceKindLabel } from '@/domain/sourceExplain'
import { useIsochroneStore } from '@/stores/isochrone'
import { useAppStore } from '@/stores/app'
import { usePlanStore } from '@/stores/plan'
import { useCommuteStore } from '@/stores/commute'
import PlaceSearch from '@/components/PlaceSearch.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useMapInteractionStore } from '@/stores/mapInteraction'

withDefaults(defineProps<{ showReportExport?: boolean }>(), { showReportExport: true })

const app = useAppStore()
const exportError = ref('')
async function exportReport(): Promise<void> {
  exportError.value = ''
  if (!store.result || !app.provider.exportReport) return
  try {
    const response = await app.provider.exportReport(store.result.taskId, 'json')
    const url = URL.createObjectURL(new window.Blob([response.content], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `生活圈报告-${store.result.taskId}.json`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) { exportError.value = error instanceof Error ? error.message : String(error) }
}
const store = useIsochroneStore()
const plan = usePlanStore()
const { result, l2Preview, backgroundStatus, loading, error, hasOrigin, originLabel } = storeToRefs(store)

// F57：圈内 POI 加入今天安排。POI 来自百度区域检索（来源跟随行），停留为用户输入模拟值。
const joinNotice = ref('')
function joinPlan(poi: IsochronePoiRow): void {
  const raw = (poi.coord ?? poi.naviCoord ?? poi.navi_coord) as unknown
  const coord = (typeof raw === 'object' && raw !== null ? raw : poi) as Record<string, unknown>
  const lng = Number(coord.lng)
  const lat = Number(coord.lat)
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
    joinNotice.value = '该地点缺少位置，无法加入今天安排'
    return
  }
  const place = {
    uid: typeof poi.uid === 'string' ? poi.uid : undefined,
    name: String(poi.name ?? poi.uid ?? '附近地点'),
    coord: { lng, lat, crs: String(coord.crs ?? 'BD09') },
    source: (typeof poi.source === 'string' ? poi.source : 'derived'),
  } as unknown as PlaceRef
  plan.addFixedTask(place, 10)
  joinNotice.value = `已加入今天安排：${place.name}（停留 10 分钟，可在安排中修改）`
}

const commute = useCommuteStore()
const mapInteraction = useMapInteractionStore()
const locating = ref(false)
const locateError = ref('')
function locate(): void {
  if (!('geolocation' in navigator)) {
    locateError.value = '当前浏览器不支持定位，请改用地图点选或地址搜索'
    return
  }
  locating.value = true
  locateError.value = ''
  navigator.geolocation.getCurrentPosition(
    (position) => {
      locating.value = false
      // 浏览器定位为 WGS84；百度请求在唯一出口转换，此处显式记录来源坐标系。
      store.setOrigin(
        {
          lng: position.coords.longitude,
          lat: position.coords.latitude,
          crs: 'WGS84',
        },
        '自定位',
      )
    },
    (failure) => {
      locating.value = false
      locateError.value = failure.code === failure.PERMISSION_DENIED
        ? '定位被拒绝：请在浏览器地址栏允许定位，或改用地图点选/地址搜索'
        : `定位失败（${failure.message || failure.code}），请改用地图点选/地址搜索`
    },
    { timeout: 8000 },
  )
}

const activeCircle = computed(() => result.value ?? l2Preview.value)

const report = computed(() => {
  const raw = result.value?.report
  if (!raw || typeof raw !== 'object') return null
  return raw as Record<string, unknown>
})

function num(value: unknown): number | null {
  if (value == null || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

// 重建近似面积（km²，取 report.approxAreaM2）；无结果时若处于 L2 预览则按 L2 半径折算。
const areaKm2 = computed(() => {
  const m2 = report.value ? num(report.value.approxAreaM2) : null
  if (m2 != null) return m2 / 1e6
  if (l2Preview.value) {
    const r = Object.values(l2Preview.value.radiiM)[0]
    if (r != null && r > 0) return (Math.PI * r * r) / 1e6
  }
  return null
})
// 实测道路边界中位（米，取 report.medianRadiusM）；L2 预览时显示折算半径。
const medianM = computed(() => {
  const m = report.value ? num(report.value.medianRadiusM) : null
  if (m != null) return m
  if (l2Preview.value) {
    const r = Object.values(l2Preview.value.radiiM)[0]
    if (r != null && r > 0) return r
  }
  return null
})

function walkMinutes(poi: IsochronePoiRow): string {
  const seconds = num(poi.walkSeconds)
  if (seconds == null) return '步行时长未知'
  const minutes = seconds / 60
  return `步行 ${minutes >= 10 ? Math.round(minutes) : minutes.toFixed(1)} 分钟`
}

function distanceText(poi: IsochronePoiRow): string {
  const meters = num(poi.distanceM)
  if (meters == null) return ''
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)}km` : `${Math.round(meters)}m`
}

function unreachableReason(poi: IsochronePoiRow): string {
  const reason = typeof poi.reason === 'string' && poi.reason ? poi.reason : '不可达'
  return ({ no_route: '无法步行到达', over_threshold: '超出步行时间范围', unknown_route: '路线尚未查明' } as Record<string, string>)[reason] ?? reason
}
</script>

<template>
  <section class="isochrone-page">
    <!-- 探测中心卡：起点名 + 阈值 pills（一键生成圈 + 联动后续设施体检） -->
    <div
      v-if="showReportExport || store.heatError"
      class="origin-card"
    >
      <div
        v-if="showReportExport"
        class="origin-row"
      >
        <span class="origin-title"><span
          class="origin-dot"
          aria-hidden="true"
        />当前地点</span>
        <strong class="origin-name">{{ originLabel || '选择一个地点' }}</strong>
      </div>
      <details
        v-if="showReportExport"
        class="origin-picker"
        :open="!hasOrigin"
      >
        <summary>更换地点</summary>
        <div class="row">
          <PlaceSearch
            :city="commute.city"
            search-type="search"
            label="搜索地址作为起点"
            placeholder="搜索社区或地址"
            @select="place => store.setOrigin(place.coord, place.name)"
          />
          <div class="origin-actions">
            <button
              type="button"
              @click="mapInteraction.beginPick('community-center')"
            >
              地图选位置
            </button>
            <button
              type="button"
              :disabled="locating"
              @click="locate"
            >
              {{ locating ? '定位中…' : '使用定位' }}
            </button>
            <button
              v-if="hasOrigin"
              type="button"
              @click="store.reset()"
            >
              清除地点
            </button>
          </div>
        </div>
      </details>
      <p
        v-if="locateError"
        class="error"
        role="alert"
      >
        {{ locateError }}
      </p>
      <p
        v-if="store.heatError"
        class="error"
        role="status"
      >
        {{ store.heatError }}
      </p>
    </div>

    <button
      v-if="result && showReportExport"
      type="button"
      @click="exportReport"
    >
      导出报告
    </button>
    <p
      v-if="exportError"
      class="error"
      role="alert"
    >
      {{ exportError }}
    </p>
    <!-- 边界指标卡：支持 L2 预估即时展示 + 路网实测完成后无感升级 -->
    <div
      v-if="activeCircle && showReportExport"
      class="metrics"
    >
      <div class="metric">
        <p class="metric-label">
          近似覆盖面积
        </p>
        <p class="metric-value">
          <template v-if="areaKm2 != null">
            {{ areaKm2.toFixed(2) }} <span class="metric-unit">km²</span>
          </template>
          <template v-else>
            —
          </template>
        </p>
        <span class="metric-note note-green">{{ result ? '步行范围估算' : '快速范围初筛' }}</span>
      </div>
      <div class="metric">
        <p class="metric-label">
          步行可达距离
        </p>
        <p class="metric-value">
          <template v-if="medianM != null">
            {{ Math.round(medianM) }} <span class="metric-unit">米中位</span>
          </template>
          <template v-else>
            —
          </template>
        </p>
        <span class="metric-note note-blue">{{ result ? '按步行路线测量' : '快速估算预览' }}</span>
      </div>
      <div class="metric">
        <p class="metric-label">
          圈内可达服务
        </p>
        <p class="metric-value">
          <template v-if="store.poisLoaded">
            {{ store.poiTruncated || store.unreachable.some(poi => poi.reason === 'unknown_route') ? '至少 ' : '' }}{{ store.reachable.length }} <span class="metric-unit">家</span>
          </template>
          <template v-else>
            —
          </template>
        </p>
        <span class="metric-note note-purple">从中心步行可达</span>
      </div>
    </div>

    <p
      v-if="loading || backgroundStatus === 'running' || (result?.frontier && result.status !== 'complete' && result.frontier.previewContours.length)"
      class="l2-banner"
      role="status"
    >
      <AppIcon
        name="circle"
        :size="18"
      />
      {{ result?.frontier ? backgroundStatus === 'running' ? '虚线随当前测点拟合，最终范围仍在测量中…' : '范围未测完，虚线仅供参考。' : result?.status === 'complete' ? '范围已显示，正在完善边界…' : '虚线为预估范围，正在查询实际步行范围…' }}
    </p>
    <p
      v-if="error"
      class="error"
      role="alert"
    >
      {{ error }}
    </p>

    <template v-if="result && (backgroundStatus !== 'running' || result.status === 'complete')">
      <p class="status-line">
        {{ isochroneStatusLabel(result.status) }} · {{ sourceKindLabel(result.sourceKind ?? (result.cacheHit ? 'api-cache' : 'derived')) }}
        <span v-if="store.rangeReused"> · 已复用步行范围</span>
        <span v-if="result.warnings?.includes('adaptive_resolution_limited')"> · 近似范围</span>
        <span v-if="result.frontier?.interiorEstimated"> · 内部区域为近似估计</span>
        <span v-if="result.frontier?.clipped"> · 部分范围超出测量区域</span>
        <span v-if="result.skippedBearings.length">
          · 部分方向尚未完成测量
        </span>
      </p>
      <p
        v-if="showReportExport"
        class="report-trace"
      >
        报告编号 {{ result.taskId }} · 算法版本 {{ result.algorithmVersion }} · 阈值 {{ result.thresholdSeconds / 60 }} 分钟
      </p>
      <p
        v-if="result.status !== 'complete'"
        class="warning"
      >
        部分方向未能完成测量，当前范围仅供参考。可切换步行时长后重试。
      </p>
    </template>

    <!-- 圈内 POI 列表 -->
    <section
      v-if="result && showReportExport"
      class="pois-panel"
    >
      <div class="pois-head">
        <h3>范围内设施</h3>
        <span class="source-tag">来源：{{ sourceKindLabel(result.sourceKind ?? (result.cacheHit ? 'api-cache' : 'derived')) }}</span>
      </div>
      <form
        class="search"
        @submit.prevent="store.loadPois()"
      >
        <input
          v-model="store.poiTerms"
          type="text"
          placeholder="搜索设施，如：药店 便利店"
          aria-label="圈内设施类别关键词"
        >
        <button
          type="submit"
          :disabled="store.poisLoading"
        >
          {{ store.poisLoading ? '查找中…' : '查找圈内设施' }}
        </button>
      </form>
      <p v-if="store.poisLoading">
        正在查找设施并核对步行时间…
      </p>
      <p
        v-if="store.poisError"
        class="error"
        role="alert"
      >
        {{ store.poisError }}
      </p>
      <template v-if="!store.poisLoading && !store.poisError">
        <p v-if="store.reachable.length || store.unreachable.length">
          检索到的设施：可达 {{ store.reachable.length }} 个 · 不可达 {{ store.unreachable.length }} 个
          <span v-if="store.poiTruncated">· 仅显示部分检索结果</span>
        </p>
        <ul
          v-if="store.reachable.length"
          class="poi-list"
        >
          <li
            v-for="poi in store.reachable"
            :key="String(poi.uid ?? poi.name)"
            class="poi-row"
          >
            <div class="poi-main">
              <p class="poi-name">
                {{ String(poi.name ?? poi.uid) }}
              </p>
              <p class="poi-sub">
                <span v-if="distanceText(poi)">{{ distanceText(poi) }} · </span>{{ walkMinutes(poi) }}
              </p>
            </div>
            <div class="poi-side">
              <span class="badge-ok">圈内可达</span>
              <button
                type="button"
                class="join-btn"
                @click="joinPlan(poi)"
              >
                加入今天安排
              </button>
            </div>
          </li>
        </ul>
        <ul
          v-if="store.unreachable.length"
          class="poi-list"
        >
          <li
            v-for="poi in store.unreachable"
            :key="String(poi.uid ?? poi.name)"
            class="poi-row poi-row--off"
          >
            <div class="poi-main">
              <p class="poi-name">
                {{ String(poi.name ?? poi.uid) }}
              </p>
              <p class="poi-sub">
                {{ walkMinutes(poi) }}
              </p>
            </div>
            <div class="poi-side">
              <span class="badge-off">{{ unreachableReason(poi) }}</span>
            </div>
          </li>
        </ul>
        <p
          v-if="joinNotice"
          class="notice"
        >
          {{ joinNotice }}
          <RouterLink to="/plan">
            去今天安排查看
          </RouterLink>
        </p>
        <p
          v-if="!store.reachable.length && !store.unreachable.length"
          class="empty"
        >
          暂未查询设施
        </p>
      </template>
    </section>
  </section>
</template>

<style scoped>
.isochrone-page { display: grid; gap: 0.65rem; }
.hint { color: var(--color-muted); font-size: 0.85rem; margin: 0.25rem 0 0; }
.origin-card {
  display: grid;
  gap: 0.5rem;
  padding: 0.8rem;
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: 0.9rem;
  background: linear-gradient(135deg, #f8fbff 0%, #ffffff 68%);
  box-shadow: 0 2px 10px rgb(15 23 42 / 4%);
}
.origin-row { display: grid; gap: 0.375rem; min-width: 0; }
.origin-title { color: var(--color-muted); font-size: 12px; display: inline-flex; align-items: center; gap: 0.375rem; }
.origin-dot { width: 0.5rem; height: 0.5rem; border-radius: 9999px; background: #2563eb; display: inline-block; }
.origin-name { font-size: 18px; font-weight: 700; color: var(--color-text); line-height: 1.5; overflow-wrap: anywhere; }
.row { display: grid; gap: 0.25rem; min-width: 0; }
.origin-actions { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
.origin-actions button { min-height: 44px; padding: 6px 4px; border: 0; background: transparent; font-size: 12px; color: #2563eb; }
.origin-actions button:last-child { margin-left: auto; }
.row :deep(.place-search__form) { gap: 6px; }
.row :deep(.place-search__form input), .row :deep(.place-search__form button) { font-size: 13px; }
.search { display: flex; gap: 0.5rem; flex: 1 1 16rem; }
.search input { flex: 1 1 auto; }
.candidates { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.25rem; }
.threshold-row { display: grid; gap: 0.375rem; padding-top: 0.25rem; }
.threshold-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
.threshold-label { font-size: 12px; color: var(--color-muted); }
.origin-card .threshold-head--empty { display: flex; }
.thresholds { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.375rem; }
.pill { min-height: 44px; border: 1px solid var(--color-border, #e2e8f0); border-radius: 0.5rem; padding: 0.25rem 0.375rem; font-size: 0.75rem; font-weight: 600; background: #fff; transition: all 0.15s ease; }
.pill.active { background: #2563eb; color: #fff; border-color: #2563eb; box-shadow: 0 2px 6px rgb(37 99 235 / 22%); }
.heat-btn { font-size: 0.78rem; padding: 0.45rem 0.75rem; border-radius: 0.55rem; border: 1px solid #cbd5e1; background: #f8fafc; color: #1e293b; font-weight: 600; }
.l2-banner { font-size: 0.78rem; color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 0.6rem; padding: 0.45rem 0.65rem; margin: 0; }
.metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.45rem; text-align: center; }
.metric { background: #fff; padding: 0.6rem 0.35rem; border: 1px solid var(--color-border, #e2e8f0); border-radius: 0.7rem; box-shadow: 0 1px 3px rgb(15 23 42 / 4%); }
.metric-label { font-size: 0.65rem; color: var(--color-muted); margin: 0; }
.metric-value { font-size: 0.9rem; font-weight: 700; margin: 0.25rem 0 0; }
.metric-unit { font-size: 0.65rem; font-weight: 400; }
.metric-note { font-size: 0.6rem; }
.note-green { color: #059669; }
.note-blue { color: #2563eb; }
.note-purple { color: #7c3aed; }
.status-line { font-size: 0.72rem; color: var(--color-muted); margin: 0; }
.report-trace { display: none; }
@media print { .report-trace { display: block; font-size: 10px; } }
.error { color: #b3261e; }
.warning { color: #8a5a00; }
.empty { color: var(--color-muted); }
.pois-panel { display: grid; gap: 0.5rem; padding-top: 0.15rem; }
.pois-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
.pois-head h3 { margin: 0; font-size: 0.85rem; }
.source-tag { font-size: 0.65rem; background: var(--color-surface, #f1f5f9); padding: 0.125rem 0.375rem; border-radius: 0.375rem; color: var(--color-muted); }
.poi-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.5rem; }
.poi-row { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; padding: 0.625rem; background: #fff; border: 1px solid var(--color-border, #e2e8f0); border-radius: 0.75rem; }
.poi-row--off { opacity: 0.75; }
.poi-name { font-weight: 700; margin: 0; font-size: 0.85rem; }
.poi-sub { font-size: 0.7rem; color: var(--color-muted); margin: 0.125rem 0 0; }
.poi-side { display: grid; gap: 0.375rem; justify-items: end; }
.badge-ok { font-size: 0.65rem; background: #ecfdf5; color: #047857; font-weight: 600; padding: 0.125rem 0.5rem; border-radius: 9999px; border: 1px solid #a7f3d0; }
.badge-off { font-size: 0.65rem; background: var(--color-surface, #f1f5f9); color: var(--color-muted); padding: 0.125rem 0.5rem; border-radius: 9999px; }
.join-btn { font-size: 0.75rem; font-weight: 600; }
.notice { font-size: 0.8rem; }
@media (max-width: 430px) {
  .metrics { gap: 0.3rem; }
  .metric-label { font-size: 0.6rem; }
  .metric-value { font-size: 0.82rem; }
}

.origin-card{background:#f8fafc;padding:10px;border:1px solid #e4eaf2;border-radius:13px;box-shadow:none}.origin-row{display:flex;gap:8px;align-items:center}.origin-title{font-size:11px;white-space:nowrap}.origin-name{font-size:14px;line-height:1.5;overflow-wrap:anywhere}.origin-picker{margin:4px 0}.origin-picker summary{font-size:11px;color:#2563eb;min-height:30px;cursor:pointer;display:flex;align-items:center}.threshold-row{display:block;margin-top:5px}.threshold-head{display:none}.thresholds{display:flex;flex-wrap:nowrap;gap:5px}.thresholds .pill{flex:1;min-width:0;white-space:nowrap;min-height:36px;padding:6px 4px;font-size:11px;border-radius:9px}.isochrone-page{gap:8px}.status-line,.l2-banner,.warning{font-size:11px;padding:7px 9px;margin:0}.origin-actions{flex-wrap:wrap}.origin-actions button{font-size:11px}.origin-card .row{flex-wrap:wrap}.origin-card .place-search{flex-basis:100%}

.origin-card{gap:6px}.origin-row{margin:0}.threshold-row{padding-top:0;margin-top:0}.origin-card .thresholds button{min-height:44px}.origin-picker{margin:0}.origin-picker summary{min-height:26px}

.origin-change{justify-self:start;border:0;background:none;color:#2563eb;font-size:11px;min-height:30px;padding:4px 0}
.l2-banner{display:flex;align-items:center;gap:8px;padding:10px 12px;background:#eff6ff;border-radius:12px;font-size:12px;line-height:1.5;color:#41638e}.l2-banner .app-icon{color:#2563eb;flex:none}
.thresholds .pill{font-size:13px;border-radius:10px}.origin-card{padding:12px}.origin-title{font-size:12px}.thresholds{gap:6px}
</style>
