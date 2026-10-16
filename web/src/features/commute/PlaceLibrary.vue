<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { PlaceRef } from '@/domain/types'
import PlaceSearch from '@/components/PlaceSearch.vue'
import { useCommuteStore } from '@/stores/commute'
import { usePlacesStore } from '@/stores/places'
import { useRoutePresetsStore } from '@/stores/routePresets'
import { useMapInteractionStore } from '@/stores/mapInteraction'

const emit = defineEmits<{ created: [] }>()
const commute = useCommuteStore()
const places = usePlacesStore()
const routes = useRoutePresetsStore()
const map = useMapInteractionStore()
const query = ref('')
const label = ref('')
const message = ref('')
const startId = ref('')
const endId = ref('')
const routeName = ref('')
const start = computed(() => places.places.find(p => p.id === startId.value))
const end = computed(() => places.places.find(p => p.id === endId.value))
const canCreate = computed(() => Boolean(start.value && end.value && startId.value !== endId.value))

function save(place: PlaceRef): void {
  places.save({ label: label.value.trim() || place.name, place })
  message.value = '地点已保存'
}
function createRoute(): void {
  if (!canCreate.value || !start.value || !end.value) return
  const origin = { ...start.value.place, name: start.value.label }
  const destination = { ...end.value.place, name: end.value.label }
  const preset = routes.save({ name: routeName.value.trim() || origin.name + ' → ' + destination.name,
    company: origin, home: destination, companyQuery: origin.name, homeQuery: destination.name })
  if (preset) { routes.apply(preset); emit('created') }
}
function useAs(place: PlaceRef, slot: 'company' | 'home'): void {
  places.use(place, slot)
  message.value = slot === 'company' ? '已设为起点' : '已设为终点'
}
watch(() => map.selectedFor, target => {
  if (target !== 'saved-place') return
  const coord = map.selected(target)
  if (!coord) return
  const picked = map.selectedPlace
  save({ ...picked, name: picked?.name || '地图地点', coord, source: picked?.source ?? 'user-input' })
  map.clearSelected(target)
})
onBeforeUnmount(() => {
  if (map.pickTarget === 'saved-place') map.pickTarget = null
})
</script>

<template>
  <section
    class="place-library"
    aria-label="我的地点"
  >
    <PlaceSearch
      v-model="query"
      :city="commute.city"
      label="查找保存地点"
      action="保存"
      @select="save"
    />
    <div class="search">
      <input
        v-model="label"
        aria-label="保存地点名称"
        placeholder="地点名称（可选）"
      >
      <button @click="map.beginPick('saved-place')">
        地图创建
      </button>
    </div>
    <div
      class="actions"
      aria-label="保存当前路径地点"
    >
      <button
        v-if="commute.company"
        @click="save(commute.company)"
      >
        保存当前起点
      </button>
      <button
        v-if="commute.home"
        @click="save(commute.home)"
      >
        保存当前终点
      </button>
    </div>
    <p
      v-if="message"
      role="status"
    >
      {{ message }}
    </p>
    <div class="library-title">
      <strong>已保存地点</strong><span>{{ places.places.length }} 个</span>
    </div>
    <p v-if="!places.places.length">
      先搜索或在地图上创建地点，再选两个地点创建路径。
    </p>
    <ul class="rows">
      <li
        v-for="favorite in places.places"
        :key="favorite.id"
      >
        <div class="saved-place">
          <strong>{{ favorite.label }}</strong><small>{{ favorite.place.address || favorite.place.name }}</small>
          <div class="actions">
            <button
              :aria-label="'将 ' + favorite.label + ' 设为起点'"
              @click="useAs({ ...favorite.place, name: favorite.label }, 'company')"
            >
              设为起点
            </button>
            <button
              :aria-label="'将 ' + favorite.label + ' 设为终点'"
              @click="useAs({ ...favorite.place, name: favorite.label }, 'home')"
            >
              设为终点
            </button>
            <button
              :aria-label="'删除保存地点 ' + favorite.label"
              @click="places.remove(favorite.id)"
            >
              删除
            </button>
          </div>
        </div>
      </li>
    </ul>
    <div
      v-if="places.places.length"
      class="route-builder"
    >
      <strong>从地点创建路径</strong>
      <label>起点<select
        v-model="startId"
        aria-label="已保存路径起点"
      ><option
        value=""
        disabled
      >选择地点</option><option
        v-for="place in places.places"
        :key="place.id"
        :value="place.id"
      >{{ place.label }}</option></select></label>
      <label>终点<select
        v-model="endId"
        aria-label="已保存路径终点"
      ><option
        value=""
        disabled
      >选择地点</option><option
        v-for="place in places.places"
        :key="place.id"
        :value="place.id"
      >{{ place.label }}</option></select></label>
      <input
        v-model="routeName"
        aria-label="新建路径名称"
        placeholder="路径名称（可选）"
      >
      <button
        class="primary"
        :disabled="!canCreate"
        @click="createRoute"
      >
        创建并使用路径
      </button>
    </div>
  </section>
</template>

<style scoped>
.place-library{display:grid;gap:12px;background:#f6f8fc;border-radius:14px;padding:12px;font-size:13px}
button,input,select{font:inherit;min-height:44px;border:1px solid #dfe5ef;border-radius:10px;background:white;color:#26344c;padding:8px 10px;box-sizing:border-box}
input,select{width:100%;min-width:0}button{cursor:pointer;flex:none}button:disabled{opacity:.45;cursor:default}
button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #8cafff;outline-offset:2px}
.search{display:flex;gap:8px}.rows{list-style:none;padding:0;margin:0}.rows li{display:flex;gap:8px;align-items:center;padding:10px 0;border-bottom:1px solid #e4e9f2}
.rows li>span,.saved-place{display:grid;gap:6px;min-width:0;width:100%}small,p,.library-title span{font-size:12px;color:#7b879c;line-height:1.6;margin:0}
.actions{display:flex;gap:6px;flex-wrap:wrap}.actions button{font-size:12px;padding:6px 9px}.library-title{display:flex;justify-content:space-between}
.route-builder{display:grid;gap:10px}.route-builder label{display:grid;gap:6px;font-size:12px}.primary{background:#477beb;color:#fff;border-color:#477beb}
</style>

