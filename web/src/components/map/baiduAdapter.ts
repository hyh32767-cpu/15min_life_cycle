// T110/UI-M：百度 JSAPI 4.0 地图适配层（无 npm 依赖，script 动态加载）。
// 只做底图/点选/覆盖物；业务 POI/路线/矩阵/等时圈仍经 /api，坐标一律具名 BD09。
import type { NamedCoord, PlaceRef } from '@/domain/types'
import { placeMapLabels, type LabelBounds } from './mapTheme'
import { destAt } from '@/domain/geo'
import { roundContour } from './roundContour'

export interface BMapPointLike {
  lng: number
  lat: number
}

export interface BMapNamespace {
  Convertor?: new () => {
    translate(points: BMapPointLike[], from: number, to: number,
      callback: (result: { status: number; points?: BMapPointLike[] }) => void): void
  }
  Map: new (container: string | HTMLElement, opts?: Record<string, unknown>) => BMapInstance
  Point: new (lng: number, lat: number) => BMapPointLike
  Marker: new (point: BMapPointLike, opts?: Record<string, unknown>) => BMapOverlay
  Label?: new (text: string, opts?: Record<string, unknown>) => BMapOverlay & {
    setStyle?: (style: Record<string, string>) => void
  }
  Polyline: new (points: BMapPointLike[], opts?: Record<string, unknown>) => BMapOverlay
  Polygon: new (points: BMapPointLike[], opts?: Record<string, unknown>) => BMapOverlay
}

export interface BMapInstance {
  setMapStyle?: (style: { styleJson: unknown[]; merge?: boolean }) => void
  centerAndZoom(point: BMapPointLike, zoom: number): void
  panTo?: (point: BMapPointLike, options?: { noAnimation?: boolean }) => void
  getCenter?: () => BMapPointLike
  getZoom?: () => number
  pointToPixel?: (point: BMapPointLike) => { x: number; y: number }
  panBy?: (x: number, y: number, options?: { noAnimation?: boolean }) => void
  zoomIn?: () => void
  zoomOut?: () => void
  setViewport(points: BMapPointLike[], options?: Record<string, unknown>): void
  addOverlay(overlay: BMapOverlay): void
  removeOverlay(overlay: BMapOverlay): void
  clearOverlays(): void
  addEventListener(event: string, handler: (e: BMapClickEvent) => void): void
  removeEventListener(event: string, handler: (e: BMapClickEvent) => void): void
  destroy?: () => void
}

export interface BMapClickEvent {
  point: BMapPointLike
  overlay?: BMapOverlay
  icon?: { name: string; position: BMapPointLike; uid: string }
  poi?: { name: string; position: BMapPointLike; uid: string }
}

export type BMapOverlay = object

const previewFrames = new WeakMap<BMapInstance, number>()
const previewShapes = new WeakMap<BMapInstance, NamedCoord[][]>()
export function stopPreviewAnimation(map: BMapInstance): void {
  const frame = previewFrames.get(map)
  if (frame != null) cancelAnimationFrame(frame)
  previewFrames.delete(map)
}

export interface LayerMarker {
  probe?: 'reachable' | 'outside' | 'unknown' | 'no_route'
  coord: NamedCoord
  label: string
  style?: 'icon' | 'pill'
  title?: string
  caption?: string
  subtitle?: string
  active?: boolean
  kind?: 'center' | 'facility'
  priority?: number
  place?: PlaceRef
  payload?: { type: string; index?: number; placeKey?: string }
}

