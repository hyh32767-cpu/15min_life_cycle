<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useAppStore } from '@/stores/app'
import type { ServiceAssessment } from './report'
const props = defineProps<{profiles: ServiceAssessment[]; busy: boolean}>()
const app = useAppStore()
const text = ref(''), scope = ref(''), error = ref(''), loading = ref(false)
let controller: InstanceType<typeof window.AbortController> | null = null
const input = computed(() => props.profiles.map(p => ({id:p.id,covered:p.coveredCount,total:p.totalGrids,facilities:p.facilityCount,status:p.status})))
const ready = computed(() => !props.busy && input.value.length > 0 && input.value.every(p => p.status === 'ready' && p.covered != null && p.total && p.facilities != null))
function clear(): void {
  controller?.abort(); controller = null
  text.value = ''; scope.value = ''; error.value = ''; loading.value = false
}
watch(() => JSON.stringify([input.value,props.busy]),clear)
onBeforeUnmount(clear)
async function generate(): Promise<void> {
  if (!ready.value || loading.value) return
  const current = new window.AbortController()
  controller = current; loading.value = true; error.value = ''
  try {
    if (!app.provider.getCommunityInsight) throw new Error('社区解读暂不可用')
    const result = await app.provider.getCommunityInsight(input.value.map(p => ({id:p.id,covered:p.covered!,total:p.total!,facilities:p.facilities!})),current.signal)
    if (controller !== current) return
    text.value = result.summary; scope.value = result.scope
  } catch (err) {
    if (controller === current) error.value = err instanceof Error ? err.message : '解读暂时不可用'
  } finally { if (controller === current) loading.value = false }
}
</script>

<template>
  <section
    class="community-insight"
    aria-label="社区解读"
  >
    <div class="community-insight__head">
      <strong>社区解读 <small>AI</small></strong>
      <button
        v-if="!text"
        type="button"
        :disabled="!ready || loading"
        @click="generate"
      >
        {{ loading ? '正在整理…' : error ? '重试' : '看看建议' }}
      </button>
    </div>
    <p v-if="text">
      {{ text }}
    </p>
    <p
      v-else-if="error"
      role="status"
    >
      {{ error }}
    </p>
    <span v-else>{{ ready ? '用几句话看看社区服务的长处与不足' : '设施查询完成后，可查看解读' }}</span>
    <small
      v-if="text"
      class="community-insight__scope"
    >{{ scope }}</small>
  </section>
</template>

<style scoped>
.community-insight{margin:16px 0;padding:16px;border:1px solid #dbe7ff;border-radius:18px;background:#f5f8ff;color:#24364b}
.community-insight__head{display:flex;align-items:center;justify-content:space-between;gap:12px}
.community-insight__head strong{font-size:16px}.community-insight__head small{font-size:10px;margin-left:4px;color:#4676df}
.community-insight button{border:0;border-radius:20px;padding:9px 14px;min-height:40px;background:#e7efff;color:#2461e9;font:inherit;font-size:13px;font-weight:600}
.community-insight button:disabled{opacity:.5}.community-insight p{font-size:14px;line-height:1.8;margin:12px 0 0;overflow-wrap:anywhere}
.community-insight>span,.community-insight__scope{display:block;margin-top:10px;font-size:12px;color:#74839a;line-height:1.6}
</style>
