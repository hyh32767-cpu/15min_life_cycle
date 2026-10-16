<!-- T110/UI-M：百度地图底图视口。百度 JSAPI 负责底图/点选/覆盖物；
     业务数据仍经 /api。SDK 失败时显示独立错误，不回退假底图。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import { MAP_STYLE } from './mapTheme'
import './mapVisuals.css'

import type { NamedCoord, PlaceRef, SourceKind } from '@/domain/types'
import { sourceKindLabel } from '@/domain/sourceExplain'
import { useAppStore } from '@/stores/app'
import { useMapsStore } from '@/stores/maps'
import {
  renderLayers,
  stopPreviewAnimation,
  gpsToBaidu,
  type BMapClickEvent,
  type BMapInstance,
  type BMapNamespace,
  type BMapOverlay,
  type LayerMarker,
} from './baiduAdapter'

export type MapMarkerInput = LayerMarker

const props = withDefaults(defineProps<{
  routes?: NamedCoord[][]
  planRoutes?: NamedCoord[][]
  isoPolygons?: NamedCoord[][]
  isoContours?: NamedCoord[][]
  previewContours?: NamedCoord[][]
  referenceCircle?: { center: NamedCoord; radiusM: number } | null
  heatPolygons?: { ring: NamedCoord[]; seconds: number; mesh?: boolean; estimated?: boolean; contours?: NamedCoord[][] }[]
  coverageCells?: { ring: NamedCoord[]; status: 'covered' | 'blind' | 'unknown' }[]
  routeBand?: { fills: NamedCoord[][]; boundaries: NamedCoord[][]; seconds: number } | null
  markers?: MapMarkerInput[]
  center?: NamedCoord | null
  viewKey?: string
  zoom?: number
  pickable?: boolean
  interactionLocked?: boolean
  pickPrompt?: string
  sourceKinds?: SourceKind[]
}>(), {
  routes: () => [],
  planRoutes: () => [],
  isoPolygons: () => [],
  isoContours: () => [],
  previewContours: () => [],
  referenceCircle: null,
  heatPolygons: () => [],
  coverageCells: () => [],
  routeBand: null,
  markers: () => [],
  center: null,
  viewKey: 'commute',
  zoom: 15,
  pickable: false,
  interactionLocked: false,
  pickPrompt: '',
  sourceKinds: () => [],
})

const emit = defineEmits<{
  (event: 'pick', coord: NamedCoord, place?: PlaceRef): void
  (event: 'map-error', message: string): void
  (event: 'marker-click', payload: { type: string; index?: number; placeKey?: string }): void
  (event: 'poi-click', place: PlaceRef): void
  (event: 'cancel-pick'): void
}>()

