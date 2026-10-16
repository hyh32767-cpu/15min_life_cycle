import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import PlaceSearch from '@/components/PlaceSearch.vue'
import { useAppStore } from '@/stores/app'

beforeEach(() => { setActivePinia(createPinia()); vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })
const place = { name: '真实名称', address: '完整地址', coord: { lng: 116.3, lat: 40, crs: 'BD09' as const }, source: 'live-api' as const }
it('debounces input, deduplicates explicit search and keeps the selected name and address', async () => {
  const search = vi.spyOn(useAppStore().provider, 'searchLocations').mockResolvedValue({ traceId: 't', mode: 'live', candidates: [place], warnings: [] })
  const wrapper = mount(PlaceSearch)
  await wrapper.get('input').setValue('图')
  await vi.advanceTimersByTimeAsync(750)
  expect(search).not.toHaveBeenCalled()
  await wrapper.get('input').setValue('图书馆')
  await vi.advanceTimersByTimeAsync(700)
  await flushPromises()
  await wrapper.get('form').trigger('submit')
  expect(search).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).toContain('完整地址')
  await wrapper.get('.place-search__result').trigger('click')
  expect(wrapper.emitted('select')?.[0]?.[0]).toEqual(place)
  wrapper.unmount()
})
it('drops a stale response after the keyword changes and cancels delayed search on unmount', async () => {
  let finish!: (value: { traceId: string; mode: 'live'; candidates: typeof place[]; warnings: string[] }) => void
  const search = vi.spyOn(useAppStore().provider, 'searchLocations').mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const wrapper = mount(PlaceSearch)
  await wrapper.get('input').setValue('旧名称')
  await wrapper.get('form').trigger('submit')
  await wrapper.get('input').setValue('新名称')
  finish({ traceId: 't', mode: 'live', candidates: [place], warnings: [] })
  await flushPromises()
  expect(wrapper.text()).not.toContain('真实名称')
  wrapper.unmount()
  await vi.advanceTimersByTimeAsync(750)
  expect(search).toHaveBeenCalledTimes(1)
})
