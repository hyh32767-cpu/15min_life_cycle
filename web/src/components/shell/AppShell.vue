<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { notifyHydrated, usePersistenceStore } from '@/stores/persistence'
import { useCommuteStore } from '@/stores/commute'
import { useIsochroneStore } from '@/stores/isochrone'
import { useMapInteractionStore } from '@/stores/mapInteraction'
import { useMapRouteStore } from '@/stores/mapRoute'
import { usePlacesStore } from '@/stores/places'
import { usePlanStore } from '@/stores/plan'
import { useDialog } from '@/composables/useDialog'
import type { PlaceRef } from '@/domain/types'
import PlaceSearch from '@/components/PlaceSearch.vue'
import { useRoutePresetsStore, type RoutePreset } from '@/stores/routePresets'

const app = useAppStore(), persistence = usePersistenceStore(), commute = useCommuteStore()
const iso = useIsochroneStore(), interaction = useMapInteractionStore(), mapRoute = useMapRouteStore()
const places = usePlacesStore(), route = useRoute(), plan = usePlanStore()
const presets = useRoutePresetsStore(), router = useRouter()
const snap = ref(1), sheetContent = ref<HTMLElement | null>(null)
const reportOpen = ref(false), reportPanel = ref<HTMLElement | null>(null)
const searchOpen = ref(false), searchPanel = ref<HTMLElement | null>(null)
const searchTarget = ref<'center' | 'start' | 'end' | 'waypoint'>('center')
const showSaved = ref(false)
const addingFavorite = ref(false)
const favoriteNotice = ref('')
const favoriteTab = ref<'places' | 'routes'>('places')
const favoriteRouteName = ref(''), favoriteStart = ref(''), favoriteEnd = ref('')
function saveCurrentRoute(): void {
  if (!commute.company || !commute.home) return
  presets.save({ name: favoriteRouteName.value.trim() || `${commute.company.name} → ${commute.home.name}`,
    company: commute.company, home: commute.home, companyQuery: commute.companyQuery, homeQuery: commute.homeQuery,
    waypointTasks: plan.tasks, visitOrder: plan.visitOrder })
  favoriteRouteName.value = ''; favoriteNotice.value = '路线已收藏'
}
function createFavoriteRoute(): void {
  const start = places.places.find(item => item.id === favoriteStart.value)
  const end = places.places.find(item => item.id === favoriteEnd.value)
  if (!start || !end || start.id === end.id) return
  presets.save({ name: favoriteRouteName.value.trim() || `${start.label} → ${end.label}`,
    company: start.place, home: end.place, companyQuery: start.place.name, homeQuery: end.place.name,
    waypointTasks: [], visitOrder: [] })
  favoriteRouteName.value = ''; favoriteNotice.value = '路线已收藏'
}
async function useFavoriteRoute(preset: RoutePreset): Promise<void> {
  if (iso.busy) return
  searchOpen.value = false
  if (route.name !== 'commute') await router.push('/')
  presets.apply(preset)
}
watch(snap, () => { void nextTick(() => window.dispatchEvent(new Event('map-visible-area-change'))) })
const isLife = computed(() => route.name === 'community')
const sheetTitle = computed(() => isLife.value ? '步行生活圈' : route.name === 'cases' ? '历史案例' : '顺路办事')
const searchLabel = computed(() => isLife.value ? iso.originLabel || '搜索社区、地标或地址' : '搜索地点，加入沿途行程')
useDialog(reportOpen, reportPanel, () => { reportOpen.value = false })
useDialog(searchOpen, searchPanel, () => { searchOpen.value = false })
let dragStart: number | null = null, dragged = false
function toggleSheet(): void { if (dragged) { dragged = false; return }; snap.value = (snap.value + 1) % 3 }
function startDrag(e: PointerEvent): void { dragStart = e.clientY; dragged = false; (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId) }
function finishDrag(e: PointerEvent): void { if (dragStart == null) return; const delta = e.clientY - dragStart; dragStart = null; if (Math.abs(delta) > 30) { dragged = true; snap.value = Math.max(0, Math.min(2, snap.value + (delta < 0 ? 1 : -1))) } }
function openSearch(saved = false): void { if (iso.busy) return; if (isLife.value) favoriteTab.value = 'places'; showSaved.value = saved; addingFavorite.value = false; favoriteNotice.value = ''; searchTarget.value = isLife.value ? 'center' : 'end'; searchOpen.value = true }
function saveFavorite(place: PlaceRef): void {
  if (!places.save({ label: place.name, place })) return
  favoriteNotice.value = `已收藏 ${place.name}`
  if (addingFavorite.value) { showSaved.value = true; addingFavorite.value = false }
}
function saveCircleCenter(): void {
  if (iso.origin) saveFavorite({ name: iso.originLabel || '地图地点', coord: { ...iso.origin }, source: 'user-input' })
}
function guardNavigation(event: Event): void { if (iso.busy) { event.preventDefault(); event.stopImmediatePropagation() } }
watch(() => iso.busy, busy => { if (busy) { searchOpen.value = false; reportOpen.value = false; interaction.pickTarget = null } })
watch(() => interaction.placePickerRequested, requested => { if (requested) { openSearch(); interaction.placePickerRequested = false } })
async function choose(place: PlaceRef): Promise<void> {
  if (iso.busy) return
  const target = searchTarget.value
  if (target === 'center') {
    if (route.name !== 'community') await router.push('/community')
    iso.setOrigin(place.naviCoord ?? place.coord, place.name)
  } else {
    if (route.name !== 'commute') await router.push('/')
    if (target === 'waypoint') interaction.waypointRequest = { place }
    else places.use(place, target === 'start' ? 'company' : 'home')
  }
  searchOpen.value = false
  snap.value = 1
}
let favoritePickRoute: string | null = null
function pick(): void {
  favoritePickRoute = addingFavorite.value ? route.fullPath : null
  interaction.beginPick(addingFavorite.value ? 'saved-place' : searchTarget.value === 'center' ? 'community-center' : searchTarget.value === 'start' ? 'route-start' : searchTarget.value === 'end' ? 'route-end' : 'waypoint')
  searchOpen.value = false; snap.value = 0
}
watch(() => interaction.pickTarget, target => {
  snap.value = target ? 0 : 1
  if (favoritePickRoute == null || target === 'saved-place') return
  const samePage = favoritePickRoute === route.fullPath
  favoritePickRoute = null
  if (!samePage) return
  if (interaction.selectedFor === 'saved-place' && interaction.selectedPlace) {
    saveFavorite(interaction.selectedPlace)
    interaction.clearSelected('saved-place')
  }
  searchOpen.value = true
})
watch(() => interaction.editingWaypoints, editing => { if (editing) snap.value = 2 })
watch(() => interaction.panelExpandRequested, requested => { if (requested) { snap.value = 2; interaction.panelExpandRequested = false } })
watch(() => mapRoute.destination, value => { if (value) snap.value = 0 })
watch(() => route.name, () => { interaction.pickTarget = null; interaction.editingWaypoints = false; snap.value = 1; reportOpen.value = false; searchOpen.value = false; void nextTick(() => { if (sheetContent.value) sheetContent.value.scrollTop = 0 }) })
onMounted(async () => { const restored = persistence.restore(); persistence.startAutoPersist(); notifyHydrated(restored); await app.loadHealth() })
</script>

