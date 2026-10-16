<!-- 底部安排条（购物车式）：有任务时固定显示，点击弹出安排抽屉。 -->
<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'

import { formatClockSeconds } from '@/domain/time'
import { usePlanStore } from '@/stores/plan'
import { useExecutionStore } from '@/stores/execution'

const emit = defineEmits<{ (event: 'open'): void }>()
defineProps<{ flow?: boolean }>()

const plan = usePlanStore()
const execution = useExecutionStore()
const { tasks, result } = storeToRefs(plan)

const arrivalText = computed(() => {
  if (!result.value || result.value.status !== 'ready') return null
  if (execution.replan?.status === 'infeasible') return null
  const alt = execution.baseAlternative
  return alt ? formatClockSeconds(alt.finishSeconds) : null
})
</script>

<template>
  <button
    type="button"
    class="plan-bar"
    :class="{ 'plan-bar--flow': flow }"
    @click="emit('open')"
  >
    <span class="plan-bar__badge">{{ tasks.length }}</span>
    <span class="plan-bar__text">
      <strong>今天安排</strong>
      <small>{{ arrivalText ? `${arrivalText} 到达终点` : tasks.length ? '待规划' : '添加要去的地点' }}</small>
    </span>
    <span class="plan-bar__cta">查看 ›</span>
  </button>
</template>

<style scoped>
.plan-bar {
  position: sticky;
  bottom: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 0.55rem;
  width: 100%;
  border: 0;
  border-radius: 0.9rem;
  background: linear-gradient(135deg, #1d4ed8, #2563eb);
  color: #fff;
  padding: 0.6rem 0.85rem;
  cursor: pointer;
  box-shadow: 0 6px 18px rgb(29 78 216 / 35%);
}

.plan-bar__badge {
  display: grid;
  place-items: center;
  min-width: 1.5rem;
  height: 1.5rem;
  border-radius: 999px;
  background: rgb(255 255 255 / 22%);
  font-weight: 800;
  font-size: 0.85rem;
}
.plan-bar--flow{position:static}

.plan-bar__text {
  display: grid;
  gap: 0.05rem;
  text-align: left;
  flex: 1;
  min-width: 0;
}

.plan-bar__text strong {
  font-size: 0.85rem;
  line-height: 1.1;
}

.plan-bar__text small {
  font-size: 0.68rem;
  opacity: 0.85;
}

.plan-bar__cta {
  flex: none;
  font-size: 0.75rem;
  font-weight: 700;
  background: rgb(255 255 255 / 18%);
  border-radius: 999px;
  padding: 0.3rem 0.7rem;
}
</style>