const maps = useMapsStore()
const container = ref<HTMLElement | null>(null)
const localError = ref('')
const pendingPick = ref<NamedCoord | null>(null)
const pickedPlace = ref<PlaceRef | null>(null)
const pickName = ref('')
const resolvingPick = ref(false)
const pickError = ref('')
let pickGeneration = 0
let pickTimer: ReturnType<typeof setTimeout> | undefined
const app = useAppStore()
let map: BMapInstance | null = null
let alignTimer: ReturnType<typeof setTimeout> | undefined
function alignVisibleArea(): void {
  clearTimeout(alignTimer)
  alignTimer = setTimeout(() => {
    const BMap = (window as unknown as Record<string, unknown>).BMap as BMapNamespace | undefined
    if (!map?.pointToPixel || !map.panBy || !BMap || !props.center || props.center.crs !== 'BD09' || !container.value) return
    const rect = container.value.getBoundingClientRect()
    const { width, height } = rect
    const shell = container.value.closest('.shell')
    if (!shell) return
    const sheet = shell.querySelector('.sheet')?.getBoundingClientRect()
    const mobile = window.innerWidth <= 820
    const visibleBottom = sheet?.height ? Math.max(0, Math.min(height, sheet.top - rect.top)) : height
    const panelRight = sheet?.height ? Math.max(0, sheet.right - rect.left) : 0
    const x = mobile ? width / 2 : (width + panelRight) / 2
    const y = mobile ? visibleBottom / 2 : height / 2
    const pixel = map.pointToPixel(new BMap.Point(props.center.lng, props.center.lat))
    map.panBy(x - pixel.x, y - pixel.y, { noAnimation: true })
  }, 260)
}
let overlays: BMapOverlay[] = []
let markerRevision = 0
let markerClickedAt = 0
let renderedMarkers: MapMarkerInput[] = []
const knownPick = ref<PlaceRef | null>(null)
let resizeObserver: ResizeObserver | null = null
let clickHandler: ((e: BMapClickEvent) => void) | null = null
const DEFAULT_CENTER: NamedCoord = { lng: 116.404, lat: 39.915, crs: 'BD09' }
type ViewState = { point: NamedCoord; zoom: number; anchor: string }
const views = new Map<string, ViewState>()
let activeView = props.viewKey
let activeAnchor = ''
const currentLocation = ref<NamedCoord | null>(null)
const locating = ref(false)
const locationError = ref('')
let locationGeneration = 0
let locationNoticeTimer: ReturnType<typeof setTimeout> | undefined
function clearLocationNotice(): void {
  clearTimeout(locationNoticeTimer)
  locationError.value = ''
}
function showLocationError(message: string): void {
  clearLocationNotice()
  locationError.value = message
  locationNoticeTimer = setTimeout(clearLocationNotice, 5000)
}
async function locateOnMap(): Promise<void> {
  if (props.interactionLocked) return
  clearLocationNotice()
  if (!window.isSecureContext) { showLocationError('定位需要 HTTPS，请先使用搜索或地图选点'); return }
  if (!navigator.geolocation) { showLocationError('当前浏览器不支持定位，请使用搜索或地图选点'); return }
  const ns = (window as unknown as Record<string, unknown>).BMap as BMapNamespace | undefined
  if (!map || !ns) return
  const current = ++locationGeneration
  locating.value = true
  let watchdog: ReturnType<typeof setTimeout> | undefined
  try {
    const position = await new Promise<{ coords: { longitude: number; latitude: number } }>((resolve, reject) => {
      // 一些浏览器未按 geolocation 的 timeout 回调；独立计时保证按钮恢复。
      watchdog = setTimeout(() => reject({ code: 3 }), 8500)
      navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 8000, maximumAge: 30_000, enableHighAccuracy: true })
    })
    clearTimeout(watchdog)
    if (current !== locationGeneration) return
    const coord = await gpsToBaidu(ns, position.coords.longitude, position.coords.latitude)
    if (current !== locationGeneration || !map) return
    currentLocation.value = coord
    const point = new ns.Point(coord.lng, coord.lat)
    if (map.panTo) map.panTo(point, { noAnimation: true })
    else map.centerAndZoom(point, map.getZoom?.() ?? props.zoom)
    rememberView()
    drawLayers(ns)
  } catch (error) {
    if (current !== locationGeneration) return
    const code = (error as { code?: number }).code
    showLocationError(code === 1 ? '定位权限未开启，请在浏览器中允许定位'
      : code === 3 ? '定位超时，请重试' : error instanceof Error ? error.message : '暂时无法定位，请重试')
  } finally { clearTimeout(watchdog); if (current === locationGeneration) locating.value = false }
}
watch(() => props.viewKey, () => { locationGeneration++; locating.value = false; clearLocationNotice() })
watch(() => props.interactionLocked, locked => {
  if (locked) { locationGeneration++; locating.value = false; clearLocationNotice(); pendingPick.value = null }
})
onBeforeUnmount(() => { locationGeneration++; clearLocationNotice() })
function anchorOf(coord: NamedCoord | null | undefined): string {
  return coord ? `${coord.crs}:${coord.lng}:${coord.lat}` : ''
}
function rememberView(): void {
  const point = map?.getCenter?.()
  const zoom = map?.getZoom?.()
  if (!point || !Number.isFinite(point.lng) || !Number.isFinite(point.lat) || !Number.isFinite(zoom)) return
  views.set(activeView, { point: { lng: point.lng, lat: point.lat, crs: 'BD09' }, zoom: zoom!, anchor: activeAnchor })
}