export interface LayerInput {
  route?: NamedCoord[][]
  /** 方案动线：按停站顺序拼接的单条连续折线，与基准线区分颜色。 */
  planRoutes?: NamedCoord[][]
  isoPolygons?: NamedCoord[][]
  isoContours?: NamedCoord[][]
  previewContours?: NamedCoord[][]
  referenceCircle?: { center: NamedCoord; radiusM: number } | null
  heatPolygons?: { ring: NamedCoord[]; seconds: number; mesh?: boolean; estimated?: boolean; contours?: NamedCoord[][] }[]
  routeBand?: { fills: NamedCoord[][]; boundaries: NamedCoord[][]; seconds: number } | null
  coverageCells?: { ring: NamedCoord[]; status: 'covered' | 'blind' | 'unknown' }[]
  markers?: LayerMarker[]
  markerRevision?: number
  labelBounds?: LabelBounds
  labelObstacles?: LabelBounds[]
}

const MARKER_COLORS = ['#2563eb', '#ea580c', '#7c3aed', '#16a34a', '#dc2626'] as const

export function gpsToBaidu(BMap: BMapNamespace, lng: number, lat: number): Promise<NamedCoord> {
  if (!BMap.Convertor) return Promise.reject(new Error('位置转换暂不可用，请稍后重试'))
  if (!Number.isFinite(lng) || !Number.isFinite(lat) || Math.abs(lng) > 180 || Math.abs(lat) > 90) return Promise.reject(new Error('定位结果无效，请重试'))
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error('位置转换超时，请重试')), 8000)
    try {
      new BMap.Convertor!().translate([new BMap.Point(lng, lat)], 1, 5, result => {
        window.clearTimeout(timer)
        const point = result.points?.[0]
        if (result.status !== 0 || !point || !Number.isFinite(point.lng) || !Number.isFinite(point.lat)) {
          reject(new Error('位置转换失败，请重试')); return
        }
        resolve({ lng: point.lng, lat: point.lat, crs: 'BD09' })
      })
    } catch { window.clearTimeout(timer); reject(new Error('位置转换失败，请重试')) }
  })
}
export function heatColor(seconds: number): string {
  return seconds <= 300 ? '#17b684' : seconds <= 600 ? '#39afa7' : '#3975ed'
}

function toPoint(BMap: BMapNamespace, coord: NamedCoord): BMapPointLike {
  if (coord.crs !== 'BD09') {
    throw new Error(`地图图层只接受 BD09 坐标，收到 ${coord.crs}`)
  }
  return new BMap.Point(coord.lng, coord.lat)
}

/** 把业务图层渲染到百度地图；返回本次创建的覆盖物，调用方负责下一轮清理。
 *
 * 注意：图层渲染不调用 setViewport，不自动改变用户的比例尺，
 * 避免高频视口动画克隆覆盖物层产生同位残影。
 * markers.style='icon' 渲染为无边框小图标（点击由 BaiduMap 的 DOM 委托透传 payload）；
 * 默认 'pill' 渲染带边框文字标签。JSAPI Label 的事件 API 在部分版本不可用，
 * 点击走 BaiduMap 容器上的原生事件委托。
 */
