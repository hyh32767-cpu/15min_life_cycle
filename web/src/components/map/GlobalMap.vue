<!-- 兼容旧引用的薄封装。正式地图生命周期与覆盖物渲染统一由 BaiduMap/baiduAdapter 负责。 -->
<script setup lang="ts">
import BaiduMap from './BaiduMap.vue'
import type { NamedCoord, PlaceRef } from '@/domain/types'

import type { MapMarker } from './useGlobalMapLayers'

export type { MapMarker }

export interface GlobalMapLayer {
  routes: NamedCoord[][]
  planRoutes: NamedCoord[][]
  isoPolygons: NamedCoord[][]
  isoContours?: NamedCoord[][]
  previewContours?: NamedCoord[][]
  referenceCircle?: { center: NamedCoord; radiusM: number } | null
  heatPolygons?: { ring: NamedCoord[]; seconds: number; mesh?: boolean; estimated?: boolean; contours?: NamedCoord[][] }[]
  coverageCells?: { ring: NamedCoord[]; status: 'covered' | 'blind' | 'unknown' }[]
  routeBand?: { fills: NamedCoord[][]; boundaries: NamedCoord[][]; seconds: number } | null
  markers: MapMarker[]
}

const props = withDefaults(defineProps<{
  layers: GlobalMapLayer
  center?: NamedCoord | null
  viewKey?: string
  zoom?: number
  pickable?: boolean
  interactionLocked?: boolean
  pickPrompt?: string
}>(), {
  center: null,
  viewKey: 'commute',
  zoom: 15,
  pickable: false,
  interactionLocked: false,
  pickPrompt: '',
})

const emit = defineEmits<{
  (event: 'pick', coord: NamedCoord, place?: PlaceRef): void
  (event: 'map-error', message: string): void
  (event: 'marker-click', payload: { type: string; index?: number; placeKey?: string }): void
  (event: 'poi-click', place: PlaceRef): void
  (event: 'cancel-pick'): void
}>()
</script>

<template>
  <BaiduMap
    :routes="props.layers.routes"
    :plan-routes="props.layers.planRoutes"
    :iso-polygons="props.layers.isoPolygons"
    :iso-contours="props.layers.isoContours"
    :preview-contours="props.layers.previewContours"
    :reference-circle="props.layers.referenceCircle"
    :heat-polygons="props.layers.heatPolygons"
    :coverage-cells="props.layers.coverageCells"
    :route-band="props.layers.routeBand"
    :markers="props.layers.markers"
    :center="props.center"
    :view-key="props.viewKey"
    :zoom="props.zoom"
    :pickable="props.pickable"
    :interaction-locked="props.interactionLocked"
    :pick-prompt="props.pickPrompt"
    @cancel-pick="emit('cancel-pick')"
    @pick="(coord, place) => emit('pick', coord, place)"
    @map-error="emit('map-error', $event)"
    @marker-click="emit('marker-click', $event)"
    @poi-click="emit('poi-click', $event)"
  />
</template>