const statusText = computed(() => {
  if (maps.status === 'loading') return '百度底图加载中…'
  if (maps.status === 'error' || localError.value) return '百度底图不可用，请检查网络后重试'
  return ''
})

function clearOverlays(): void {
  if (!map) return
  stopPreviewAnimation(map)
  // F80 残影修复：Label 的 removeOverlay 在部分版本静默失败，逐个移除会留残影；
  // clearOverlays 一次清空全部覆盖物后由 drawLayers 全量重画。
  try {
    map.clearOverlays()
  } catch {
    for (const overlay of overlays) {
      try {
        map.removeOverlay(overlay)
      } catch {
        // 覆盖物已销毁时忽略
      }
    }
  }
  overlays = []
  container.value?.querySelectorAll('[data-map-marker-id]').forEach(el => el.closest('.BMapLabel')?.remove())
}

function drawLayers(BMap: BMapNamespace): void {
  if (!map) return
  clearOverlays()
  markerRevision++
  renderedMarkers = pendingPick.value ? [...props.markers, { coord: pendingPick.value, label: '所选位置', style: 'pill' }] : [...props.markers]
  if (currentLocation.value) renderedMarkers.push({ coord: currentLocation.value, label: '📍', style: 'icon', title: '当前位置',
    place: { name: '当前位置', coord: currentLocation.value, source: 'user-input' } })
  // 图层重绘不改变中心或比例尺；用户手动缩放、平移后保持当前视图。
  overlays = renderLayers(BMap, map, {
    labelBounds: visibleLabelBounds(),
    labelObstacles: blockedLabelAreas(),
    route: props.routes,
    planRoutes: props.planRoutes,
    isoPolygons: props.isoPolygons,
    isoContours: props.isoContours,
    previewContours: props.previewContours,
    referenceCircle: props.referenceCircle,
    heatPolygons: props.heatPolygons,
    coverageCells: props.coverageCells,
    routeBand: props.routeBand,
    markers: renderedMarkers,
    markerRevision,
  })
}

function visibleLabelBounds() {
  const rect = container.value!.getBoundingClientRect()
  const sheet = document.querySelector('.sheet')?.getBoundingClientRect()
  const mobile = window.innerWidth <= 820
  return { left: !mobile && sheet ? Math.max(12, sheet.right - rect.left + 12) : 12,
    right: rect.width - 66, top: 16,
    bottom: mobile && sheet ? Math.min(rect.height - 24, sheet.top - rect.top - 12) : rect.height - 24 }
}

function blockedLabelAreas() {
  const rect = container.value!.getBoundingClientRect()
  return [...document.querySelectorAll('.facility-card,.map-route-card,.map-circle-loading,.shell__layers')]
    .map(node => node.getBoundingClientRect()).filter(r => r.width > 0 && r.height > 0)
    .map(r => ({ left: r.left - rect.left, right: r.right - rect.left, top: r.top - rect.top, bottom: r.bottom - rect.top }))
}

function onViewSettled(): void {
  rememberView()
  const ns = (window as unknown as Record<string, unknown>).BMap as BMapNamespace | undefined
  if (map && ns) drawLayers(ns)
}

