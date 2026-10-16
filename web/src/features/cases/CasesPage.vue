<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import type { CaseSummary } from '@/providers/contracts'
import { useAppStore } from '@/stores/app'

const app = useAppStore()
const cases = ref<CaseSummary[]>([])
const detail = ref<unknown>(null)
const error = ref('')
const loading = ref(false)
const selectedId = ref('')
const detailLoading = ref(false)
let detailSequence = 0
const caseInfo = computed(() => {
  const value = detail.value as { title?: string; radii?: Record<string, number>; metrics?: { iou?: number }; pockets?: unknown[] } | null
  if (!value) return null
  const radii = Object.values(value.radii ?? {}).filter(Number.isFinite)
  return {
    title: value.title ?? '社区案例',
    range: radii.length ? `${Math.round(Math.min(...radii))}–${Math.round(Math.max(...radii))} 米` : '未提供',
    directions: radii.length,
    iou: typeof value.metrics?.iou === 'number' ? `${(value.metrics.iou * 100).toFixed(1)}%` : '未提供',
  }
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    cases.value = await app.provider.listCases()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

async function openCase(id: string): Promise<void> {
  const sequence = ++detailSequence
  error.value = ''
  selectedId.value = id
  detail.value = null
  detailLoading.value = true
  try {
    const value = await app.provider.getCase(id)
    if (sequence === detailSequence) detail.value = value
  } catch (err) {
    if (sequence === detailSequence) error.value = err instanceof Error ? err.message : String(err)
  } finally {
    if (sequence === detailSequence) detailLoading.value = false
  }
}

function closeCase(): void {
  detailSequence++
  selectedId.value = ''
  detail.value = null
  detailLoading.value = false
  error.value = ''
}

onMounted(() => { void load() })
</script>

<template>
  <section class="cases">
    <div class="cases__head">
      <div>
        <h2>历史案例</h2>
        <p class="hint">
          浏览已完成的社区步行范围研究。
        </p>
      </div>
      <button
        class="reload"
        type="button"
        :disabled="loading"
        @click="load"
      >
        重新加载
      </button>
    </div>

    <p
      v-if="error"
      class="error"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-if="loading"
      class="empty"
      aria-live="polite"
    >
      加载中…
    </p>
    <p
      v-if="!loading && !error && cases.length === 0"
      class="empty"
    >
      暂无历史案例。
    </p>

    <ul
      v-if="cases.length > 0"
      class="case-list"
    >
      <li
        v-for="item in cases"
        :key="item.id"
        class="case-card"
        :class="{ 'case-card--active': item.id === selectedId }"
      >
        <div class="case-card__main">
          <p class="case-card__title">
            {{ item.title }} · {{ item.region }}
          </p>
          <p class="case-card__summary">
            15 分钟步行范围 · 历史社区研究
          </p>
        </div>
        <button
          class="case-card__open"
          type="button"
          @click="openCase(item.id)"
        >
          打开
        </button>
      </li>
    </ul>

    <div
      v-if="caseInfo"
      class="detail"
    >
      <h3>{{ caseInfo.title }}</h3>
      <button
        type="button"
        @click="closeCase"
      >
        关闭案例
      </button>
      <dl class="case-metrics">
        <div><dt>步行范围</dt><dd>{{ caseInfo.range }}</dd></div>
        <div><dt>测量方向</dt><dd>{{ caseInfo.directions }}</dd></div>
        <div><dt>历史边界重合率</dt><dd>{{ caseInfo.iou }}</dd></div>
      </dl>
      <p class="hint">
        历史研究结果，不代表当前社区状况或本次分析的准确率。
      </p>
    </div>
    <p
      v-else-if="!loading && !error && cases.length > 0"
      class="empty"
    >
      {{ detailLoading ? '正在读取案例…' : '选择一个案例查看步行范围。' }}
    </p>
  </section>
</template>

<style scoped>
.cases {
  display: grid;
  gap: 0.75rem;
}
.cases__head {
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  background: var(--color-surface);
  padding: 1rem;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
}
.cases__head h2 {
  margin: 0;
  font-size: 1rem;
}
.hint, .empty { color: var(--color-muted); font-size: 0.85rem; }
.hint { margin: 0.25rem 0 0; }
.empty { margin: 0; }
.error { color: #dc2626; margin: 0; }
.reload {
  flex-shrink: 0;
  padding: 0.4rem 0.8rem;
  border-radius: 0.6rem;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}
.reload:disabled { opacity: 0.6; }
.case-list {
  display: grid;
  gap: 0.75rem;
  margin: 0;
  padding: 0;
  list-style: none;
}
.case-card {
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  background: var(--color-surface);
  padding: 1rem;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
}
.case-card--active { outline: 2px solid var(--color-accent); }
.case-card__title {
  margin: 0;
  font-weight: 700;
}
.case-card__summary {
  margin: 0.25rem 0 0;
  color: var(--color-muted);
  font-size: 0.85rem;
}
.case-card__open {
  flex-shrink: 0;
  padding: 0.4rem 0.8rem;
  border-radius: 0.6rem;
  border: 1px solid var(--color-border);
}
.detail {
  border: 1px solid var(--color-border);
  border-radius: 0.75rem;
  background: var(--color-surface);
  padding: 1rem;
  display: grid;
  gap: 0.5rem;
}
.detail h3 { margin: 0; font-size: 0.9rem; }
.case-metrics { display: grid; gap: .6rem; margin: 0; }
.case-metrics > div { display: flex; justify-content: space-between; gap: 1rem; }
.case-metrics dt { color: var(--color-muted); }
.case-metrics dd { margin: 0; font-weight: 700; }
</style>
