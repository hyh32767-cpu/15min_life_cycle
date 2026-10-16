<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ directions?: number; heat?: boolean; compact?: boolean; frontier?: { phase: string; samples: unknown[]; currentShellM?: number | null } }>()
const title = computed(() => props.heat ? '正在测量时间分层' : props.frontier?.phase === 'interior-check' ? '正在检查内部缺口' : props.frontier ? '正在从外围测量边界' : props.directions ? '正在完善边界' : '正在测量步行范围')
</script>

<template>
  <div
    class="circle-loading"
    :class="{ 'circle-loading--compact': compact }"
    role="status"
    aria-live="polite"
  >
    <span
      class="circle-loading__radar"
      aria-hidden="true"
    ><i /><b /></span>
    <span class="circle-loading__copy"><strong>{{ title }}</strong><small>{{ frontier ? `已测 ${frontier.samples.length} 个位置 · 虚线随测点更新` : directions ? `已显示 ${directions} 个方向的实测范围` : '首轮完成后，范围会立即显示' }}</small></span>
    <span
      class="circle-loading__dots"
      aria-hidden="true"
    ><i /><i /><i /></span>
  </div>
</template>

<style scoped>
.circle-loading{display:flex;align-items:center;gap:12px;padding:13px 14px;border:1px solid #d8e5ff;border-radius:16px;background:#f5f9ff;color:#1e4db1}.circle-loading__copy{display:grid;gap:4px;min-width:0}.circle-loading strong{font-size:14px;font-weight:650}.circle-loading small{font-size:12px;color:#657b9b;line-height:1.4}.circle-loading__radar{position:relative;display:block;flex:none;width:36px;height:36px;border:1px solid #c6d9ff;border-radius:50%;background:repeating-radial-gradient(circle,#dce9ff 0 1px,transparent 2px 8px);overflow:hidden}.circle-loading__radar i{position:absolute;inset:0;border-radius:50%;background:conic-gradient(from 0deg,transparent 0 70%,#3c7aff55);animation:circle-scan 2.4s linear infinite}.circle-loading__radar b{position:absolute;inset:15px;border-radius:50%;background:#2563eb;box-shadow:0 0 0 4px #2563eb15}.circle-loading__dots{display:flex;gap:3px;margin-left:auto}.circle-loading__dots i{width:4px;height:4px;background:#82a8ee;border-radius:50%;animation:circle-dot 1.5s ease-in-out infinite}.circle-loading__dots i:nth-child(2){animation-delay:.2s}.circle-loading__dots i:nth-child(3){animation-delay:.4s}.circle-loading--compact{box-shadow:0 5px 24px #1c407015;background:#ffffffed;backdrop-filter:blur(12px)}
@keyframes circle-scan{to{transform:rotate(360deg)}}@keyframes circle-dot{50%{opacity:.25;transform:translateY(-2px)}}
@media(prefers-reduced-motion:reduce){.circle-loading__radar i,.circle-loading__dots i{animation:none}}
</style>
