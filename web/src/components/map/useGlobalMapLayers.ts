// 实测边界共用射线几何；快速预估独立标识，不参加覆盖分析。
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { polygonFromRays } from '@/domain/geo'
import { serviceIcons as SERVICE_ICONS } from '@/domain/serviceIcons'
import type { LayerMarker } from './baiduAdapter'
import type { NamedCoord } from '@/domain/types'
import { useCommuteStore } from '@/stores/commute'
import { useIsochroneStore } from '@/stores/isochrone'
import { useMapInteractionStore } from '@/stores/mapInteraction'
import { usePlanStore } from '@/stores/plan'
import { useCommunityRadiusStore } from '@/stores/communityRadius'
import { useRouteBandStore } from '@/stores/routeBand'
import { useMapRouteStore } from '@/stores/mapRoute'

export type MapMarker = LayerMarker

export interface GlobalMapLayers {
  routes: NamedCoord[][]
  planRoutes: NamedCoord[][]
  isoPolygons: NamedCoord[][]
  isoContours?: NamedCoord[][]
  markers: MapMarker[]
}

const CATEGORY_ICONS: Record<string, string> = {
  药店: '💊',
  超市: '🛒',
  美食: '🍜',
  商场: '🏬',
  快递: '📦',
}

function entryOf(place: { coord: NamedCoord; naviCoord?: NamedCoord }): NamedCoord {
  return place.naviCoord ?? place.coord
}

