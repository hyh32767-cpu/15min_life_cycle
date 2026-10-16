<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppShell from '@/components/shell/AppShell.vue'
import CircleLoading from '@/components/CircleLoading.vue'
import GlobalMap from '@/components/map/GlobalMap.vue'
import LedgerReport from '@/components/report/LedgerReport.vue'
import { useGlobalMapLayers } from '@/components/map/useGlobalMapLayers'
import { useCommuteStore } from '@/stores/commute'
import { useIsochroneStore } from '@/stores/isochrone'
import { useMapInteractionStore } from '@/stores/mapInteraction'
import { useRouteBandStore } from '@/stores/routeBand'
import type { NamedCoord, PlaceRef } from '@/domain/types'
import MapRouteCard from '@/components/map/MapRouteCard.vue'
import { useMapRouteStore } from '@/stores/mapRoute'
import { useCommunityRadiusStore } from '@/stores/communityRadius'
import CommunityFacilityCard from '@/components/map/CommunityFacilityCard.vue'

const { routes, planRoutes, isoPolygons, isoContours, previewContours, referenceCircle, heatPolygons, coverageCells, routeBand, markers, center } = useGlobalMapLayers()
const route = useRoute()
const router = useRouter()
const isoStore = useIsochroneStore()
const mapInteraction = useMapInteractionStore()
const commuteStore = useCommuteStore()
const band = useRouteBandStore()
const mapRoute = useMapRouteStore()
const community = useCommunityRadiusStore()
watch(() => community.serviceId, () => mapRoute.clear())
watch([() => route.name, () => commuteStore.category, () => commuteStore.company, () => commuteStore.home, () => isoStore.origin, () => mapInteraction.pickTarget], () => mapRoute.clear(), { deep: true })
function routeOrigin(): NamedCoord | null {
  return route.name === 'community' ? isoStore.origin : commuteStore.company?.naviCoord ?? commuteStore.company?.coord ?? null
}
function onMapPoi(place: PlaceRef): void { if (!isoStore.busy) void mapRoute.open(place, routeOrigin(), true) }
async function addMapWaypoint(): Promise<void> {
  if (isoStore.busy) return
  const place = mapRoute.destination
  if (!place) return
  mapRoute.clear()
  await router.push('/')
  mapInteraction.waypointRequest = { place }
}
async function useMapDestination(): Promise<void> {
  if (isoStore.busy) return
  const place = mapRoute.destination
  if (!place) return
  mapRoute.clear()
  await router.push('/')
  commuteStore.home = place
  commuteStore.homeQuery = place.name
  commuteStore.homeCandidates = [place]
}

// 地图 POI 图标点击 → 通勤页打开单店详情（详情里显示名称）。
function onMarkerClick(payload: { type: string; index?: number; placeKey?: string }): void {
  if (isoStore.busy || mapInteraction.pickTarget) return
  if (payload.type === 'life-center' && (route.name === 'community' || route.name === 'isochrone')) {
    community.closeFacility()
    mapRoute.clear()
    return
  }
  if (payload.type === 'community-facility' && route.name === 'community' && payload.placeKey) {
    community.selectFacility(payload.placeKey)
    mapRoute.clear()
  }
  if (payload.type === 'poi' && payload.index != null) {
    const place = commuteStore.rankedPois[payload.index]?.place
    if (!place || payload.placeKey !== commuteStore.placeIdentity(place)) return
    void mapRoute.open(place, routeOrigin())
  }
  if (payload.type === 'band-center' && payload.index != null) band.selectedIndex = payload.index
}

// 社区体检承载等时圈入口；旧 /isochrone 路由保留为兼容详情页。
const mapPickable = computed(() => !isoStore.busy && Boolean(mapInteraction.pickTarget))

function onGlobalPick(coord: NamedCoord, place?: PlaceRef): void {
  if (isoStore.busy) return
  if (mapInteraction.pickTarget) {
    if (mapInteraction.pickTarget === 'community-center') isoStore.setOrigin(coord, place?.name || '地图地点')
    mapInteraction.completePick(coord, place)
    return
  }
  if (route.name !== 'isochrone' && route.name !== 'community') return
  isoStore.setOrigin(coord, place?.name || '地图地点')
}

function onMapError(message: string): void {
  // 全局地图错误由 AppShell 底栏统一展示；此处仅控制台留痕，不弹假 toast。
  console.warn('[global-map]', message)
}
</script>

<template>
  <AppShell>
    <template #map>
      <GlobalMap
        :layers="{ routes, planRoutes, isoPolygons, isoContours, previewContours, referenceCircle, heatPolygons, coverageCells, routeBand, markers }"
        :center="center"
        :view-key="String(route.name ?? 'commute')"
        :pickable="mapPickable"
        :interaction-locked="isoStore.busy"
        :pick-prompt="mapInteraction.pickTarget ? '在地图上点击要选择的地点' : ''"
        @cancel-pick="mapInteraction.pickTarget = null"
        @pick="onGlobalPick"
        @map-error="onMapError"
        @marker-click="onMarkerClick"
        @poi-click="onMapPoi"
      />
      <MapRouteCard
        v-if="!isoStore.busy"
        @waypoint="addMapWaypoint"
        @destination="useMapDestination"
      />
      <Transition name="circle-status">
        <CircleLoading
          v-if="isoStore.busy && (route.name === 'community' || route.name === 'isochrone')"
          class="map-circle-loading measurement-status"
          compact
          :heat="isoStore.heatLoading"
          :frontier="isoStore.result?.frontier ?? undefined"
          :directions="isoStore.result?.status === 'complete' ? Object.keys(isoStore.result.radiiM).length : 0"
        />
      </Transition>
      <CommunityFacilityCard
        v-if="!isoStore.busy && route.name === 'community' && !mapRoute.destination && !mapInteraction.pickTarget"
        @route="community.selectedFacility && mapRoute.open(community.selectedFacility, isoStore.origin)"
      />
    </template>
    <template #report>
      <LedgerReport />
    </template>
    <RouterView v-slot="{ Component }">
      <KeepAlive :max="4">
        <component :is="Component" />
      </KeepAlive>
    </RouterView>
  </AppShell>
</template>

<style>
.map-circle-loading{position:absolute;z-index:22;left:50%;top:max(16px,env(safe-area-inset-top));transform:translateX(-50%);width:max-content;max-width:calc(100% - 32px);box-sizing:border-box;pointer-events:none}.circle-status-enter-active,.circle-status-leave-active{transition:opacity .2s,margin-top .2s}.circle-status-enter-from,.circle-status-leave-to{opacity:0;margin-top:-8px}@media(min-width:821px){.map-circle-loading{left:calc(50% + 210px);max-width:calc(100% - 470px)}}@media(prefers-reduced-motion:reduce){.circle-status-enter-active,.circle-status-leave-active{transition:none}}
</style>
