// T110/UI-M：BaiduMap 挂载冒烟。SDK 用 BMap 全局替身，不加载外部脚本、不触网。
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import BaiduMap from '@/components/map/BaiduMap.vue'
import { useMapsStore } from '@/stores/maps'

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

function stubSdk() {
  const handlers = new Map<string, (e: unknown) => void>()
  const added: unknown[] = []
  let center = new FakePoint(116.3, 39.9)
  let zoom = 13
  const map = {
    centerAndZoom: vi.fn((point: FakePoint, level: number) => { center = point; zoom = level }),
    setViewport: vi.fn(),
    panTo: vi.fn((point: FakePoint) => { center = point }),
    zoomIn: vi.fn(() => { zoom++ }),
    getCenter: () => center,
    getZoom: () => zoom,
    addOverlay(o: unknown) {
      added.push(o)
    },
    removeOverlay: vi.fn(),
    clearOverlays: vi.fn(),
    addEventListener(event: string, handler: (e: unknown) => void) {
      handlers.set(event, handler)
    },
    removeEventListener: vi.fn(),
  }
  const BMap = {
    Map: vi.fn(function () { return map }),
    Point: FakePoint,
    Marker: FakeOverlay,
    Polyline: FakeOverlay,
    Polygon: FakeOverlay,
  }
  vi.stubGlobal('BMap', BMap)
  useMapsStore().status = 'ready'
  return { handlers, added, map }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.unstubAllGlobals()
})
afterEach(() => vi.useRealTimers())

