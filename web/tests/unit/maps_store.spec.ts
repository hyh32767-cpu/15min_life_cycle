// T110/UI-M：maps store 只测 AK 获取优先级与状态机；SDK script 注入本身不测。
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAppStore } from '@/stores/app'
import { resetMapsLoaderForTesting, useMapsStore } from '@/stores/maps'

function mockApp(config: { ak: string; version?: string }) {
  return {
    provider: {
      getMapsConfig: vi.fn().mockResolvedValue({
        configured: Boolean(config.ak),
        ak: config.ak,
        version: config.version ?? '4.0',
      }),
    },
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  resetMapsLoaderForTesting()
  vi.unstubAllGlobals()
})

describe('maps store', () => {
  it('无任何 AK 时进入 error，不静默假装可用', async () => {
    const app = useAppStore()
    app.setProviderForTesting(mockApp({ ak: '' }).provider as never)
    vi.stubEnv('VITE_BAIDU_MAP_AK_BROWSER', '')
    const store = useMapsStore()
    await expect(store.ensureLoaded()).rejects.toThrow('地图服务尚未配置')
    expect(store.status).toBe('error')
    expect(store.error).toContain('地图服务尚未配置')
    expect(store.error).not.toContain('VITE_')
  })

  it('运行时配置 AK 可用时尝试加载 SDK', async () => {
    const app = useAppStore()
    const provider = mockApp({ ak: 'runtime-ak' })
    app.setProviderForTesting(provider.provider as never)
    vi.stubEnv('VITE_BAIDU_MAP_AK_BROWSER', '')
    // 预置 BMap 使 loader 直接 resolve，不注入 script
    vi.stubGlobal('BMap', { Map: vi.fn() })
    const store = useMapsStore()
    const ns = await store.ensureLoaded()
    expect(ns).toBeDefined()
    expect(store.status).toBe('ready')
    expect(provider.provider.getMapsConfig).toHaveBeenCalledTimes(1)
  })

  it('配置请求未完成时并发调用共享同一加载 Promise', async () => {
    const app = useAppStore()
    let finish!: (value: { configured: boolean; ak: string; version: string }) => void
    const getMapsConfig = vi.fn(() => new Promise<{ configured: boolean; ak: string; version: string }>((resolve) => { finish = resolve }))
    app.setProviderForTesting({ getMapsConfig } as never)
    vi.stubEnv('VITE_BAIDU_MAP_AK_BROWSER', '')
    vi.stubGlobal('BMap', { Map: vi.fn() })
    const store = useMapsStore()
    const first = store.ensureLoaded()
    const second = store.ensureLoaded()
    finish({ configured: true, ak: 'runtime-ak', version: '4.0' })
    const [firstResult, secondResult] = await Promise.all([first, second])
    expect(firstResult).toBe(secondResult)
    expect(getMapsConfig).toHaveBeenCalledTimes(1)
  })

  it('SDK超时移除失败脚本，下一次可以重新加载', async () => {
    vi.useFakeTimers()
    try {
      const app = useAppStore()
      app.setProviderForTesting(mockApp({ ak: 'runtime-ak' }).provider as never)
      vi.stubEnv('VITE_BAIDU_MAP_AK_BROWSER', '')
      const store = useMapsStore()
      const rejected = expect(store.ensureLoaded()).rejects.toThrow('超时')
      await vi.advanceTimersByTimeAsync(15000)
      await rejected
      expect(document.querySelector('script[src*="api.map.baidu.com/api"]')).toBeNull()
      vi.stubGlobal('BMap', { Map: vi.fn() })
      await expect(store.ensureLoaded()).resolves.toBeDefined()
      expect(store.status).toBe('ready')
    } finally {
      vi.useRealTimers()
    }
  })
})
