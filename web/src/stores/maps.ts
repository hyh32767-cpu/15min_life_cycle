import { ref } from 'vue'
import { defineStore } from 'pinia'

import { useAppStore } from '@/stores/app'

/** T110/UI-M：百度 JSAPI 4.0 加载状态。浏览器端 AK 只经 /api/maps/config 获取或构建时注入。 */
export type MapsStatus = 'idle' | 'loading' | 'ready' | 'error'

let loaderPromise: Promise<unknown> | null = null

function loadBaiduSdk(ak: string, version = '4.0'): Promise<unknown> {
  if (loaderPromise) return loaderPromise
  // JSAPI 4.0 bootstrap 用 document.write 拉 getscript，动态注入 script 时不执行；
  // 按官方异步加载方式带 callback，由 getscript 主动回调用 appendChild 注入。
  loaderPromise = new Promise<unknown>((resolve, reject) => {
    const w = window as unknown as Record<string, unknown>
    if (w.BMap) {
      resolve(w.BMap)
      return
    }
    const callbackName = '__shunshouBaiduInit'
    const wAny = window as unknown as Record<string, unknown>
    const script = document.createElement('script')
    const timer = window.setTimeout(() => fail('地图加载超时，请重试'), 15000)
    function fail(message: string): void {
      window.clearTimeout(timer)
      delete wAny[callbackName]
      script.remove()
      reject(new Error(message))
    }
    wAny[callbackName] = () => {
      window.clearTimeout(timer)
      delete wAny[callbackName]
      const loaded = (window as unknown as Record<string, unknown>).BMap
      if (loaded) resolve(loaded)
      else fail('地图加载未完成，请重试')
    }
    script.src = `https://api.map.baidu.com/api?v=${encodeURIComponent(version)}&ak=${encodeURIComponent(ak)}&callback=${callbackName}`
    script.async = true
    script.onerror = () => fail('地图加载失败，请重试')
    document.head.appendChild(script)
  })
  return loaderPromise
}

export function resetMapsLoaderForTesting(): void {
  loaderPromise = null
}

export const useMapsStore = defineStore('maps', () => {
  const app = useAppStore()
  const status = ref<MapsStatus>('idle')
  const error = ref('')
  const ak = ref('')
  const version = ref('4.0')
  let pendingLoad: Promise<unknown> | null = null

  function ensureLoaded(): Promise<unknown> {
    if (pendingLoad) return pendingLoad
    pendingLoad = load().finally(() => { pendingLoad = null })
    return pendingLoad
  }

  async function load(): Promise<unknown> {
    if (status.value === 'ready') {
      return (window as unknown as Record<string, unknown>).BMap
    }
    status.value = 'loading'
    error.value = ''
    try {
      // 浏览器端 AK：构建时注入优先，否则经 /api/maps/config 运行时获取。
      // Server AK/SK 永不进入此路径。
      let key = import.meta.env.VITE_BAIDU_MAP_AK_BROWSER?.trim() || ''
      let ver = '4.0'
      if (!key) {
        const config = await app.provider.getMapsConfig()
        key = (config.ak || '').trim()
        ver = config.version || '4.0'
      }
      if (!key) {
        throw new Error('地图服务尚未配置，请联系维护者')
      }
      ak.value = key
      version.value = ver
      const ns = await loadBaiduSdk(key, ver)
      status.value = 'ready'
      return ns
    } catch (err) {
      loaderPromise = null
      status.value = 'error'
      error.value = err instanceof Error ? err.message : String(err)
      throw err
    }
  }

  return { status, error, ak, version, ensureLoaded }
})
