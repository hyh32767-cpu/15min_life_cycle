import { ref } from 'vue'

export interface LedgerSummary {
  rows: number
  requests: number
  liveRequests: number
  cacheHits: number
  pairs: number
  errors: number
  byStage?: { key: string; rows: number; requests: number }[]
  byInterface?: { key: string; rows: number; requests: number }[]
  note?: string
}

export function useLedgerReport() {
  const summary = ref<LedgerSummary | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function refresh(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const body = await fetch('/api/ledger/summary').then((r) => {
        if (!r.ok) throw new Error(`账本汇总失败 HTTP ${r.status}`)
        return r.json() as Promise<LedgerSummary>
      })
      summary.value = body
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  return { summary, loading, error, refresh }
}