<template>
  <div
    class="shell"
    :class="{ 'shell--picking': interaction.pickTarget, 'shell--expanded': snap === 2 }"
    :style="{ '--sheet-height': ['20dvh', '48dvh', '82dvh'][snap] }"
  >
    <div class="shell__map">
      <slot name="map" />
    </div>
    <section
      class="sheet"
      :class="{ 'sheet--expanded': snap === 2, 'sheet--picking': interaction.pickTarget }"
    >
      <header class="shell__omni">
        <div class="shell__brand-row">
          <div class="shell__brand">
            <span class="shell__brand-mark">⌁</span><strong>顺路</strong><small>附近生活 · 顺路办事</small>
          </div>
        </div>
        <nav
          class="shell__nav"
          aria-label="主导航"
        >
          <RouterLink
            to="/community"
            class="shell__nav-item"
            :aria-disabled="iso.busy"
            :tabindex="iso.busy ? -1 : undefined"
            @click.capture="guardNavigation"
          >
            <AppIcon
              name="circle"
              :size="18"
            /> 生活圈
          </RouterLink><RouterLink
            to="/"
            class="shell__nav-item"
            :aria-disabled="iso.busy"
            :tabindex="iso.busy ? -1 : undefined"
            @click.capture="guardNavigation"
          >
            <AppIcon
              name="route"
              :size="18"
            /> 顺路办事
          </RouterLink>
        </nav>
      </header>
      <div
        class="sheet__handle"
        role="button"
        tabindex="0"
        aria-label="展开或收起面板"
        :aria-expanded="snap === 2"
        @click="toggleSheet"
        @pointerdown="startDrag"
        @pointerup="finishDrag"
        @pointercancel="dragStart = null"
        @keydown.enter="toggleSheet"
        @keydown.space.prevent="toggleSheet"
      >
        <i class="sheet__grabber" /><span
          v-if="route.name === 'cases'"
          class="sheet__title"
        >{{ sheetTitle }}</span><span class="sheet__toggle">{{ snap === 2 ? '收起看图 ↓' : '展开 ↑' }}</span>
      </div>
      <div
        v-if="route.name !== 'cases'"
        class="shell__search-row sheet__search-row"
      >
        <button
          class="shell__search"
          :disabled="iso.busy"
          @click="openSearch()"
        >
          <AppIcon
            name="search"
            :size="18"
          /><span :class="{ 'origin-name': isLife }">{{ searchLabel }}</span>
        </button>
        <button
          class="shell__saved"
          :disabled="iso.busy"
          @click="openSearch(true)"
        >
          <AppIcon
            name="bookmark"
            :size="17"
          /> 我的收藏
        </button>
      </div>
      <div
        ref="sheetContent"
        class="sheet__content"
      >
        <fieldset
          class="sheet__actions"
          :disabled="iso.busy"
          :inert="iso.busy"
        >
          <slot /><footer class="shell__footer">
            <RouterLink to="/cases">
              历史案例
            </RouterLink><button
              class="text"
              @click="reportOpen = true"
            >
              使用记录
            </button>
          </footer>
        </fieldset>
      </div>
    </section>
    <div
      v-if="isLife"
      class="shell__layers"
    >
      <button
        :class="{ active: interaction.showFacilities }"
        :disabled="iso.busy"
        @click="interaction.showFacilities = !interaction.showFacilities"
      >
        <AppIcon
          name="pin"
          :size="16"
        /> 设施
      </button>
    </div>
    <div
      v-if="reportOpen"
      class="shell-modal"
      role="dialog"
      aria-modal="true"
      aria-label="地图使用记录"
      @click.self="reportOpen = false"
    >
      <div
        ref="reportPanel"
        class="shell-modal__card"
        tabindex="-1"
      >
        <header>
          <h3>地图使用记录</h3><button
            data-dialog-close
            aria-label="关闭报告"
            @click="reportOpen = false"
          >
            ✕
          </button>
        </header><slot name="report" />
      </div>
    </div>
    <div
      v-if="searchOpen"
      class="shell-modal"
      role="dialog"
      aria-modal="true"
      :aria-label="showSaved ? '我的收藏' : addingFavorite ? '添加收藏' : '选择地点'"
      @click.self="searchOpen = false"
    >
      <div
        ref="searchPanel"
        class="shell-modal__card"
        :class="{ 'place-picker-modal': !showSaved }"
        tabindex="-1"
      >
        <header>
          <h3>{{ showSaved ? '我的收藏' : addingFavorite ? '添加收藏' : '选择地点' }}</h3><button
            data-dialog-close
            aria-label="关闭地点选择"
            @click="searchOpen = false"
          >
            <AppIcon
              name="close"
              :size="18"
            />
          </button>
        </header>
        <div
          v-if="showSaved"
          class="favorite-list"
        >
          <div
            v-if="!isLife"
            class="favorite-tabs"
            role="tablist"
            aria-label="收藏分类"
          >
            <button
              role="tab"
              :aria-selected="favoriteTab === 'places'"
              @click="favoriteTab = 'places'; favoriteNotice = ''"
            >
              地点 {{ places.places.length }}
            </button>
            <button
              role="tab"
              :aria-selected="favoriteTab === 'routes'"
              @click="favoriteTab = 'routes'; favoriteNotice = ''"
            >
              路线 {{ presets.presets.length }}
            </button>
          </div>
          <div
            v-if="!isLife && favoriteTab === 'routes'"
            class="favorite-routes"
          >
            <p
              v-if="favoriteNotice"
              class="favorite-notice"
              role="status"
            >
              {{ favoriteNotice }}
            </p>
            <details class="favorite-route-create">
              <summary>＋ 收藏路线</summary>
              <input
                v-model="favoriteRouteName"
                aria-label="收藏路线名称"
                placeholder="路线名称（可选）"
              >
              <div
                v-if="commute.company && commute.home"
                class="favorite-route-current"
              >
                <small>{{ commute.company.name }} → {{ commute.home.name }}</small>
                <button @click="saveCurrentRoute">
                  收藏当前路线
                </button>
              </div>
              <label>起点<select
                v-model="favoriteStart"
                aria-label="收藏路线起点"
              ><option value="">选择收藏地点</option><option
                v-for="item in places.places"
                :key="item.id"
                :value="item.id"
              >{{ item.label }}</option></select></label>
              <label>终点<select
                v-model="favoriteEnd"
                aria-label="收藏路线终点"
              ><option value="">选择收藏地点</option><option
                v-for="item in places.places"
                :key="item.id"
                :value="item.id"
              >{{ item.label }}</option></select></label>
              <button
                :disabled="!places.places.some(p => p.id === favoriteStart) || !places.places.some(p => p.id === favoriteEnd) || favoriteStart === favoriteEnd"
                @click="createFavoriteRoute"
              >
                从收藏地点创建路线
              </button>
            </details>
            <div
              v-if="!presets.presets.length"
              class="favorite-empty"
            >
              <span aria-hidden="true">↗</span><strong>还没有收藏路线</strong><small>收藏当前路线，或用收藏地点创建。</small>
            </div>
            <div
              v-for="preset in [...presets.presets].reverse()"
              :key="preset.id"
              class="favorite-route-row"
            >
              <button
                class="shell-picker__place"
                @click="useFavoriteRoute(preset)"
              >
                <strong>{{ preset.name }}</strong><small>{{ preset.company.name }} → {{ preset.home.name }}</small>
              </button>
              <button
                :aria-label="`删除收藏路线 ${preset.name}`"
                @click="presets.remove(preset.id)"
              >
                ×
              </button>
            </div>
          </div>
          <template v-else>
            <div class="favorite-current">
              <button
                v-if="isLife && iso.origin"
                @click="saveCircleCenter"
              >
                收藏当前地点
              </button>
              <button
                v-if="!isLife && commute.company"
                @click="saveFavorite(commute.company)"
              >
                收藏当前起点
              </button>
              <button
                v-if="!isLife && commute.home"
                @click="saveFavorite(commute.home)"
              >
                收藏当前终点
              </button>
            </div>
            <div class="favorite-list__head">
              <small>{{ places.places.length }} 个收藏地点</small>
              <button @click="showSaved = false; addingFavorite = true; favoriteNotice = ''">
                ＋ 添加收藏
              </button>
            </div>
            <p
              v-if="favoriteNotice"
              class="favorite-notice"
              role="status"
            >
              {{ favoriteNotice }}
            </p>
            <div
              v-if="!places.places.length"
              class="favorite-empty"
            >
              <span aria-hidden="true">☆</span><strong>还没有收藏地点</strong><small>添加常去的地点，下次直接选择。</small>
            </div>
            <template v-else>
              <div
                class="shell-picker__targets"
              >
                <button
                  :class="{ active: searchTarget === 'center' }"
                  @click="searchTarget = 'center'"
                >
                  生活圈中心
                </button>
                <button
                  :class="{ active: searchTarget === 'start' }"
                  @click="searchTarget = 'start'"
                >
                  设起点
                </button>
                <button
                  :class="{ active: searchTarget === 'end' }"
                  @click="searchTarget = 'end'"
                >
                  设终点
                </button>
                <button
                  :class="{ active: searchTarget === 'waypoint' }"
                  :disabled="plan.tasks.length >= 5"
                  @click="searchTarget = 'waypoint'"
                >
                  加途经点
                </button>
              </div>
              <div
                v-for="item in [...places.places].reverse()"
                :key="item.id"
                class="favorite-place-row"
              >
                <button
                  class="shell-picker__place"
                  @click="choose(item.place)"
                >
                  <strong>{{ item.label }}</strong><small>{{ item.place.address || item.place.name }}</small>
                </button>
                <button
                  :aria-label="`删除收藏地点 ${item.label}`"
                  @click="places.remove(item.id)"
                >
                  ×
                </button>
              </div>
            </template>
          </template>
        </div>
        <div
          v-else
          class="shell-picker"
        >
          <button
            v-if="addingFavorite"
            class="text"
            @click="showSaved = true; addingFavorite = false"
          >
            ‹ 返回我的收藏
          </button>
          <p
            v-if="favoriteNotice"
            class="favorite-notice"
            role="status"
          >
            {{ favoriteNotice }}
          </p>
          <div
            v-if="!isLife && !addingFavorite"
            class="shell-picker__targets"
          >
            <button
              :class="{ active: searchTarget === 'start' }"
              @click="searchTarget = 'start'"
            >
              设起点
            </button><button
              :class="{ active: searchTarget === 'end' }"
              @click="searchTarget = 'end'"
            >
              设终点
            </button><button
              :class="{ active: searchTarget === 'waypoint' }"
              :disabled="plan.tasks.length >= 5"
              @click="searchTarget = 'waypoint'"
            >
              加途经点
            </button>
          </div>
          <div class="location-search">
            <AppIcon
              class="location-search__icon"
              name="search"
              :size="18"
            />
            <PlaceSearch
              search-type="search"
              city="全国"
              :action="addingFavorite ? '收藏' : '选择'"
              :allow-save="!addingFavorite"
              @select="place => addingFavorite ? saveFavorite(place) : choose(place)"
              @save="saveFavorite"
            />
          </div>
          <div class="location-tools">
            <button
              class="location-map-pick"
              aria-label="地图选位置"
              @click="pick"
            >
              <AppIcon
                name="location"
                :size="17"
              />地图选点
            </button>
          </div>
          <section
            v-if="!addingFavorite"
            class="picker-saved"
            aria-label="收藏地点快捷选择"
          >
            <header v-if="places.places.length">
              <strong>收藏地点</strong><small>{{ places.places.length }} 个</small>
            </header>
            <button
              v-for="item in places.places"
              :key="item.id"
              class="shell-picker__place"
              @click="choose(item.place)"
            >
              <AppIcon
                name="bookmark"
                :size="17"
              /><span><strong>{{ item.label }}</strong><small>{{ item.place.address || item.place.name }}</small></span>
            </button>
            <p
              v-if="!places.places.length"
              class="picker-saved__empty"
            >
              <AppIcon
                name="bookmark"
                :size="17"
              />还没有收藏地点
            </p>
          </section>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sheet__search-row{flex:none;margin:10px 14px 0;min-height:42px}.sheet__search-row .shell__search{display:flex;align-items:center;gap:8px}.sheet__search-row .shell__search span{margin:0}.sheet__search-row .shell__search span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.sheet__search-row .shell__saved{border-left:1px solid #dce4ee;border-radius:0;min-height:24px;margin-right:5px;color:#547297}.sheet__search-row .origin-name{font-weight:550;color:#455b79}
@media(min-width:821px){.shell .sheet{top:14px}}
.favorite-current{display:flex;flex-wrap:wrap;gap:6px}.favorite-current:empty{display:none}.favorite-current button{font-size:11px;color:#2863df;background:#f5f8ff}
.favorite-tabs{display:flex;gap:4px;padding:4px;background:#f1f5f9;border-radius:12px}.favorite-tabs button{flex:1;border:0;background:transparent;color:#718098}.favorite-tabs button[aria-selected="true"]{background:white;color:#2863df;font-weight:600;box-shadow:0 1px 5px #17243a0d}.favorite-routes{display:grid;gap:12px}.favorite-route-create{padding:10px;border:1px solid #e7edf5;border-radius:12px;font-size:12px}.favorite-route-create summary{cursor:pointer;color:#2863df;min-height:30px;line-height:30px}.favorite-route-create input,.favorite-route-create select{font:inherit;border:1px solid #dfe6f0;border-radius:8px;min-height:40px;padding:6px 8px;box-sizing:border-box;width:100%;min-width:0}.favorite-route-create label{display:grid;grid-template-columns:35px minmax(0,1fr);gap:8px;align-items:center;margin-top:10px}.favorite-route-create>button{margin-top:10px;width:100%;color:#2863df}.favorite-route-current{display:grid;gap:8px;padding:12px 0;border-bottom:1px solid #edf1f6;color:#718098}.favorite-route-row{display:flex;gap:8px;align-items:center}.favorite-route-row .shell-picker__place{flex:1;min-width:0}.favorite-route-row .shell-picker__place small{white-space:normal;line-height:1.5}.favorite-list .shell-picker__targets{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}
.favorite-list{display:grid;gap:10px;min-height:150px}.favorite-list__head{display:flex;justify-content:space-between;align-items:center;gap:10px}.favorite-list__head small,.favorite-list .shell-picker__place small{font-size:12px;color:#7b899d}.favorite-list .shell-picker__place{min-height:62px;padding:12px;gap:5px}.favorite-empty{display:grid;justify-items:center;gap:9px;text-align:center;padding:26px 12px 30px;color:#68798e}.favorite-empty>span{font-size:34px;color:#9ab3de}.favorite-empty strong{font-size:14px;color:#34465e}.favorite-empty small{font-size:12px}.favorite-notice{margin:0;font-size:12px;color:#2863d6;line-height:1.5}
.sheet__actions{border:0;margin:0;padding:0;min-width:0}.shell__nav-item[aria-disabled="true"]{opacity:.5;cursor:wait}
.shell{height:100dvh;width:100%;overflow:hidden;position:relative;background:#eef2f6;--sheet-height:48dvh;color:#17243a}.shell__map{position:absolute;inset:0}.shell__omni{position:absolute;z-index:25;top:14px;left:14px;width:408px;box-sizing:border-box;padding:12px 14px;display:grid;gap:9px;background:#fffffff5;border:1px solid #e2e8f080;border-radius:18px;box-shadow:0 10px 30px #18283d20;backdrop-filter:blur(18px)}.shell__brand-row,.shell__brand{display:flex;align-items:center;gap:8px}.shell__brand-row{justify-content:space-between}.shell__brand strong{font-size:15px}.shell__brand small{font-size:10px;color:#4d73aa}.shell__brand-mark{width:28px;height:28px;display:grid;place-items:center;border-radius:8px;background:#3863f5;color:white;font-size:18px}.shell button{font:inherit;cursor:pointer;min-height:38px;border:1px solid #dfe6f0;background:white;border-radius:10px;padding:7px 10px;font-size:12px;color:#334155}.shell .text{border:0;background:none;color:#2863d6;padding:3px 6px}.shell button:disabled{opacity:.5;cursor:default}.shell__search-row{display:flex;align-items:center;background:#f1f5f9;border-radius:12px;min-width:0}.shell .shell__search{flex:1;min-width:0;text-align:left;background:none;border:0;color:#68798f;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px;min-height:42px}.shell__search span{margin-right:8px}.shell .shell__saved{border:0;background:none;font-size:11px;flex:none;color:#4f647d}.shell__nav{display:flex;gap:4px;background:#f0f3f8;border-radius:12px;padding:4px}.shell__nav-item{flex:1;text-align:center;padding:8px;color:#718098;font-size:12.5px;font-weight:700;border-radius:9px;text-decoration:none}.shell__nav-item.router-link-exact-active{background:white;color:#2563eb;box-shadow:0 2px 6px #17243a09}.sheet{position:absolute;z-index:24;left:14px;top:191px;bottom:14px;width:408px;background:#fffffff5;border:1px solid #e2e8f080;border-radius:18px;display:flex;flex-direction:column;box-shadow:0 10px 30px #18283d20;backdrop-filter:blur(18px);overflow:hidden}.sheet__handle{display:flex;align-items:center;justify-content:space-between;flex:none;padding:9px 14px;border-bottom:1px solid #e9edf4;color:#6a7c94;font-size:11px;cursor:pointer;touch-action:none}.sheet__grabber{display:none}.sheet__title{font-weight:650}.sheet__content{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;padding:13px 14px}.shell__footer{display:flex;align-items:center;justify-content:space-around;border-top:1px solid #e4eaf2;margin-top:16px;padding-top:6px}.shell__footer a{font-size:11px;text-decoration:none;color:#6a7c94}.shell__layers{position:absolute;z-index:23;right:14px;top:14px;display:flex;gap:6px}.shell__layers button{background:#ffffffed;border-radius:20px;box-shadow:0 3px 12px #17243a12;font-size:11px;min-height:34px}.shell .active{background:#eff5ff;border-color:#8ab0fa;color:#2563eb}.shell--dock-collapsed .sheet{display:none}.shell-modal{position:fixed;inset:0;z-index:80;background:#10243b55;display:flex;align-items:center;justify-content:center;padding:20px}.shell-modal__card{width:460px;max-width:100%;max-height:86dvh;overflow:auto;background:white;border-radius:20px;padding:16px;box-sizing:border-box}.shell-modal__card>header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.shell-modal h3{font-size:16px;margin:0}.shell-picker{display:grid;gap:12px}.shell-picker__targets{display:flex;gap:6px}.shell-picker__targets button{flex:1}.shell-picker__city{display:flex;gap:10px;align-items:center;font-size:12px}.shell-picker input{border:1px solid #dfe6f0;border-radius:10px;min-height:40px;min-width:0;padding:8px;font:inherit;flex:1}.shell .shell-picker__place{display:grid;text-align:left;gap:4px}.shell-picker small{font-size:11px;color:#7b899d}.shell button:focus-visible,.sheet__handle:focus-visible{outline:3px solid #92b5f5;outline-offset:2px}
@media(max-width:820px){.shell__omni{top:max(8px,env(safe-area-inset-top));left:10px;width:calc(100% - 20px);padding:9px 11px;gap:7px;border-radius:16px}.shell__brand-row{display:none}.shell .shell__search{min-height:39px;font-size:12px}.shell__nav-item{padding:7px;font-size:12px}.sheet{left:0;right:0;top:auto;bottom:0;width:100%;height:var(--sheet-height);border-radius:22px 22px 0 0;transition:height .23s;box-sizing:border-box;padding-bottom:env(safe-area-inset-bottom)}.sheet__handle{display:grid;grid-template-columns:1fr auto;gap:7px;padding:8px 14px 7px;min-height:39px;box-sizing:border-box}.sheet__grabber{display:block;grid-column:1/-1;width:34px;height:4px;justify-self:center;border-radius:5px;background:#cbd5e1}.sheet__content{padding:12px 14px}.shell__layers{top:auto;bottom:calc(var(--sheet-height) + 12px);right:10px;transition:bottom .23s}.shell--dock-collapsed .sheet{display:flex}.shell-modal{padding:0;align-items:flex-end}.shell-modal__card{width:100%;max-height:86dvh;border-radius:22px 22px 0 0;padding:16px 16px max(16px,env(safe-area-inset-bottom))}.shell--picking .shell__omni{visibility:visible}}
@media print{.shell{height:auto;overflow:visible}.shell__omni,.shell__footer,.shell__layers,.sheet__handle{display:none}.shell__map{position:relative;height:360px}.sheet{position:relative;inset:auto;width:100%;height:auto;overflow:visible;box-shadow:none}.sheet__content{overflow:visible}.shell--dock-collapsed .sheet{display:block}}
.favorite-place-row{display:flex;gap:6px;align-items:center}.favorite-place-row>.shell-picker__place{flex:1;min-width:0}.favorite-place-row>button:last-child{min-width:36px;min-height:44px;border:0;background:transparent;color:#8795a9}
.sheet__search-row .shell__search span.origin-name{white-space:normal;overflow-wrap:anywhere;font-weight:700}
.sheet__search-row .shell__search>.app-icon{flex-shrink:0}
</style>
<style scoped>
.sheet .shell__omni{position:static;inset:auto;width:auto;flex:none;order:1;padding:0 12px 8px;margin:0;border:0;box-shadow:none;border-radius:0;background:transparent;backdrop-filter:none}
.sheet .sheet__handle{order:0;display:flex;position:relative;justify-content:flex-end;min-height:28px;padding:4px 12px;box-sizing:border-box;border-bottom:0;font-size:10px}
.sheet .sheet__content{order:3}.sheet .sheet__search-row{order:2;margin-top:0}
.sheet .sheet__title{margin-right:auto}
.shell .location-tools{justify-content:flex-end}
.place-picker-modal{padding:18px;max-height:80dvh}.place-picker-modal>header{margin-bottom:14px}.place-picker-modal>header h3{font-size:18px;letter-spacing:.2px}.shell .place-picker-modal>header button{display:grid;place-items:center;min-height:40px;width:40px;padding:0;border:0;border-radius:50%;background:#f3f6fa;color:#6c7b90}.place-picker-modal .shell-picker{gap:0}
.location-search{position:relative}.location-search__icon{position:absolute;left:13px;top:15px;z-index:1;color:#8493a8;pointer-events:none}.location-search :deep(.place-search__form){gap:8px}.location-search :deep(.place-search__form input){height:48px;min-height:48px;padding:10px 12px 10px 39px;border:1px solid #e6ecf3;background:#f4f7fa;border-radius:13px;font-size:15px}.location-search :deep(.place-search__form button){min-height:48px;min-width:56px;border:0;background:#f2f5fa;color:#9aa6b7;border-radius:12px;font-size:13px;padding:8px 12px}.location-search :deep(.place-search__form button:not(:disabled)){background:#2563eb;color:white}.location-search :deep(.place-search__results){max-height:36dvh;margin-top:6px}.location-search :deep(.place-search__result){padding:13px 3px;min-height:62px}.location-search :deep(.place-search__result strong){font-size:15px}.location-search :deep(.place-search__results li>button:last-child:not(.result)){border:0;background:#f3f7fc;color:#4772b1;font-size:12px;min-height:36px;padding:6px 9px}
.location-tools{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:54px;border-bottom:1px solid #edf1f6;margin-top:4px}.location-city{display:flex;align-items:center;gap:5px;color:#8493a8;min-width:0}.location-city input{width:90px;max-width:35vw;min-height:42px;border:0;background:transparent;padding:6px 3px;border-radius:6px;font-size:13px;color:#526781;flex:none}.shell .location-map-pick{display:flex;align-items:center;gap:6px;border:0;padding:8px 0 8px 10px;min-height:44px;background:transparent;color:#336ce1;font-size:13px}.picker-saved{padding-top:16px}.picker-saved>header{display:flex;align-items:center;justify-content:space-between;margin-bottom:5px}.picker-saved>header strong{font-size:13px;color:#5c6f88;font-weight:550}.picker-saved>header small{font-size:11px;color:#9aa7b8}.shell .picker-saved .shell-picker__place{display:flex;align-items:center;gap:10px;border:0;border-bottom:1px solid #f0f3f7;border-radius:0;min-height:58px;padding:10px 2px}.picker-saved .shell-picker__place>.app-icon{color:#8a9bb1}.picker-saved .shell-picker__place>span{display:grid;gap:4px;min-width:0}.picker-saved .shell-picker__place strong{font-size:14px;font-weight:550}.picker-saved .shell-picker__place small{font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.picker-saved__empty{display:flex;align-items:center;justify-content:center;gap:8px;color:#9aa7b8;font-size:12px;margin:4px 0 8px;min-height:32px}.shell-picker:has(.place-search__results) .picker-saved{display:none}
@media(max-width:820px){.place-picker-modal{padding:14px 16px max(18px,env(safe-area-inset-bottom))}.place-picker-modal:before{content:'';display:block;width:32px;height:4px;border-radius:4px;background:#d4dce7;margin:0 auto 12px}}
.shell__nav-item{display:flex;align-items:center;justify-content:center;gap:7px;font-size:14px;padding:10px 8px;transition:color .18s,background .18s,box-shadow .18s}.shell__nav-item .app-icon{opacity:.85}.shell .shell__search{font-size:14px;min-height:46px}.shell .shell__saved{display:flex;align-items:center;gap:5px;font-size:12px;min-height:36px}.shell button{transition:background .16s,border-color .16s,box-shadow .16s}.shell button:active:not(:disabled){filter:brightness(.97)}.sheet__content{scroll-behavior:smooth}.shell-modal__card{animation:sheet-arrive .2s ease-out}.sheet .sheet__search-row{margin-bottom:4px}
@keyframes sheet-arrive{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
@media(prefers-reduced-motion:reduce){.shell button,.shell__nav-item,.shell .sheet,.shell .shell__layers{transition:none}.shell-modal__card{animation:none}.sheet__content{scroll-behavior:auto}}
@media(max-width:820px){.sheet .sheet__grabber{position:absolute;left:50%;top:8px;transform:translateX(-50%);width:32px;height:4px}.sheet .shell__omni{padding:0 12px 8px}.sheet .sheet__toggle{line-height:20px}}
</style>
