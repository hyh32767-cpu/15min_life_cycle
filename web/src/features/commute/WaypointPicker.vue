<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { PlaceRef } from '@/domain/types'
import PlaceSearch from '@/components/PlaceSearch.vue'
import { useDialog } from '@/composables/useDialog'
import { useCommuteStore } from '@/stores/commute'
import { useMapInteractionStore } from '@/stores/mapInteraction'
import { usePlacesStore } from '@/stores/places'

const props = defineProps<{ open: boolean; initialPlace?: PlaceRef | null; initialMinutes?: number; editing?: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean]; confirm: [place: PlaceRef, minutes: number] }>()
const panel = ref<HTMLElement | null>(null)
const commute = useCommuteStore()
const map = useMapInteractionStore()
const places = usePlacesStore()
const route = useRoute()
const selected = ref<PlaceRef | null>(null)
const name = ref('')
const minutes = ref(10)
const query = ref('')
let returning = false
let awaiting = false
function close(): void { emit('update:open', false) }
useDialog(computed(() => props.open), panel, close)
function choose(place: PlaceRef): void { selected.value = place; name.value = place.name }
watch(() => props.open, open => {
  if (!open) return
  if (returning) { returning = false; return }
  selected.value = null
  name.value = ''
  query.value = ''
  minutes.value = props.initialMinutes ?? commute.stayMinutes
  if (props.initialPlace) choose(props.initialPlace)
})
function beginPick(): void {
  returning = true
  awaiting = true
  map.beginPick('waypoint')
  close()
}
watch(() => map.selectedFor, target => {
  if (target === 'waypoint' && map.selectedPlace) choose(map.selectedPlace)
})
watch(() => map.pickTarget, target => {
  if (!awaiting || target === 'waypoint') return
  awaiting = false
  if (route.name === 'commute') emit('update:open', true)
  else returning = false
})
const canConfirm = computed(() => selected.value && name.value.trim() && Number.isFinite(minutes.value) && minutes.value >= 0 && minutes.value <= 480)
function confirm(): void {
  if (!selected.value || !canConfirm.value) return
  const place = selected.value
  emit('confirm', { ...place, name: name.value.trim(), source: name.value.trim() === place.name ? place.source : 'user-input' }, minutes.value)
  map.clearSelected('waypoint')
  close()
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="waypoint-picker"
      role="dialog"
      aria-modal="true"
      aria-label="选择途经点"
      @click.self="close"
    >
      <section
        ref="panel"
        class="waypoint-picker__panel"
        tabindex="-1"
      >
        <header>
          <strong>{{ editing ? '更换途经点' : '选择途经点' }}</strong><button
            type="button"
            aria-label="关闭途经点选择"
            data-dialog-close
            @click="close"
          >
            ✕
          </button>
        </header>
        <PlaceSearch
          v-model="query"
          :city="commute.city"
          label="搜索途经点"
          placeholder="输入途经地点或地址"
          @select="choose"
        />
        <button
          type="button"
          @click="beginPick"
        >
          地图选位置
        </button>
        <div
          v-if="!query.trim() && places.places.length"
          class="waypoint-picker__saved"
        >
          <small>我的地点</small>
          <button
            v-for="favorite in places.places"
            :key="favorite.id"
            type="button"
            @click="choose({ ...favorite.place, name: favorite.label })"
          >
            {{ favorite.label }}
          </button>
        </div>
        <div
          v-if="selected"
          class="waypoint-picker__selection"
        >
          <label>地点名称<input
            v-model="name"
            aria-label="途经点名称"
          ></label>
          <p>{{ selected.address || selected.name }}</p>
          <label class="waypoint-picker__minutes">停留<input
            v-model.number="minutes"
            type="number"
            min="0"
            max="480"
            aria-label="途经点停留分钟"
          >分钟</label>
        </div>
        <button
          type="button"
          class="primary"
          :disabled="!canConfirm"
          @click="confirm"
        >
          确认途经点
        </button>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.waypoint-picker{position:fixed;inset:0;z-index:55;display:flex;align-items:flex-end;justify-content:center;background:#0f172a66}.waypoint-picker__panel{display:grid;gap:12px;background:white;padding:16px 16px max(16px,env(safe-area-inset-bottom));border-radius:18px 18px 0 0;width:min(480px,100%);max-height:85dvh;overflow:auto;box-sizing:border-box;color:#26344c;font-size:14px}header{display:flex;align-items:center;justify-content:space-between}button,input{font:inherit;min-height:44px;border:1px solid #dfe5ef;border-radius:10px;padding:8px 12px;background:white;color:inherit;box-sizing:border-box}button{cursor:pointer}button:disabled{opacity:.5}input{width:100%;min-width:0}.primary{background:#477beb;color:white;border-color:#477beb}.waypoint-picker__selection{display:grid;gap:10px;padding:12px;border-radius:12px;background:#f4f7fc}.waypoint-picker__selection label{display:grid;gap:6px}.waypoint-picker__minutes{grid-template-columns:auto 80px 1fr;align-items:center}.waypoint-picker__saved{display:grid;gap:6px}.waypoint-picker__saved button{text-align:left}p,small{margin:0;color:#718098;line-height:1.5}button:focus-visible,input:focus-visible{outline:3px solid #8cafff;outline-offset:2px}
</style>
