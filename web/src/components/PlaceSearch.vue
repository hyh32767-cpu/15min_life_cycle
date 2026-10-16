<script setup lang="ts">
import { onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import type { PlaceRef } from '@/domain/types'
import { useAppStore } from '@/stores/app'

const props = withDefaults(defineProps<{
  modelValue?: string
  city?: string
  label?: string
  placeholder?: string
  action?: string
  allowSave?: boolean
  searchType?: 'search' | 'text'
}>(), { modelValue: '', city: '', label: '搜索地点', placeholder: '搜索地点或地址', action: '选择', allowSave: false, searchType: 'text' })
const emit = defineEmits<{ 'update:modelValue': [value: string]; select: [place: PlaceRef]; save: [place: PlaceRef] }>()
const app = useAppStore()
const query = ref(props.modelValue)
const candidates = ref<PlaceRef[]>([])
const loading = ref(false)
const searched = ref(false)
const error = ref('')
let generation = 0
let timer: ReturnType<typeof setTimeout> | undefined
let lastSearch = ''
watch(() => props.modelValue, value => { if (value !== query.value) query.value = value })
function invalidate(): void {
  clearTimeout(timer)
  generation++
  loading.value = false
}
watch([query, () => props.city], () => {
  invalidate()
  candidates.value = []
  searched.value = false
  error.value = ''
  lastSearch = ''
  emit('update:modelValue', query.value)
  if (query.value.trim().length >= 2) timer = setTimeout(() => { void search() }, 700)
}, { flush: 'sync' })
async function search(): Promise<void> {
  clearTimeout(timer)
  const text = query.value.trim()
  if (!text) { error.value = '请输入地点名称或地址'; return }
  const key = `${props.city}:${text}`
  if (lastSearch === key && (loading.value || searched.value) && !error.value) return
  const seq = ++generation
  lastSearch = key
  loading.value = true
  error.value = ''
  candidates.value = []
  try {
    const result = await app.provider.searchLocations(text, props.city || undefined)
    if (seq !== generation) return
    candidates.value = result.candidates
    searched.value = true
  } catch (err) {
    if (seq === generation) error.value = err instanceof Error ? err.message : String(err)
  } finally { if (seq === generation) loading.value = false }
}
function choose(place: PlaceRef): void {
  invalidate()
  candidates.value = []
  searched.value = false
  emit('select', place)
}
onBeforeUnmount(invalidate)
onDeactivated(invalidate)
</script>

<template>
  <div class="place-search">
    <form
      class="place-search__form"
      @submit.prevent="search"
    >
      <input
        v-model="query"
        :type="searchType"
        :aria-label="label"
        :placeholder="placeholder"
        autocomplete="off"
      >
      <button
        type="submit"
        :disabled="loading || !query.trim()"
      >
        {{ loading ? '搜索中…' : '搜索' }}
      </button>
    </form>
    <p
      v-if="loading"
      role="status"
    >
      正在查找地点…
    </p>
    <p
      v-if="error"
      role="alert"
    >
      {{ error }} <button
        type="button"
        @click="search"
      >
        重试
      </button>
    </p>
    <p v-if="searched && !loading && !error && !candidates.length">
      没找到地点，试试完整名称、地址或其他城市。
    </p>
    <ul
      v-if="candidates.length"
      class="place-search__results"
    >
      <li
        v-for="(place, index) in candidates"
        :key="place.uid || index"
      >
        <button
          type="button"
          class="place-search__result result"
          :aria-label="(action === '保存' ? '保存搜索地点 ' : action + ' ') + place.name"
          @click="choose(place)"
        >
          <strong>{{ place.name }}</strong><small>{{ place.address || '暂无详细地址，请在地图上核对位置' }}</small>
        </button>
        <button
          v-if="allowSave"
          type="button"
          :aria-label="'保存地点 ' + place.name"
          @click="emit('save', place)"
        >
          保存
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.place-search{display:grid;gap:8px;min-width:0}.place-search__form{display:flex;gap:8px}
input,button{font:inherit;min-height:44px;border:1px solid #dfe5ef;border-radius:10px;background:white;color:#26344c;padding:8px 10px;box-sizing:border-box}input{min-width:0;flex:1;width:100%}button{cursor:pointer}button:disabled{opacity:.5}p{font-size:12px;color:#687891;margin:0;line-height:1.6}
.place-search__results{list-style:none;padding:0;margin:0;max-height:260px;overflow:auto}.place-search__results li{display:flex;gap:8px;align-items:center;border-bottom:1px solid #e4e9f2}.place-search__result{display:grid;gap:5px;text-align:left;flex:1;min-width:0;border:0;border-radius:0;padding:12px 4px;background:transparent}strong{font-size:14px}small{font-size:12px;color:#718098;line-height:1.5;overflow-wrap:anywhere}
input:focus-visible,button:focus-visible{outline:3px solid #8cafff;outline-offset:2px}
</style>