async function initMap(): Promise<void> {
  if (!container.value) return
  try {
    const ns = (await maps.ensureLoaded()) as unknown as BMapNamespace
    if (!container.value || map) return
    const instance = new ns.Map(container.value, { enableMapClick: true, enableIconClick: true, enableIconInfoWindow: false, fixCenterWhenResize: true })
    map = instance
    try { instance.setMapStyle?.({ styleJson: MAP_STYLE, merge: true }) }
    catch { console.warn('[map-style] 样式加载失败，保留默认底图') }
    const focus = props.center ?? props.markers[0]?.coord ?? DEFAULT_CENTER
    if (focus.crs !== 'BD09') {
      throw new Error(`地图初始中心只接受 BD09，收到 ${focus.crs}`)
    }
    instance.centerAndZoom(new ns.Point(focus.lng, focus.lat), props.zoom)
    window.addEventListener('map-visible-area-change', alignVisibleArea)
    alignVisibleArea()
    activeView = props.viewKey
    activeAnchor = anchorOf(props.center)
    instance.addEventListener('moveend', onViewSettled)
    instance.addEventListener('zoomend', onViewSettled)
    rememberView()
    clickHandler = (e: BMapClickEvent) => {
      if (props.interactionLocked) return
      if (Date.now() - markerClickedAt < 350) return
      const icon = e.icon ?? e.poi
      if (icon?.name && icon.position && Number.isFinite(icon.position.lng) && Number.isFinite(icon.position.lat)) {
        const place: PlaceRef = { uid: icon.uid || undefined, name: icon.name, coord: { lng: icon.position.lng, lat: icon.position.lat, crs: 'BD09' }, source: 'live-api' }
        if (props.pickPrompt) { knownPick.value = place; pendingPick.value = place.coord }
        else emit('poi-click', place)
        return
      }
      if (e.overlay) return
      if (!props.pickable || e?.point == null) return
      const { lng, lat } = e.point
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
        emit('map-error', '点选位置无效，请重试')
        return
      }
      // JSAPI 默认 BD09 输出；先在地图内确认，再触发业务层真实测时请求。
      knownPick.value = null
      pendingPick.value = { lng, lat, crs: 'BD09' }
    }
    instance.addEventListener('click', clickHandler)
    drawLayers(ns)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    localError.value = message
    emit('map-error', message)
  }
}

function cancelPending(): void {
  pendingPick.value = null
  emit('cancel-pick')
}

function confirmPending(): void {
  if (!pendingPick.value || resolvingPick.value || !pickName.value.trim()) return
  const coord = pendingPick.value
  const name = pickName.value.trim()
  const resolved = pickedPlace.value
  emit('pick', coord, { ...resolved, name, coord, source: resolved?.name === name ? resolved.source : 'user-input' })
  pendingPick.value = null
}

// 只在停下选点后查一次地址；迟到响应不可覆盖另一位置或已取消的选点。
watch(pendingPick, coord => {
  clearTimeout(pickTimer)
  const seq = ++pickGeneration
  pickedPlace.value = null
  pickName.value = ''
  pickError.value = ''
  resolvingPick.value = Boolean(coord)
  const ns = (window as unknown as Record<string, unknown>).BMap as BMapNamespace | undefined
  if (map && ns) drawLayers(ns)
  if (!coord) return
  if (knownPick.value && (!knownPick.value.uid || knownPick.value.address)) {
    pickedPlace.value = knownPick.value
    pickName.value = knownPick.value.name
    resolvingPick.value = false
    return
  }
  pickTimer = setTimeout(async () => {
    try {
      const uid = knownPick.value?.uid
      if (uid ? !app.provider.getLocationDetail : !app.provider.resolveLocation) throw new Error('地址查询不可用，请填写地点名称')
      const response = uid ? await app.provider.getLocationDetail!(uid) : await app.provider.resolveLocation!(coord)
      if (seq !== pickGeneration) return
      pickedPlace.value = response.place
      if (!pickName.value.trim()) pickName.value = response.place.name
    } catch (err) {
      if (seq === pickGeneration) pickError.value = err instanceof Error ? err.message : String(err)
    } finally { if (seq === pickGeneration) resolvingPick.value = false }
  }, 450)
})

