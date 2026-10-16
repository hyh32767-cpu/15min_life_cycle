<!-- 原型 UI 重做：地图使用记录。行全部来自实时汇总，无固定占位。 -->
<script setup lang="ts">
import { onMounted } from 'vue'

import { useLedgerReport } from './useLedgerReport'

const { summary, loading, error, refresh } = useLedgerReport()

onMounted(() => {
  void refresh()
})
</script>

<template>
  <div class="ledger-report">
    <div class="ledger-report__head">
      <div>
        <h4>地图使用记录</h4>
        <p class="ledger-report__note">
          地图查询与已保存结果分别统计。
        </p>
      </div>
      <button
        type="button"
        :disabled="loading"
        @click="refresh"
      >
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
    </div>
    <p
      v-if="error"
      class="ledger-report__error"
      role="alert"
    >
      {{ error }}
    </p>
    <dl
      v-else-if="summary"
      class="ledger-report__grid"
    >
      <div><dt>地图查询</dt><dd>{{ summary.liveRequests }}</dd></div>
      <div><dt>复用结果</dt><dd>{{ summary.cacheHits }}</dd></div>
      <div><dt>路线对比</dt><dd>{{ summary.pairs }}</dd></div>
      <div><dt>错误</dt><dd>{{ summary.errors }}</dd></div>
    </dl>
    <p
      v-else
      class="ledger-report__note"
    >
      暂无使用记录
    </p>
    <ul
      v-if="summary?.byInterface?.length"
      class="ledger-report__list"
    >
      <li
        v-for="row in summary.byInterface"
        :key="row.key"
      >
        地图查询 {{ summary.byInterface.indexOf(row) + 1 }} · {{ row.requests }} 次
      </li>
    </ul>
  </div>
</template>

<style scoped>
.ledger-report { display: grid; gap: 0.75rem; font-size: 0.8rem; }
.ledger-report__head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem; }
.ledger-report__head h4 { margin: 0; font-size: 0.9rem; }
.ledger-report__note { margin: 0.2rem 0 0; color: var(--color-muted); font-size: 0.72rem; }
.ledger-report__error { color: #b91c1c; margin: 0; }
.ledger-report__grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.5rem; margin: 0; }
.ledger-report__grid div { border: 1px solid var(--color-border); border-radius: 0.5rem; padding: 0.4rem; text-align: center; }
.ledger-report__grid dt { font-size: 0.65rem; color: var(--color-muted); }
.ledger-report__grid dd { margin: 0.15rem 0 0; font-weight: 700; }
.ledger-report__list { margin: 0; padding-left: 1rem; color: var(--color-muted); font-size: 0.72rem; }
</style>
