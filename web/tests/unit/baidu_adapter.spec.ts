// T110/UI-M：百度地图适配层契约。只测纯逻辑（BD09 守卫/多边形配色/空图层），
// 不加载外部 SDK、不碰 DOM。
import { describe, expect, it, vi } from 'vitest'

import {
  renderLayers,
  type BMapInstance,
  type BMapNamespace,
  type BMapOverlay,
} from '@/components/map/baiduAdapter'

function fakeNs(): { ns: BMapNamespace; map: BMapInstance & { added: BMapOverlay[] } } {
  const added: BMapOverlay[] = []
  const map = {
    added,
    centerAndZoom: vi.fn(),
    setViewport: vi.fn(),
    addOverlay(o: BMapOverlay) {
      added.push(o)
    },
    removeOverlay(o: BMapOverlay) {
      const index = added.indexOf(o)
      if (index >= 0) added.splice(index, 1)
    },
    clearOverlays: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }
  class FakePoint {
    lng: number
    lat: number
    constructor(lng: number, lat: number) {
      this.lng = lng
      this.lat = lat
    }
  }
  class FakeOverlay {
    arg: unknown
    constructor(arg: unknown) {
      this.arg = arg
    }
  }
  const ns = {
    Map: vi.fn(),
    Point: FakePoint,
    Marker: FakeOverlay,
    Polyline: FakeOverlay,
    Polygon: FakeOverlay,
  } as unknown as BMapNamespace
  return { ns, map: map as unknown as BMapInstance & { added: BMapOverlay[] } }
}