function onContainerClick(event: Event): void {
  if (props.interactionLocked) return
  const target = event.target as HTMLElement | null
  const label = target?.closest?.('[data-map-marker-id]') as HTMLElement | null
  if (!label) return
  const [revision, index] = (label.dataset.mapMarkerId || '').split(':').map(Number)
  if (revision !== markerRevision) return
  const marker = renderedMarkers[index]
  if (!marker) return
  markerClickedAt = Date.now()
  event.stopPropagation()
  if (props.pickable && !(marker.payload?.type === 'community-facility' && !props.pickPrompt)) {
    knownPick.value = marker.place ?? { name: marker.title || marker.label, coord: marker.coord, source: 'user-input' }
    pendingPick.value = marker.coord
    return
  }
  if (marker?.payload) emit('marker-click', marker.payload)
}
function onContainerKey(event: KeyboardEvent): void {
  if (event.key !== 'Enter' && event.key !== ' ') return
  if (!(event.target as HTMLElement | null)?.closest('[data-map-marker-id]')) return
  event.preventDefault()
  onContainerClick(event)
}

function zoomInMap(): void {
  map?.zoomIn?.()
}

function zoomOutMap(): void {
  map?.zoomOut?.()
}

watch(() => props.pickable, (enabled) => {
  if (!enabled) pendingPick.value = null
})

watch(
  () => [props.routes, props.planRoutes, props.isoPolygons, props.isoContours, props.previewContours, props.referenceCircle, props.heatPolygons, props.coverageCells, props.routeBand, props.markers, props.interactionLocked],
  () => {
    const ns = (window as unknown as Record<string, unknown>).BMap as BMapNamespace | undefined
    if (map && ns && maps.status === 'ready') drawLayers(ns)
  },
  { deep: true, flush: 'post' },
)

watch(
  () => [props.viewKey, props.center] as const,
  ([key, next]) => {
    if (!map) return
    const BMap = (window as unknown as Record<string, unknown>).BMap as BMapNamespace | undefined
    if (!BMap) return
    if (key !== activeView) {
      rememberView()
      activeView = key
      activeAnchor = anchorOf(next)
      pendingPick.value = null
      const saved = views.get(key)
      const target = saved?.anchor === activeAnchor ? saved.point : next?.crs === 'BD09' ? next : DEFAULT_CENTER
      map.centerAndZoom(new BMap.Point(target.lng, target.lat), saved?.zoom ?? props.zoom)
      if (!saved) alignVisibleArea()
      rememberView()
      return
    }
    if (!next || next.crs !== 'BD09' || anchorOf(next) === activeAnchor) return
    activeAnchor = anchorOf(next)
    // 切换地点仅平移，不把用户选择的缩放级别重置为初始值。
    map.panTo?.(new BMap.Point(next.lng, next.lat), { noAnimation: true })
    alignVisibleArea()
    rememberView()
  },
  { deep: true },
)

onBeforeUnmount(() => {
  clearTimeout(alignTimer)
  window.removeEventListener('map-visible-area-change', alignVisibleArea)
  clearTimeout(pickTimer)
  pickGeneration++
  resizeObserver?.disconnect()
  container.value?.removeEventListener('pointerdown', onContainerClick, true)
  container.value?.removeEventListener('keydown', onContainerKey, true)
  if (map && clickHandler) {
    try {
      map.removeEventListener('click', clickHandler)
      map.removeEventListener('moveend', onViewSettled)
      map.removeEventListener('zoomend', onViewSettled)
    } catch {
      // 卸载时监听已失效则忽略
    }
  }
  clickHandler = null
  clearOverlays()
  try {
    map?.destroy?.()
  } catch {
    // 无 destroy 的版本忽略
  }
  map = null
})

