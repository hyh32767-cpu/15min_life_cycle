<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ items: { id: string; label: string; status: string; coveredCount: number | null; totalGrids: number | null }[] }>()
function point(index: number, scale = 1): { x: number; y: number } {
  const angle = -Math.PI / 2 + index * Math.PI * 2 / props.items.length
  return { x: 170 + Math.cos(angle) * 78 * scale, y: 130 + Math.sin(angle) * 78 * scale }
}
const values = computed(() => props.items.map(item => item.status === 'ready' && item.coveredCount != null && item.totalGrids
  ? item.coveredCount / item.totalGrids : null))
const polygon = computed(() => values.value.every(value => value != null)
  ? values.value.map((value, index) => { const p = point(index, value!); return `${p.x},${p.y}` }).join(' ') : '')
const description = computed(() => props.items.map((item, index) => `${item.label}${values.value[index] == null ? '待查明' : Math.round(values.value[index]! * 100) + '%'}`).join('，'))
</script>

<template>
  <figure class="coverage-radar">
    <figcaption>所选服务覆盖对比</figcaption>
    <svg
      viewBox="0 0 340 270"
      role="img"
      :aria-label="`服务覆盖雷达图：${description}`"
    >
      <polygon
        v-for="scale in [0.25, 0.5, 0.75, 1]"
        :key="scale"
        :points="items.map((_item, index) => { const p = point(index, scale); return `${p.x},${p.y}` }).join(' ')"
        class="coverage-radar__grid"
      />
      <line
        v-for="(item, index) in items"
        :key="item.id"
        x1="170"
        y1="130"
        :x2="point(index).x"
        :y2="point(index).y"
        class="coverage-radar__axis"
      />
      <polygon
        v-if="polygon"
        :points="polygon"
        class="coverage-radar__value"
      />
      <template
        v-for="(item, index) in items"
        :key="item.id"
      >
        <circle
          v-if="values[index] != null"
          :cx="point(index, values[index]!).x"
          :cy="point(index, values[index]!).y"
          r="3.5"
          fill="#6366f1"
        />
        <text
          :x="point(index, 1.42).x"
          :y="point(index, 1.42).y"
          text-anchor="middle"
          dominant-baseline="middle"
        >
          {{ item.label }} {{ values[index] == null ? '待查明' : `${Math.round(values[index]! * 100)}%` }}
        </text>
      </template>
      <text
        x="174"
        y="119"
        class="coverage-radar__scale"
      >0%</text>
      <text
        x="174"
        y="53"
        class="coverage-radar__scale"
      >100%</text>
    </svg>
    <p v-if="!polygon">
      部分结果待查明，暂不绘制完整覆盖面。
    </p>
  </figure>
</template>

<style scoped>
.coverage-radar { margin: 0; min-width: 0; border-bottom: 1px solid #e5e7eb; }
figcaption { color: #334155; font-size: 14px; font-weight: 600; }
svg { display: block; width: 100%; max-width: 340px; margin: auto; }
text { font-size: 12px; fill: #475569; }
.coverage-radar__grid { fill: #f8faff; stroke: #dbe2ef; stroke-width: 1; }
.coverage-radar__axis { stroke: #dbe2ef; }
.coverage-radar__value { fill: #6366f133; stroke: #6366f1; stroke-width: 2; }
.coverage-radar__scale { font-size: 9px; fill: #94a3b8; }
p { margin: 0 0 10px; font-size: 12px; color: #64748b; }
</style>