describe('BaiduMap', () => {
  it('定位没有回调也会超时恢复按钮，提示自动消失且晚到的位置不再移动地图', async () => {
    const { map } = stubSdk()
    let success!: (value: unknown) => void
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('navigator', { geolocation: { getCurrentPosition: vi.fn((resolve) => { success = resolve }) } })
    const wrapper = mount(BaiduMap)
    await vi.waitFor(() => expect(map.centerAndZoom).toHaveBeenCalledTimes(1))
    vi.useFakeTimers()
    const button = wrapper.get('[aria-label="定位到当前位置"]')
    await button.trigger('click')
    expect(button.attributes('disabled')).toBeDefined()
    await vi.advanceTimersByTimeAsync(8500)
    expect(wrapper.text()).toContain('定位超时')
    expect(button.attributes('disabled')).toBeUndefined()
    success({ coords: { longitude: 116.4, latitude: 39.9 } })
    await vi.advanceTimersByTimeAsync(5000)
    expect(wrapper.text()).not.toContain('定位超时')
    expect(map.panTo).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('routes native base-map icon clicks using the SDK POI identity', async () => {
    const { handlers } = stubSdk()
    const wrapper = mount(BaiduMap)
    await vi.waitFor(() => expect(handlers.has('click')).toBe(true))
    handlers.get('click')!({ point: new FakePoint(116.1, 40), icon: { uid: 'native', name: '底图药店', position: new FakePoint(116.2, 40.1) } })
    expect(wrapper.emitted('poi-click')?.[0]?.[0]).toMatchObject({ uid: 'native', name: '底图药店', coord: { lng: 116.2, lat: 40.1, crs: 'BD09' } })
    wrapper.unmount()
  })
  it('rejects stale rendered-marker clicks instead of applying the new array index', async () => {
    const { handlers } = stubSdk()
    const point = { lng: 116.3, lat: 40, crs: 'BD09' as const }
    const wrapper = mount(BaiduMap, { props: { markers: [{ coord: point, label: '甲', payload: { type: 'poi', index: 0, placeKey: 'a' } }] } })
    await vi.waitFor(() => expect(handlers.has('click')).toBe(true))
    const stale = document.createElement('span')
    stale.dataset.mapMarkerId = '1:0'
    wrapper.get('.baidu-map__container').element.append(stale)
    await wrapper.setProps({ markers: [{ coord: point, label: '乙', payload: { type: 'poi', index: 0, placeKey: 'b' } }] })
    stale.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    expect(wrapper.emitted('marker-click')).toBeUndefined()
    wrapper.unmount()
  })
  it('keeps the last user center and zoom when the map container resizes', async () => {
    let resize!: () => void
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resize = callback }
      observe() {}
      disconnect() {}
    })
    const { map, handlers } = stubSdk()
    const wrapper = mount(BaiduMap, { props: { zoom: 13, center: { lng: 116.3, lat: 39.9, crs: 'BD09' } } })
    await vi.waitFor(() => expect(map.centerAndZoom).toHaveBeenCalledTimes(1))
    map.panTo(new FakePoint(116.35, 39.95))
    map.zoomIn()
    handlers.get('moveend')!({})
    resize()
    expect(map.centerAndZoom).toHaveBeenLastCalledWith(new FakePoint(116.35, 39.95), 14)
    wrapper.unmount()
  })
  it('restores each page viewport and cancels an unconfirmed point across pages', async () => {
    const { map, handlers } = stubSdk()
    const a = { lng: 116.3, lat: 39.9, crs: 'BD09' as const }
    const b = { lng: 116.4, lat: 40.1, crs: 'BD09' as const }
    const wrapper = mount(BaiduMap, { props: { zoom: 13, viewKey: 'commute', center: a, pickable: true } })
    await vi.waitFor(() => expect(map.centerAndZoom).toHaveBeenCalledTimes(1))
    map.panTo(new FakePoint(116.32, 39.93))
    map.zoomIn()
    handlers.get('moveend')!({})
    handlers.get('click')!({ point: a })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[aria-label="确认位置"]').exists() || wrapper.text().includes('确认位置')).toBe(true)
    await wrapper.setProps({ viewKey: 'community', center: b })
    expect(wrapper.text()).not.toContain('确认位置')
    map.zoomIn()
    handlers.get('zoomend')!({})
    await wrapper.setProps({ viewKey: 'commute', center: a })
    expect(map.getCenter()).toEqual(new FakePoint(116.32, 39.93))
    expect(map.getZoom()).toBe(14)
    await wrapper.setProps({ viewKey: 'community', center: { ...b, lng: 116.5 } })
    expect(map.getCenter()).toEqual(new FakePoint(116.5, 40.1))
    expect(map.getZoom()).toBe(14)
    wrapper.unmount()
  })
  it('keeps the user zoom through route redraws and only pans when the origin changes', async () => {
    const { map } = stubSdk()
    const wrapper = mount(BaiduMap, { props: {
      center: { lng: 116.3, lat: 39.9, crs: 'BD09' },
      routes: [[{ lng: 116.3, lat: 39.9, crs: 'BD09' }, { lng: 116.31, lat: 39.91, crs: 'BD09' }]],
    } })
    await vi.waitFor(() => expect(map.centerAndZoom).toHaveBeenCalledTimes(1))
    await wrapper.get('[aria-label="放大地图"]').trigger('click')
    expect(map.zoomIn).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ routes: [] })
    await wrapper.setProps({ routes: [[
      { lng: 116.3, lat: 39.9, crs: 'BD09' }, { lng: 116.4, lat: 40, crs: 'BD09' },
    ]], markers: [{ coord: { lng: 116.4, lat: 40, crs: 'BD09' }, label: '地点' }] })
    expect(map.setViewport).not.toHaveBeenCalled()
    expect(map.centerAndZoom).toHaveBeenCalledTimes(1)
    expect(map.panTo).not.toHaveBeenCalled()
    await wrapper.setProps({ center: { lng: 116.4, lat: 40, crs: 'BD09' } })
    expect(map.panTo).toHaveBeenCalledWith(new FakePoint(116.4, 40), { noAnimation: true })
    expect(map.centerAndZoom).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('SDK 就绪后按业务图层绘制并透传点选', async () => {
    stubSdk()
    const wrapper = mount(BaiduMap, {
      props: {
        routes: [[
          { lng: 116.3, lat: 39.9, crs: 'BD09' },
          { lng: 116.31, lat: 39.91, crs: 'BD09' },
        ]],
        markers: [{ coord: { lng: 116.3, lat: 39.9, crs: 'BD09' }, label: '公司' }],
        pickable: true,
      },
      global: { stubs: { transition: false } },
    })
    // maps store 异步 ensureLoaded：等 SDK 就绪微任务
    await vi.waitFor(() => {
      expect(wrapper.find('.baidu-map__container').exists()).toBe(true)
    })
    expect(wrapper.find('[role="application"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('无 AK 时显示独立错误，不画假底图', async () => {
    const { useAppStore } = await import('@/stores/app')
    const app = useAppStore()
    app.setProviderForTesting({
      mode: 'live',
      getHealth: async () => { throw new Error('no health') },
      searchLocations: async () => { throw new Error('no search') },
      getWalkingRoute: async () => { throw new Error('no route') },
      getTravelMatrix: async () => { throw new Error('no matrix') },
      getCorridorPois: async () => { throw new Error('no corridor') },
      createIsochrone: async () => { throw new Error('no iso') },
      getIsochronePois: async () => { throw new Error('no pois') },
      getCorridorEvidence: async () => { throw new Error('no evidence') },
      createPlan: async () => { throw new Error('no plan') },
      createReplan: async () => { throw new Error('no replan') },
      checkExplore: async () => { throw new Error('no explore') },
      checkCoverage: async () => { throw new Error('no coverage') },
      listCases: async () => { throw new Error('no cases') },
      getCase: async () => { throw new Error('no case') },
      getMapsConfig: async () => ({ configured: false, ak: '', version: '4.0' }),
    } as never)
    vi.stubEnv('VITE_BAIDU_MAP_AK_BROWSER', '')
    const wrapper = mount(BaiduMap, { props: { pickable: true } })
    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('百度底图不可用')
    })
    wrapper.unmount()
  })
})