onMounted(() => {
  // pointerdown + capture：JSAPI 会拦截 click 冒泡且部分原生序列不合成 click；
  // 下降阶段的 pointerdown 必达，等价“点一下即响应”。
  container.value?.addEventListener('pointerdown', onContainerClick, true)
  container.value?.addEventListener('keydown', onContainerKey, true)
  if (container.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      const ns = (window as unknown as Record<string, unknown>).BMap as BMapNamespace | undefined
      if (map && ns) {
        const saved = views.get(activeView)
        if (saved) map.centerAndZoom(new ns.Point(saved.point.lng, saved.point.lat), saved.zoom)
        drawLayers(ns)
        alignVisibleArea()
      }
    })
    resizeObserver.observe(container.value)
  }
  void initMap()
})
</script>

<template>
  <figure class="baidu-map">
    <div
      ref="container"
      class="baidu-map__container"
      role="application"
      aria-label="百度地图底图"
    />
    <p
      v-if="statusText"
      class="baidu-map__status"
      role="status"
    >
      {{ statusText }}
      <button
        v-if="maps.status === 'error' || localError"
        type="button"
        @click="localError = ''; initMap()"
      >
        重新加载
      </button>
    </p>
    <div
      class="baidu-map__controls"
      aria-label="地图控制"
    >
      <button
        type="button"
        title="定位到当前位置"
        aria-label="定位到当前位置"
        :disabled="props.interactionLocked || locating || maps.status !== 'ready'"
        :aria-busy="locating"
        @click="locateOnMap"
      >
        <AppIcon
          name="location"
          :class="{ 'is-locating': locating }"
        />
      </button>
      <button
        type="button"
        title="放大地图"
        aria-label="放大地图"
        @click="zoomInMap"
      >
        <AppIcon name="plus" />
      </button>
      <button
        type="button"
        title="缩小地图"
        aria-label="缩小地图"
        @click="zoomOutMap"
      >
        <AppIcon name="minus" />
      </button>
    </div>
    <p
      v-if="locationError"
      class="baidu-map__location-error"
      role="alert"
    >
      {{ locationError }}
      <button
        type="button"
        aria-label="关闭定位提示"
        @click="clearLocationNotice"
      >
        ×
      </button>
    </p>
    <div
      v-if="pickPrompt && !pendingPick"
      class="baidu-map__pick-guide"
      role="status"
    >
      <span>{{ pickPrompt }}</span>
      <button
        type="button"
        aria-label="取消选点"
        @click="emit('cancel-pick')"
      >
        取消
      </button>
    </div>
    <div
      v-if="pendingPick"
      class="baidu-map__pick-banner"
    >
      <div class="baidu-map__pick-info">
        <strong>{{ resolvingPick ? '正在查找地址…' : '确认这个地点' }}</strong>
        <small v-if="pickedPlace?.address">{{ pickedPlace.address }}</small>
        <small
          v-if="pickError"
          role="alert"
        >{{ pickError }}</small>
        <input
          v-model="pickName"
          aria-label="所选地点名称"
          placeholder="地点名称，可修改"
        >
      </div>
      <span class="baidu-map__pick-actions">
        <button
          type="button"
          @click="cancelPending"
        >取消</button>
        <button
          type="button"
          class="primary"
          :disabled="resolvingPick || !pickName.trim()"
          @click="confirmPending"
        >确认位置</button>
      </span>
    </div>
    <figcaption
      v-if="sourceKinds.length"
      class="baidu-map__sources"
    >
      {{ sourceKinds.map(sourceKindLabel).join(' · ') }}
    </figcaption>
  </figure>
</template>