describe('baiduAdapter', () => {
  it('keeps fitted preview separate and does not move the viewport', () => {
    const { ns, map } = fakeNs()
    const styles: Record<string, unknown>[] = []
    ns.Polyline = class { constructor(_points: unknown, style: Record<string, unknown>) { styles.push(style) } } as unknown as BMapNamespace['Polyline']
    const line = [{lng:116.4,lat:39.9,crs:'BD09' as const},{lng:116.41,lat:39.9,crs:'BD09' as const}]
    renderLayers(ns,map,{previewContours:[line],isoContours:[line]})
    expect(styles.filter(s=>s.strokeOpacity===.8)).toHaveLength(1)
    expect(styles.filter(s=>s.strokeOpacity===.95)).toHaveLength(1)
    expect(map.setViewport).not.toHaveBeenCalled()
  })
  it('keeps crowded facilities clickable, escapes names and anchors labels at the original coordinate', () => {
    const { ns, map } = fakeNs()
    const contents: string[] = []
    const positions: unknown[] = []
    ns.Label = class {
      constructor(text: string, options: { position: unknown }) { contents.push(text); positions.push(options.position) }
      setStyle() {}
    } as unknown as NonNullable<BMapNamespace['Label']>
    map.pointToPixel = p => ({ x: 120 + p.lng, y: 150 })
    const markers = Array.from({ length: 5 }, (_, i) => ({ coord: { lng: i, lat: 30, crs: 'BD09' as const },
      label: '💊', caption: i === 3 ? '<测试&药店>' : `药店${i}`, subtitle: '药店',
      title: `设施${i}`, active: i === 3, style: 'icon' as const }))
    renderLayers(ns, map, { markers, markerRevision: 10, labelBounds: { left: 12, top: 16, right: 360, bottom: 320 } })
    expect(contents.filter(c => c.includes('data-map-marker-id'))).toHaveLength(5)
    expect(contents.some(c => c.includes('map-place--active') && c.includes('&lt;测试&amp;药店&gt;'))).toBe(true)
    expect(contents.some(c => c.includes('<测试&药店>'))).toBe(false)
    expect(contents.some(c => c.includes('map-place-anchor'))).toBe(true)
    expect(positions.every(p => (p as { lat: number }).lat === 30)).toBe(true)
    expect(map.setViewport).not.toHaveBeenCalled()
  })
  it('renders open reconstructed contours as lines without replacing classification fill or moving viewport', () => {
    const { ns, map } = fakeNs()
    const ring = [{ lng: 116, lat: 40, crs: 'BD09' as const },
      { lng: 116.01, lat: 40, crs: 'BD09' as const }, { lng: 116.01, lat: 40.01, crs: 'BD09' as const }]
    const line = [ring[0]!, ring[1]!]
    const created = renderLayers(ns, map, { isoPolygons: [ring], isoContours: [line],
      heatPolygons: [{ ring, seconds: 600, contours: [line] }] })
    expect(created.map(c => (c as { arg: unknown[] }).arg.length)).toEqual([3, 2, 2, 3, 2, 2])
    expect(map.setViewport).not.toHaveBeenCalled()
    expect(map.centerAndZoom).not.toHaveBeenCalled()
  })
  it('coverage samples are small static dots rather than overlapping place buttons', () => {
    const { ns, map } = fakeNs()
    const styles: Record<string, string>[] = []
    const labels: string[] = []
    const offsets: { width: number; height: number }[] = []
    class Label {
      constructor(content: string, options: { offset: { width: number; height: number } }) { labels.push(content); offsets.push(options.offset) }
      setStyle(style: Record<string, string>) { styles.push(style) }
    }
    ns.Label = Label as unknown as NonNullable<BMapNamespace['Label']>
    renderLayers(ns, map, { markerRevision: 1, markers: [
      { coord: { lng: 116, lat: 40, crs: 'BD09' }, label: '✓', title: '已覆盖采样点' },
      { coord: { lng: 116.001, lat: 40, crs: 'BD09' }, label: '!', title: '未覆盖采样点' },
    ] })
    expect(styles.every(style => style.width === '10px' && style.pointerEvents === 'none')).toBe(true)
    expect(labels.every(label => label.includes('role="img"') && !label.includes('tabindex'))).toBe(true)
    expect(offsets.every(offset => offset.width === -5 && offset.height === -5)).toBe(true)
  })
  it('draws measured band beneath routes without changing zoom', () => {
    const { ns, map } = fakeNs()
    const ring = [{ lng: 1, lat: 1, crs: 'BD09' as const },
      { lng: 2, lat: 1, crs: 'BD09' as const }, { lng: 2, lat: 2, crs: 'BD09' as const }]
    const created = renderLayers(ns, map, { routeBand: { fills: [ring], boundaries: [ring], seconds: 900 }, route: [ring.slice(0, 2)] })
    expect(created).toHaveLength(3)
    expect((created[0] as { arg: unknown[] }).arg).toHaveLength(3)
    expect((created[2] as { arg: unknown[] }).arg).toHaveLength(2)
    expect(map.centerAndZoom).not.toHaveBeenCalled()
    expect(map.setViewport).not.toHaveBeenCalled()
  })

  it('拒绝非 BD09 图层，不静默混系', () => {
    const { ns, map } = fakeNs()
    expect(() => renderLayers(ns, map, {
      markers: [{ coord: { lng: 116.3, lat: 39.9, crs: 'WGS84' }, label: 'x' }],
    })).toThrow('BD09')
    expect(map.added).toEqual([])
  })

  it('跳过不足点的几何，不画假线假面', () => {
    const { ns, map } = fakeNs()
    const created = renderLayers(ns, map, {
      route: [[{ lng: 1, lat: 1, crs: 'BD09' }]],
      isoPolygons: [[
        { lng: 1, lat: 1, crs: 'BD09' },
        { lng: 2, lat: 2, crs: 'BD09' },
      ]],
    })
    expect(created).toEqual([])
    expect(map.added).toEqual([])
    expect(map.setViewport).not.toHaveBeenCalled()
  })

  it('按种类渲染；视口由 BaiduMap 统一管理，adapter 不再 setViewport', () => {
    const { ns, map } = fakeNs()
    const created = renderLayers(ns, map, {
      route: [[
        { lng: 116.3, lat: 39.9, crs: 'BD09' },
        { lng: 116.31, lat: 39.91, crs: 'BD09' },
      ]],
      isoPolygons: [[
        { lng: 116.3, lat: 39.9, crs: 'BD09' },
        { lng: 116.31, lat: 39.9, crs: 'BD09' },
        { lng: 116.31, lat: 39.91, crs: 'BD09' },
      ]],
      markers: [{ coord: { lng: 116.3, lat: 39.9, crs: 'BD09' }, label: '起点' }],
    })
    expect(created).toHaveLength(3)
    // F80 残影修复：renderLayers 只画覆盖物；高频 setViewport 会克隆覆盖物层留残影，
    // 视口改由 BaiduMap 在图层内容变化时去抖调用。
    expect(map.setViewport).not.toHaveBeenCalled()
  })

  it('方案动线使用独立橙色图层，与基准线区分', () => {
    const { ns, map } = fakeNs()
    const created = renderLayers(ns, map, {
      route: [[
        { lng: 116.3, lat: 39.9, crs: 'BD09' },
        { lng: 116.31, lat: 39.91, crs: 'BD09' },
      ]],
      planRoutes: [[
        { lng: 116.3, lat: 39.9, crs: 'BD09' },
        { lng: 116.32, lat: 39.92, crs: 'BD09' },
      ]],
    })
    expect(created).toHaveLength(2)
  })
})