export function useGlobalMapLayers() {
  const commute = useCommuteStore()
  const isoStore = useIsochroneStore()
  const mapInteraction = useMapInteractionStore()
  const plan = usePlanStore()
  const route = useRoute()
  const communityRadius = useCommunityRadiusStore()
  const band = useRouteBandStore()
  const mapRoute = useMapRouteStore()

  const isIsochroneSurface = computed(() => route.name === 'community' || route.name === 'isochrone')
  const isCommuteSurface = computed(() => route.name === 'commute')

  const routeBand = computed(() => isCommuteSurface.value && band.enabled && band.result?.fills.length
    ? { fills: band.result.fills, boundaries: band.result.displayContours?.length ? band.result.displayContours : band.result.boundaries, seconds: band.thresholdSeconds } : null)
  const coverageCells = computed(() => [])

  const heatPolygons = computed<{ ring: NamedCoord[]; seconds: number; estimated?: boolean; contours?: NamedCoord[][] }[]>(() => {
    if (!isIsochroneSurface.value || isoStore.origin?.crs !== 'BD09') return []
    if (isoStore.result?.frontier) {
      const layers = isoStore.heatLayers.length ? isoStore.heatLayers : [isoStore.result]
      return layers.filter(l => l.status === 'complete').flatMap(layer => layer.frontier
        ? layer.frontier.fills.map((ring, i) => ({ ring, seconds: layer.thresholdSeconds, mesh: true,
          contours: i === 0 ? layer.reconstruction?.contours : [] })) : [])
    }
    if (isoStore.backgroundStatus === 'running' && isoStore.result?.status !== 'complete' && isoStore.l2Preview) {
      const ring = polygonFromRays(isoStore.origin, isoStore.l2Preview.radiiM)
      return ring.length >= 3 ? [{ ring, seconds: isoStore.thresholdSeconds, estimated: true }] : []
    }
    return isoStore.heatLayers.filter(layer => [300, 600, 900].includes(layer.thresholdSeconds)).flatMap(layer => {
      const ring = polygonFromRays(isoStore.origin!, layer.radiiM)
      return layer.status === 'complete' && ring.length >= 3 ? [{ ring, seconds: layer.thresholdSeconds, contours: layer.reconstruction?.contours }] : []
    })
  })

  const planRoutes = computed<NamedCoord[][]>(() => {
    if (!isCommuteSurface.value) return []
    if (mapRoute.destination) return []
    const geometry = plan.planRouteGeometry
    return geometry.length >= 2 ? [geometry] : []
  })

  const routes = computed<NamedCoord[][]>(() => {
    if (mapRoute.destination) return mapRoute.result?.route.geometry?.length ? [mapRoute.result.route.geometry] : []
    if (!isCommuteSurface.value) return []
    if (planRoutes.value.length) return []
    const out: NamedCoord[][] = []
    const base = commute.route?.route.geometry
    if (base && base.length >= 2) out.push(base)
    for (const geometry of isCommuteSurface.value ? commute.detourGeometries : []) {
      if (geometry.length >= 2) out.push(geometry)
    }
    return out
  })

  const isoPolygons = computed<NamedCoord[][]>(() => {
    const out: NamedCoord[][] = []
    const selected = commute.selectedPoiIndex != null
      ? commute.rankedPois[commute.selectedPoiIndex] ?? null
      : null
    if (isCommuteSurface.value && commute.isochrone?.status === 'complete' && selected) {
      const ring = polygonFromRays(entryOf(selected.place), commute.isochrone.radiiM)
      if (ring.length >= 3) out.push(ring)
    }
    for (const index of isCommuteSurface.value ? commute.compareIndices : []) {
      const result = commute.compareIsochrones[index]
      const poi = commute.rankedPois[index]
      if (result?.status !== 'complete' || !poi) continue
      const ring = polygonFromRays(entryOf(poi.place), result.radiiM)
      if (ring.length >= 3) out.push(ring)
    }
    const activeIso = isoStore.result ?? isoStore.l2Preview
    if (
      isIsochroneSurface.value &&
      !heatPolygons.value.length &&
      activeIso &&
      activeIso.status === 'complete' &&
      isoStore.origin?.crs === 'BD09'
    ) {
      const ring = polygonFromRays(isoStore.origin, activeIso.radiiM)
      const polygonId = polygonSignature(ring)
      if (ring.length >= 3 && !out.some((polygon) => polygonSignature(polygon) === polygonId)) out.push(ring)
    }
    const unique = new Map<string, NamedCoord[]>()
    for (const polygon of out) unique.set(polygonSignature(polygon), polygon)
    return [...unique.values()]
  })

  const markers = computed<GlobalMapLayers['markers']>(() => {
    const out: GlobalMapLayers['markers'] = []
    if (isIsochroneSurface.value && isoStore.result?.frontier && isoStore.result.status !== 'complete') {
      for (const sample of isoStore.result.frontier.samples) out.push({ coord: sample.coord, label: '', probe: sample.state })
    }
    if (isIsochroneSurface.value && isoStore.origin?.crs === 'BD09') {
      out.push({ coord: isoStore.origin, label: '📍', caption: isoStore.originLabel || '地图地点',
        subtitle: '生活圈中心', kind: 'center', priority: 100, title: isoStore.originLabel || '生活圈中心', payload: { type: 'life-center' } })
    }
    if (!isIsochroneSurface.value && route.name !== 'cases' && commute.company) {
      out.push({ coord: entryOf(commute.company), label: '起点', style: 'pill' })
    }
    if (!isIsochroneSurface.value && route.name !== 'cases' && commute.home) {
      out.push({ coord: entryOf(commute.home), label: '终点', style: 'pill' })
    }
    for (const [index, item] of (isCommuteSurface.value ? commute.rankedPois.slice(0, 16) : []).entries()) {
      if (band.onlyMeasured && !band.includes(entryOf(item.place))) continue
      out.push({
        coord: entryOf(item.place),
        label: CATEGORY_ICONS[commute.category] ?? '📍',
        caption: item.place.name,
        subtitle: item.extraTravelSeconds == null ? '绕行时间待确认' : item.extraTravelSeconds <= 0 ? '就在沿途' : `多走 ${Math.ceil(item.extraTravelSeconds / 60)} 分钟`,
        kind: 'facility', active: commute.selectedPoiIndex === index, priority: 20 - index,
        style: 'icon',
        title: item.place.name,
        place: item.place,
        payload: { type: 'poi', index, placeKey: commute.placeIdentity(item.place) },
      })
    }
    for (const node of isCommuteSurface.value && band.enabled ? band.result?.nodes ?? [] : []) {
      out.push({ coord: node.origin, label: ['①', '②', '③', '④', '⑤'][node.index] ?? '○',
        style: 'icon', payload: { type: 'band-center', index: node.index } })
    }
    for (const [placeId, coord] of Object.entries(isCommuteSurface.value ? plan.nodeCoords : {})) {
      if (placeId === 'S' || placeId === 'H') continue
      const index = plan.tasks.findIndex(task => task.options.some(option => option.placeId === placeId))
      out.push({ coord, label: index >= 0 && plan.visitOrder.length ? `途经${index + 1}` : '📌', style: plan.visitOrder.length ? 'pill' : 'icon', title: plan.placeName(placeId) })
    }
    for (const place of route.name === 'community' && mapInteraction.showFacilities ? communityRadius.facilities : []) {
      out.push({ coord: entryOf(place), label: SERVICE_ICONS[communityRadius.serviceId] ?? '📍',
        caption: place.name, subtitle: communityRadius.serviceLabel, kind: 'facility',
        active: communityRadius.selectedFacility != null && communityRadius.placeKey(communityRadius.selectedFacility) === communityRadius.placeKey(place),
        style: 'icon', title: `${place.name} · ${communityRadius.serviceLabel} · 参评设施`, place,
        payload: { type: 'community-facility', placeKey: communityRadius.placeKey(place) } })
    }
    if (mapInteraction.selectedCoord && (
      (isCommuteSurface.value && mapInteraction.selectedFor === 'manual-plan') ||
      (route.name === 'community' && mapInteraction.selectedFor === 'community-facility')
    )) {
      out.push({ coord: mapInteraction.selectedCoord, label: '新选位置' })
    }
    const deduplicated = new Map<string, (typeof out)[number]>()
    if (route.name === 'community' && mapInteraction.showBlindSpots) {
      for (const point of commute.communityGridPoints.filter(item => !item.covered)) {
        out.push({ coord: point.coord, label: '!', title: '未覆盖采样点' })
      }
    }
    if (mapRoute.destination) out.push({ coord: entryOf(mapRoute.destination), label: mapRoute.destination.name, style: 'pill' })
    for (const marker of out) {
      const key = `${coordinateKey(marker.coord)}|${marker.label}`
      if (!deduplicated.has(key)) deduplicated.set(key, marker)
    }
    return [...deduplicated.values()]
  })

  const center = computed<NamedCoord | null>(() => {
    if (mapRoute.destination?.coord.crs === 'BD09') return entryOf(mapRoute.destination)
    if (route.name === 'community' && communityRadius.focus) return communityRadius.focus
    if (isIsochroneSurface.value && isoStore.origin?.crs === 'BD09') return isoStore.origin
    if (isCommuteSurface.value && band.focus) return band.focus
    if (!isIsochroneSurface.value && route.name !== 'cases' && commute.company) return entryOf(commute.company)
    return markers.value[0]?.coord ?? null
  })

  const isoContours = computed(() => isIsochroneSurface.value && !heatPolygons.value.length
    && (isoStore.result?.frontier || isoStore.result?.status === 'complete') ? isoStore.result?.reconstruction?.contours ?? [] : [])
  const previewContours = computed(() => isIsochroneSurface.value && isoStore.result?.status !== 'complete'
    ? isoStore.result?.frontier?.previewContours ?? [] : isCommuteSurface.value && band.enabled
      ? band.result?.nodes.flatMap(node => node.backgroundStatus === 'running' ? node.previewContours ?? [] : []) ?? [] : [])
  const referenceCircle = computed(() => {
    if (isIsochroneSurface.value && isoStore.origin?.crs === 'BD09' && isoStore.result?.frontier)
      return { center: isoStore.origin, radiusM: isoStore.result.frontier.radiusM ?? isoStore.result.frontier.halfM }
    const running = isCommuteSurface.value && band.enabled ? band.result?.nodes.find(node => node.backgroundStatus === 'running') : null
    return running ? { center: running.origin, radiusM: 1100 } : null
  })

  return { routes, planRoutes, isoPolygons, isoContours, previewContours, referenceCircle, heatPolygons, coverageCells, routeBand, markers, center }
}

function coordinateKey(coord: NamedCoord): string {
  return `${coord.crs}:${coord.lng.toFixed(6)},${coord.lat.toFixed(6)}`
}

function polygonSignature(points: NamedCoord[]): string {
  return points.map(coordinateKey).join('|')
}
