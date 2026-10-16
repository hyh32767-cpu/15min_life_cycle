<script setup lang="ts">
import { useCommunityRadiusStore } from '@/stores/communityRadius'
import { sourceKindLabel } from '@/domain/sourceExplain'
const community = useCommunityRadiusStore()
defineEmits<{ route: [] }>()
</script>

<template>
  <section
    v-if="community.selectedFacility"
    class="facility-card"
    aria-label="生活圈设施详情"
  >
    <header>
      <strong>{{ community.selectedFacility.name }}</strong>
      <button
        type="button"
        aria-label="关闭设施详情"
        @click="community.closeFacility()"
      >
        ✕
      </button>
    </header>
    <p>{{ community.serviceLabel }} · 参评设施 · {{ sourceKindLabel(community.selectedFacility.source) }}</p>
    <p>{{ community.selectedFacility.address || '地址暂未提供' }}</p>
    <button
      type="button"
      class="facility-card__route"
      @click="$emit('route')"
    >
      从圈中心步行到这里
    </button>
  </section>
</template>

<style scoped>
.facility-card { position: absolute; bottom: 12px; left: 12px; right: 12px; z-index: 30; display: grid; gap: 6px; padding: 12px; border-radius: 16px; background: white; color: #26344c; box-shadow: 0 4px 20px #0f172a33; font-size: 13px; }
header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
strong { font-size: 17px; overflow-wrap: anywhere; }
p { margin: 0; color: #64748b; line-height: 1.5; overflow-wrap: anywhere; }
button { font: inherit; min-height: 44px; min-width: 44px; padding: 8px 12px; border: 1px solid #dfe5ef; border-radius: 10px; background: white; color: inherit; cursor: pointer; }
.facility-card__route { color: #2563eb; justify-self: start; }
button:focus-visible { outline: 3px solid #8cafff; outline-offset: 2px; }
</style>