export function renderLayers(
  BMap: BMapNamespace,
  map: BMapInstance,
  layers: LayerInput,
): BMapOverlay[] {
  const created: BMapOverlay[] = []
  for (const ring of layers.routeBand?.fills ?? []) {
    const overlay = new BMap.Polygon(ring.map(c => toPoint(BMap, c)), {
      strokeWeight: 0, strokeOpacity: 0, fillColor: '#6366f1', fillOpacity: 0.18,
    })
    map.addOverlay(overlay)
    created.push(overlay)
  }
  for (const ring of layers.routeBand?.boundaries ?? []) {
    const overlay = new BMap.Polyline(roundContour(ring).map(c => toPoint(BMap, c)), {
      strokeColor: '#6366f1', strokeWeight: 2, strokeOpacity: 0.7,
    })
    map.addOverlay(overlay)
    created.push(overlay)
  }
  for (const line of layers.planRoutes ?? []) {
    if (line.length < 2) continue
    const points = line.map((c) => toPoint(BMap, c))
    const overlay = new BMap.Polyline(points, {
      strokeColor: '#ea580c',
      strokeWeight: 6,
      strokeOpacity: 0.95,
    })
    map.addOverlay(overlay)
    created.push(overlay)
  }
  for (const line of layers.route ?? []) {
    if (line.length < 2) continue
    const points = line.map((c) => toPoint(BMap, c))
    const overlay = new BMap.Polyline(points, {
      strokeColor: '#2563eb',
      strokeWeight: 5,
      strokeOpacity: 0.9,
    })
    map.addOverlay(overlay)
    created.push(overlay)
  }
  if (layers.referenceCircle) {
    const { center, radiusM } = layers.referenceCircle
    const ring = Array.from({ length: 73 }, (_, i) => destAt(center, i * 5, radiusM))
    const circle = new BMap.Polyline(ring.map(p => toPoint(BMap, p)), {
      strokeColor: '#8a9ebf', strokeWeight: 1, strokeOpacity: .5, strokeStyle: 'solid',
    })
    map.addOverlay(circle)
    created.push(circle)
  }
  for (const [index, ring] of (layers.isoPolygons ?? []).entries()) {
    if (ring.length < 3) continue
    const points = ring.map((c) => toPoint(BMap, c))
    const overlay = new BMap.Polygon(points, {
      strokeColor: MARKER_COLORS[index % MARKER_COLORS.length],
      strokeWeight: 2,
      strokeOpacity: layers.isoContours?.length && index === 0 ? 0 : 0.8,
      fillColor: MARKER_COLORS[index % MARKER_COLORS.length],
      fillOpacity: 0.075,
    })
    map.addOverlay(overlay)
    created.push(overlay)
  }
  const drawContours = (lines: NamedCoord[][], color: string, weight = 3) => {
    for (const line of lines) {
      if (line.length < 2) continue
      const points = roundContour(line).map(c => toPoint(BMap, c))
      const halo = new BMap.Polyline(points, { strokeColor: '#ffffff', strokeWeight: 6, strokeOpacity: 0.75 })
      map.addOverlay(halo)
      created.push(halo)
      const overlay = new BMap.Polyline(points, {
        strokeColor: color, strokeWeight: weight, strokeOpacity: 0.95,
      })
      map.addOverlay(overlay)
      created.push(overlay)
    }
  }
  drawContours(layers.isoContours ?? [], MARKER_COLORS[0]!)
  stopPreviewAnimation(map)
  const previous = previewShapes.get(map) ?? []
  const nextPreview = layers.previewContours ?? []
  previewShapes.set(map, nextPreview)
  const animated: { overlay: BMapOverlay & { setPath?: (points: BMapPointLike[]) => void }; from: NamedCoord[]; to: NamedCoord[] }[] = []
  for (const [index, line] of nextPreview.entries()) {
    if (line.length < 2) continue
    const overlay = new BMap.Polyline(roundContour(line).map(c => toPoint(BMap, c)), {
      strokeColor: '#3975ed', strokeWeight: 3, strokeOpacity: .8,
    })
    map.addOverlay(overlay)
    created.push(overlay)
    const from = previous[index] ?? (layers.referenceCircle ? Array.from({ length: 73 }, (_, i) => destAt(layers.referenceCircle!.center, i * 5, layers.referenceCircle!.radiusM)) : undefined)
    if (from?.length === line.length && line.length === 73) animated.push({ overlay, from, to: line })
  }
  if (animated.length && typeof requestAnimationFrame === 'function' && !globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
    const begin = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - begin) / 500), ease = t * t * (3 - 2 * t)
      for (const { overlay, from, to } of animated) {
        overlay.setPath?.(roundContour(to.map((p, i) => ({ ...p, lng: from[i]!.lng + (p.lng - from[i]!.lng) * ease,
          lat: from[i]!.lat + (p.lat - from[i]!.lat) * ease }))).map(p => toPoint(BMap, p)))
      }
      if (t < 1) previewFrames.set(map, requestAnimationFrame(tick))
      else previewFrames.delete(map)
    }
    tick(begin)
  }
  // 先铺外圈，再铺内圈；顺序不依赖缓存返回次序，避免大面盖住小圈。
  for (const layer of [...(layers.heatPolygons ?? [])].sort((a, b) => b.seconds - a.seconds)) {
    const color = heatColor(layer.seconds)
    const overlay = new BMap.Polygon(layer.ring.map(coord => toPoint(BMap, coord)), {
      strokeColor: color, strokeWeight: layer.seconds === 900 ? 3 : 2, fillColor: color,
      strokeOpacity: layer.mesh || layer.contours?.length ? 0 : 0.8,
      strokeStyle: layer.estimated ? 'dashed' : 'solid', fillOpacity: layer.estimated ? 0.025 : layer.seconds <= 300 ? 0.16 : layer.seconds <= 600 ? 0.12 : 0.075,
    })
    map.addOverlay(overlay)
    created.push(overlay)
    drawContours(layer.contours ?? [], color, layer.seconds === 900 ? 3 : 2)
  }
  for (const cell of layers.coverageCells ?? []) {
    const color = cell.status === 'blind' ? '#64748b' : cell.status === 'covered' ? '#10b981' : '#cbd5e1'
    const overlay = new BMap.Polygon(cell.ring.map(coord => toPoint(BMap, coord)), {
      strokeColor: color, strokeWeight: 1, fillColor: color,
      fillOpacity: cell.status === 'unknown' ? 0.12 : 0.35,
    })
    map.addOverlay(overlay)
    created.push(overlay)
  }
  const markers = layers.markers ?? []
  const sizes = markers.map(m => ({ width: Math.min(202, Math.max(132, 62 + Array.from(m.caption ?? '').reduce((n, c) => n + (c.charCodeAt(0) > 255 ? 13 : 7), 0))), height: m.subtitle ? 54 : 38 }))
  const anchors = markers.flatMap((m, index) => {
    if (!m.caption || !map.pointToPixel) return []
    const p = map.pointToPixel(toPoint(BMap, m.coord))
    if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) return []
    return [{ index, ...p, ...sizes[index]!, priority: m.active ? 200 : m.priority ?? 0 }]
  })
  const placements = layers.labelBounds && map.pointToPixel
    ? placeMapLabels(anchors, layers.labelBounds, layers.labelBounds.right - layers.labelBounds.left < 600 ? 4 : 7, layers.labelObstacles) : null
  for (const [index, marker] of markers.entries()) {
    const point = toPoint(BMap, marker.coord)
    if (marker.probe && BMap.Label) {
      const overlay = new BMap.Label('', { position: point, offset: { width: -3, height: -3 } })
      overlay.setStyle?.({ width: '6px', height: '6px', padding: '0', border: '1px solid #ffffff', borderRadius: '50%',
        backgroundColor: { reachable: '#159d72', outside: '#8092af', unknown: '#e49932', no_route: '#64748b' }[marker.probe],
        pointerEvents: 'none', zIndex: '20' })
      map.addOverlay(overlay)
      created.push(overlay)
      continue
    }
    const isCoveragePoint = marker.label === '!' || marker.label === '✓'
    // Label 比默认红色 pin 更接近产品原型；测试替身或旧版 SDK 没有 Label 时回退 Marker。
    // style='icon' 渲染为无边框小图标并透传点击 payload；默认 pill 为带边框文字标签。
    const escape = (text: string) => text.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)
    const placement = placements?.get(index)
    const bubble = Boolean(marker.caption && (placements === null || placement))
    const size = sizes[index]!
    const bubbleContent = `<span class="map-place map-place--${placement?.side ?? 'above'} ${marker.kind === 'center' ? 'map-place--center' : ''} ${marker.active ? 'map-place--active' : ''}" style="width:${size.width}px;height:${size.height}px"><span class="map-place__icon">${escape(marker.label)}</span><span class="map-place__copy"><strong>${escape(marker.caption ?? '')}</strong>${marker.subtitle ? `<small>${escape(marker.subtitle)}</small>` : ''}</span></span>`
    const content = layers.markerRevision == null ? escape(marker.label)
      : bubble ? `<span data-map-marker-id="${layers.markerRevision}:${index}" role="button" tabindex="0" aria-label="${escape(marker.title || marker.caption || marker.label)}">${bubbleContent}</span>`
      : `<span data-map-marker-id="${layers.markerRevision}:${index}" role="${isCoveragePoint ? 'img' : 'button'}" ${isCoveragePoint ? '' : 'tabindex="0"'} aria-label="${escape(marker.title || marker.label)}" style="display:${marker.style === 'icon' ? 'inline-flex' : 'inline-block'};align-items:center;justify-content:center;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:middle;min-width:${marker.style === 'icon' ? 36 : 0}px;min-height:${marker.style === 'icon' ? 36 : 0}px">${escape(marker.label)}</span>`
    const overlay = BMap.Label
      ? new BMap.Label(content, {
        position: point,
        offset: bubble ? { width: placement ? placement.x - map.pointToPixel!(point).x : -size.width / 2,
          height: placement ? placement.y - map.pointToPixel!(point).y : -size.height - 14 }
          : isCoveragePoint ? { width: -5, height: -5 } : marker.style === 'icon' ? { width: -18, height: -18 } : { width: -18, height: marker.label === '新选位置' ? 8 : -28 },
      })
      : new BMap.Marker(point, { title: marker.label })
    if (BMap.Label && 'setStyle' in overlay && typeof overlay.setStyle === 'function') {
      const isBlind = marker.label === '!'
      const isCovered = marker.label === '✓'
      if (bubble) {
        overlay.setStyle({ backgroundColor: 'transparent', border: '0', padding: '0', cursor: 'pointer', zIndex: marker.active ? '60' : marker.kind === 'center' ? '55' : '45' })
      } else if (isCoveragePoint) {
        overlay.setStyle({ backgroundColor: isBlind ? '#64748b' : '#10b981', border: '2px solid #ffffff', borderRadius: '50%',
          width: '10px', height: '10px', padding: '0', fontSize: '0', lineHeight: '0', pointerEvents: 'none' })
      } else if (marker.style === 'icon') {
        overlay.setStyle({
          backgroundColor: marker.caption ? '#ffffff' : 'transparent',
          border: marker.caption ? '1px solid #d9e4ee' : '0',
          borderRadius: '50%',
          boxShadow: marker.caption ? '0 2px 7px #243f6018' : 'none',
          padding: '0',
          fontSize: '18px',
          lineHeight: '14px',
          whiteSpace: 'nowrap',
          cursor: 'pointer',
        })
      } else {
        overlay.setStyle({
          color: isBlind ? '#b45309' : isCovered ? '#047857' : '#0f172a',
          backgroundColor: '#ffffff',
          border: `1px solid ${isBlind ? '#fbbf24' : isCovered ? '#6ee7b7' : '#cbd5e1'}`,
          borderRadius: '999px',
          padding: '3px 7px',
          boxShadow: '0 2px 8px rgba(15, 23, 42, 0.16)',
          fontSize: '11px',
          lineHeight: '16px',
          whiteSpace: 'nowrap',
        })
      }
    }
    map.addOverlay(overlay)
    created.push(overlay)
    if (bubble && BMap.Label) {
      const anchor = new BMap.Label('<span class="map-place-anchor" aria-hidden="true"></span>', { position: point, offset: { width: -4, height: -4 } })
      anchor.setStyle?.({ border: '0', padding: '0', backgroundColor: 'transparent', pointerEvents: 'none' })
      map.addOverlay(anchor)
      created.push(anchor)
    }
  }
  return created
}
