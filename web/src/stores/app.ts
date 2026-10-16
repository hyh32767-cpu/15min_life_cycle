import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import type { DataMode, ProviderHealth } from '@/domain/types'
import type { AppProvider } from '@/providers/contracts'
import { createProvider } from '@/providers'

export const useAppStore = defineStore('app', () => {
  const mode = ref<DataMode>('live')
  const health = ref<ProviderHealth | null>(null)
  const loading = ref(false)
  const error = ref('')
  const providerOverride = ref<AppProvider | null>(null)

  const provider = computed(() => providerOverride.value ?? createProvider())

  function setProviderForTesting(next: AppProvider | null): void {
    providerOverride.value = next
  }

  async function loadHealth(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      health.value = await provider.value.getHealth()
    } catch (err) {
      health.value = null
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  return {
    mode, health, loading, error, provider,
    setProviderForTesting, loadHealth,
  }
})