<style scoped>
.baidu-map__location-error { position: absolute; bottom: 12px; left: 12px; right: 12px; z-index: 35; margin: 0; padding: 10px 12px; border: 1px solid #fed7aa; border-radius: 12px; background: #fff7ed; color: #9a3412; font-size: 13px; }
.baidu-map__location-error button { float: right; border: 0; background: transparent; color: inherit; padding: 0 5px; }
.baidu-map__controls button:disabled { opacity: 0.5; cursor: wait; }
</style>

<style scoped>
.baidu-map {
  position: relative;
  margin: 0;
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  background: var(--color-surface);
  overflow: hidden;
  height: 100%;
}

.baidu-map__container {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 240px;
}

.baidu-map__status,
.baidu-map__sources {
  margin: 0;
  padding: 0.5rem 0.75rem;
  color: var(--color-muted);
  font-size: 0.8rem;
}

.baidu-map__controls {
  position: absolute;
  right: 0.6rem;
  top: 0.6rem;
  z-index: 20;
  display: grid;
  gap: 0.35rem;
}

.baidu-map__controls button {
  width: 1.9rem;
  height: 1.9rem;
  border: 1px solid rgb(148 163 184 / 55%);
  border-radius: 0.55rem;
  background: rgb(255 255 255 / 92%);
  color: #334155;
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
  box-shadow: 0 2px 8px rgb(15 23 42 / 12%);
}

.baidu-map__pick-banner {
  position: absolute;
  bottom: 0.65rem;
  left: 0.65rem;
  right: 0.65rem;
  z-index: 21;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: center;
  gap: 0.5rem;
  background: white;
  color: #26344c;
  border-radius: 0.7rem;
  padding: 0.45rem 0.65rem;
  font-size: 0.72rem;
  box-shadow: 0 4px 20px rgb(15 23 42 / 18%);
}
.baidu-map__pick-info{display:grid;gap:6px;min-width:0}.baidu-map__pick-info small{font-size:12px;color:#718098;line-height:1.4;overflow-wrap:anywhere}.baidu-map__pick-info input{width:100%;box-sizing:border-box;min-height:44px;border:1px solid #dfe5ef;border-radius:8px;padding:8px;font:inherit}.baidu-map__pick-actions{justify-content:flex-end}.baidu-map__pick-actions button:disabled{opacity:.5}

.baidu-map__pick-actions { display: flex; gap: 0.35rem; flex-shrink: 0; }
.baidu-map__pick-actions button {
  border: 1px solid #dfe5ef;
  border-radius: 0.35rem;
  padding: 0.2rem 0.45rem;
  background: white;
  color: #386ddd;
  font-size: 0.68rem;
}
.baidu-map__pick-actions .primary { background: #2563eb; border-color: #2563eb; color: #fff; }
.baidu-map__pick-guide { position:absolute;top:.65rem;left:.65rem;right:3.5rem;z-index:21;display:flex;align-items:center;gap:10px;background:#fffffff5;border:1px solid #e2e8f0;border-radius:12px;padding:4px 6px 4px 12px;font-size:12px;line-height:1.5;box-shadow:0 3px 12px #0f172a12 }
.baidu-map__pick-guide span{flex:1;min-width:0;color:#536781}
.baidu-map__pick-guide button { flex:none;margin-left:auto;min-height:40px;padding:6px 10px;color:#386ddd;font:inherit;background:transparent;border:0;border-radius:8px }
.baidu-map__pick-actions button { min-height:44px }
.baidu-map__controls{padding:3px;border-radius:16px;background:#ffffffed;box-shadow:0 4px 18px #17243a12;gap:0}.baidu-map__controls button{width:40px;height:42px;min-height:42px;display:grid;place-items:center;border:0;border-radius:10px;background:transparent;box-shadow:none;color:#40516b;transition:background .15s}.baidu-map__controls button+button{border-top:1px solid #edf1f7;border-radius:0}.baidu-map__controls button:active{background:#edf4ff}.is-locating{animation:location-pulse 1.2s ease-in-out infinite}@keyframes location-pulse{50%{opacity:.35}}@media(prefers-reduced-motion:reduce){.is-locating{animation:none}.baidu-map__controls button{transition:none}}
</style>
