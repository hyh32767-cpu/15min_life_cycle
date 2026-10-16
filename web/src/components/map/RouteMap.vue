<script setup lang="ts">
import { computed } from 'vue'

import { polygonFromRays } from '@/domain/geo'
import { assertSameCrs } from '@/domain/mapCrs'
import { boundsOf, projectPoint, projectPolyline } from '@/domain/projection'
import type { NamedCoord, SourceKind } from '@/domain/types'

interface MapMarker {
  coord: NamedCoord
  label: string
  kind: 'start' | 'end' | 'poi' | 'entry' | 'return'
  sourceKind?: SourceKind
}

interface IsochroneLayer {
  center: NamedCoord
  radiiM: Record<string, number>
  status: string
  sourceKind?: SourceKind
}

const props = withDefaults(defineProps<{
  geometry?: NamedCoord[]
  detourGeometries?: NamedCoord[][]
  markers?: MapMarker[]
  isochrone?: IsochroneLayer | null
  isochrones?: IsochroneLayer[]
  width?: number
  height?: number
  routeSourceKind?: SourceKind | null
  detourSourceKinds?: (SourceKind | null)[]
  // F55：独立等时圈地图点选。pickable 开启后点击空白处逆投影为起点坐标（与当前 bounds 同系）。
  pickable?: boolean
  pickHint?: string
}>(), {
  geometry: () => [],
  detourGeometries: () => [],
  markers: () => [],
  isochrone: null,
  isochrones: () => [],
  width: 560,
  height: 320,
  routeSourceKind: null,
  detourSourceKinds: () => [],
  pickable: false,
  pickHint: '点击设为起点',
})

const emit = defineEmits<{
  (event: 'pick', coord: NamedCoord): void
  (event: 'pick-error', message: string): void
}>()

// F55：SVG 像素逆投影回经纬度；bounds 缺失或混系时拒绝点选，不伪造坐标。
function pickFromEvent(event: MouseEvent): void {
  if (!props.pickable) return
  const currentBounds = bounds.value
  if (!currentBounds) {
    emit('pick-error', crsError.value || '暂无地图范围，无法点选')
    return
  }
  const target = event.currentTarget as SVGSVGElement | null
  if (!target) return
  const rect = target.getBoundingClientRect()
  const px = ((event.clientX - rect.left) / rect.width) * props.width
  const py = ((event.clientY - rect.top) / rect.height) * props.height
  const spanX = currentBounds.maxLng - currentBounds.minLng || 1
  const spanY = currentBounds.maxLat - currentBounds.minLat || 1
  const lng = currentBounds.minLng + (px / props.width) * spanX
  const lat = currentBounds.maxLat - (py / props.height) * spanY
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
    emit('pick-error', '点选位置无效，请重试')
    return
  }
  const crs = allCoords.value[0]?.crs ?? 'BD09'
  emit('pick', { lng, lat, crs })
}

const isochroneLayers = computed<IsochroneLayer[]>(() => [
  ...(props.isochrone ? [props.isochrone] : []),
  ...props.isochrones,
])

// T110：同一 bounds 内的坐标必须同系；混系拒绝投影，不静默混算。
const allCoords = computed<NamedCoord[]>(() => [
  ...props.geometry,
  ...props.detourGeometries.flat(),
  ...props.markers.map((marker) => marker.coord),
  ...isochroneLayers.value.map((layer) => layer.center),
])

const crsError = computed(() => {
  try {
    assertSameCrs(allCoords.value)
    return ''
  } catch (err) {
    return err instanceof Error ? err.message : String(err)
  }
})

const bounds = computed(() => {
  if (crsError.value) return null
  return boundsOf([
    ...props.geometry,
    ...props.detourGeometries.flat(),
    ...props.markers.map((marker) => marker.coord),
    ...isochroneLayers.value.flatMap((layer) => polygonFromRays(layer.center, layer.radiiM)),
  ])
})

const routePoints = computed(() => {
  const currentBounds = bounds.value
  if (!currentBounds || !props.geometry.length) return ''
  return projectPolyline(props.geometry, currentBounds, props.width, props.height)
})

const detourPaths = computed(() => {
  const currentBounds = bounds.value
  if (!currentBounds) return []
  return props.detourGeometries
    .filter((geometry) => geometry.length > 1)
    .map((geometry) => projectPolyline(geometry, currentBounds, props.width, props.height))
})

