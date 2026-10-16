<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useRouteBandStore } from '@/stores/routeBand'
import { useCommuteStore } from '@/stores/commute'
import { useIsochroneStore } from '@/stores/isochrone'

const band = useRouteBandStore()
const commute = useCommuteStore()
const router = useRouter()
const count = computed(() => commute.rankedPois.filter(poi => band.includes(poi.place.naviCoord ?? poi.place.coord)).length)
function nodeLabel(index: number): string {
  if (index === 0) return '起点'
  if (index === (band.result?.nodes.length ?? 0) - 1) return '终点'
  return `沿途 ${index}`
}
function community(): void {
  const center = band.focus
  if (!center) return
  const iso = useIsochroneStore()
  const sameCenter = iso.origin?.lng === center.lng && iso.origin?.lat === center.lat && iso.origin?.crs === center.crs
  if (!sameCenter || iso.thresholdSeconds !== band.thresholdSeconds) {
    iso.setOrigin(center, `${nodeLabel(band.selectedIndex)}生活圈`)
    iso.thresholdSeconds = band.thresholdSeconds
  }
  void router.push({ path: '/community', query: { from: 'route-band' } })
}
</script>

<template>
  <section
    v-if="band.enabled"
    class="band-panel"
    aria-label="沿途生活圈"
  >
    <div class="band-title">
      <strong>沿途15分钟生活圈</strong>
      <span v-if="band.result">{{ band.result.completeCount }}/{{ band.result.nodes.length }} 处已测</span>
    </div>
    <p>沿途出发的步行范围，是否顺路还需查看绕行时间。</p>
    <p v-if="band.result && band.result.maxGapM > 0">
      已选位置最大间隔约 {{ Math.round(band.result.maxGapM) }} 米，未填色处不代表不可达。
    </p>
    <p
      v-if="band.loading"
      role="status"
    >
      正在读取已保存范围…
    </p>
    <div
      v-if="band.result"
      class="band-nodes"
      aria-label="沿途采样位置"
    >
      <button
        v-for="node in band.result.nodes"
        :key="node.index"
        :aria-pressed="band.selectedIndex === node.index"
        @click="band.selectedIndex = node.index"
      >
        {{ nodeLabel(node.index) }}
        <small>{{ node.status === 'complete' ? (node.cached ? '已保存' : '已测') : node.status === 'partial' ? '未测完整' : '待测' }}</small>
      </button>
    </div>
    <p
      v-if="band.supplementing"
      role="status"
    >
      正在补齐沿途范围，已完成部分可先查看…
    </p>
    <p v-else-if="band.pendingCount">
      未测完整的位置不填色，可继续补齐。
    </p>
    <p
      v-if="band.error"
      role="alert"
    >
      {{ band.error }}
    </p>
    <div class="band-actions">
      <button
        v-if="band.pendingCount"
        class="primary"
        :disabled="band.loading || band.supplementing || commute.loading"
        @click="band.supplement"
      >
        补齐沿途范围
      </button>
      <button
        v-if="band.error && !band.result"
        :disabled="band.loading"
        @click="band.preview"
      >
        重新读取范围
      </button>
      <button
        :disabled="!band.focus"
        @click="community"
      >
        查看此处社区评分
      </button>
    </div>
    <div
      v-if="band.result?.fills.length"
      class="band-filter"
    >
      <button
        :aria-pressed="band.onlyMeasured"
        @click="band.onlyMeasured = !band.onlyMeasured"
      >
        仅看已测范围内地点
      </button>
      <span>{{ count }} 个{{ commute.category }}地点在范围内</span>
    </div>
  </section>
</template>

<style scoped>
.band-panel{display:grid;gap:10px;padding:14px;border:1px solid #dce0fb;border-radius:16px;background:linear-gradient(135deg,#f4f5ff,#f0f7ff)}
.band-title{display:flex;justify-content:space-between;align-items:center;gap:8px;color:#343980}
.band-title span,.band-filter span{font-size:12px;color:#64748b}
.band-panel p{margin:0;color:#64748b;font-size:12px;line-height:1.6}
.band-panel [role=alert]{color:#b45309}
.band-panel button{font:inherit;font-size:12px;min-height:44px;border:1px solid #dce3f4;border-radius:10px;background:#fff;color:#364569;padding:8px 10px;cursor:pointer}
.band-panel button[aria-pressed=true]{color:#4338ca;background:#e7e9ff;border-color:#9d9aee}
.band-panel button:disabled{opacity:.45;cursor:default}
.band-nodes{display:flex;gap:6px;overflow-x:auto;padding-bottom:2px}
.band-nodes button{flex:1;min-width:52px;padding:7px 6px;white-space:nowrap}
.band-nodes small{display:block;font-size:10px;margin-top:3px;color:#64748b}
.band-actions,.band-filter{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.band-panel button.primary{background:#4f46e5;color:#fff;border-color:#4f46e5}
</style>