const isochronePolygons = computed(() => {
  const currentBounds = bounds.value
  if (!currentBounds) return []
  return isochroneLayers.value.map((layer, index) => {
    const polygon = polygonFromRays(layer.center, layer.radiiM)
    if (polygon.length < 3) return null
    return {
      index,
      status: layer.status,
      points: projectPolyline([...polygon, polygon[0]], currentBounds, props.width, props.height),
    }
  }).filter((item): item is { index: number; status: string; points: string } => item !== null)
})

const markerPositions = computed(() => {
  const currentBounds = bounds.value
  if (!currentBounds) return []
  return props.markers.map((marker) => ({
    ...marker,
    ...projectPoint(marker.coord, currentBounds, props.width, props.height),
  }))
})

const modeLabel = computed(() => '实时示意（百度底图未接入）')

const note = computed(() => {
  const sources = new Set<SourceKind>()
  for (const marker of props.markers) {
    if (marker.sourceKind) sources.add(marker.sourceKind)
  }
  if (props.routeSourceKind) sources.add(props.routeSourceKind)
  for (const kind of props.detourSourceKinds) {
    if (kind) sources.add(kind)
  }
  for (const layer of isochroneLayers.value) {
    if (layer.sourceKind) sources.add(layer.sourceKind)
  }
  const parts: string[] = []
  if (modeLabel.value) parts.push(modeLabel.value)
  parts.push(sources.size ? `来源：${Array.from(sources).join(' / ')}` : '来源：计算结果')
  return parts.join('；')
})
</script>

<template>
  <figure class="route-map">
    <svg
      v-if="bounds"
      :viewBox="`0 0 ${width} ${height}`"
      role="img"
      :aria-label="pickable ? `步行路线与沿途地点（${pickHint}）` : '步行路线与沿途地点'"
      :class="{ 'route-map__pickable': pickable }"
      @click="pickFromEvent"
    >
      <rect
        x="0"
        y="0"
        :width="width"
        :height="height"
        class="route-map__bg"
      />
      <polygon
        v-for="layer in isochronePolygons"
        :key="`iso-${layer.index}`"
        :points="layer.points"
        :class="`route-map__isochrone route-map__isochrone--${layer.index % 3}`"
      />
      <polyline
        v-if="routePoints"
        :points="routePoints"
        class="route-map__route"
        fill="none"
      />
      <polyline
        v-for="(path, index) in detourPaths"
        :key="`detour-${index}`"
        :points="path"
        class="route-map__detour"
        fill="none"
      />
      <g
        v-for="(marker, markerIndex) in markerPositions"
        :key="`m-${markerIndex}-${marker.kind}-${marker.coord.lng.toFixed(5)},${marker.coord.lat.toFixed(5)}`"
      >
        <circle
          :cx="marker.x"
          :cy="marker.y"
          r="6"
          :class="`route-map__marker route-map__marker--${marker.kind}`"
        />
        <text
          :x="marker.x + 8"
          :y="marker.y - 6"
          class="route-map__label"
        >
          {{ marker.label }}
        </text>
      </g>
    </svg>
    <p
      v-else-if="crsError"
      class="route-map__empty"
    >
      {{ crsError }}
    </p>
    <p
      v-else
      class="route-map__empty"
    >
      {{ pickable ? '选定起点后在此显示示意图；首次起点请用地址搜索或自定位。' : '暂时没有可显示的路线' }}
    </p>
    <figcaption>{{ note }}</figcaption>
  </figure>
</template>

<style scoped>
.route-map {
  margin: 0;
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  background: var(--color-surface);
  overflow: hidden;
}

.route-map svg {
  display: block;
  width: 100%;
  height: auto;
}

.route-map__bg {
  fill: #f3f4f6;
}

.route-map__route {
  stroke: #2563eb;
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.route-map__detour {
  stroke: #f97316;
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 6 4;
}

.route-map__isochrone {
  fill: rgb(37 99 235 / 14%);
  stroke: #1d4ed8;
  stroke-width: 1.5;
  stroke-dasharray: 4 3;
}

.route-map__isochrone--1 {
  fill: rgb(249 115 22 / 14%);
  stroke: #ea580c;
}

.route-map__isochrone--2 {
  fill: rgb(139 92 246 / 14%);
  stroke: #7c3aed;
}

.route-map__marker--start {
  fill: #16a34a;
}

.route-map__marker--end {
  fill: #dc2626;
}

.route-map__marker--poi {
  fill: #f59e0b;
}

.route-map__marker--entry {
  fill: #0ea5e9;
}

.route-map__marker--return {
  fill: #8b5cf6;
}

.route-map__label {
  font-size: 10px;
  fill: #111827;
}

.route-map__empty,
figcaption {
  margin: 0;
  padding: 0.5rem 0.75rem;
  color: var(--color-muted);
  font-size: 0.8rem;
}
</style>
