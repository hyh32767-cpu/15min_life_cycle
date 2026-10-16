<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import type { CoverageResult, CoverageTimeInput } from '@/providers/contracts'
import type { NamedCoord, PlaceRef } from '@/domain/types'
import IsochronePage from '@/features/isochrone/IsochronePage.vue'
import { useAppStore } from '@/stores/app'
import { useCommuteStore } from '@/stores/commute'
import { useMapInteractionStore } from '@/stores/mapInteraction'
import { useIsochroneStore } from '@/stores/isochrone'
import {
  circleSearchRadius,
  loadUserPrefs,
  saveUserPrefs,
} from '@/domain/lifeCircle'
import { isochroneRings, isochroneContains, isochroneSamples } from '@/domain/isochroneGeometry'
import { serviceIcons } from '@/domain/serviceIcons'
import { lifeServices, serviceGroups, serviceMatch, serviceQueries, SERVICE_MATCH_VERSION } from '@/domain/lifeServices'
import { useCommunityRadiusStore } from '@/stores/communityRadius'
import { measureCoverage } from '@/domain/coverageSampling'
import PlaceSearch from '@/components/PlaceSearch.vue'
import CoverageRadar from './CoverageRadar.vue'
import CommunityInsight from './CommunityInsight.vue'
import { averageServiceCoverage, buildLifeCircleReport, type ServiceAssessment, type FacilitySimulation } from './report'
import { ResultCache } from './resultCache'

const app = useAppStore()
const commute = useCommuteStore()
const iso = useIsochroneStore()
const route = useRoute()
const facilitiesForCoverage = ref<PlaceRef[]>([])
interface CategoryEvidence {
  result: CoverageResult
  times: CoverageTimeInput[]
  facilities: PlaceRef[]
  candidates: PlaceRef[]
}
const categoryEvidence = ref<Record<string, CategoryEvidence>>({})
let recommendationSequence = 0
const recommendationsLoading = ref(false)
let generation = 0
const l2Stage = ref<'idle' | 'l2-preview' | 'upgrading' | 'full'>('idle')

const mapInteraction = useMapInteractionStore()
const thresholdMinutes = computed(() => 15)
const newName = ref('')
const pickedFacilityCoord = ref<NamedCoord | null>(null)
const pickedFacilityAddress = ref('')
function selectFacilityLocation(place: PlaceRef): void {
  pickedFacilityCoord.value = place.coord
  pickedFacilityAddress.value = place.address || place.name
  if (!newName.value.trim()) newName.value = place.name
}
watch(() => mapInteraction.selectedFor, target => {
  if (target === 'community-facility' && mapInteraction.selectedPlace) selectFacilityLocation(mapInteraction.selectedPlace)
})
const result = ref<CoverageResult | null>(null)
const loading = ref(false)
const error = ref('')
const assessmentStarted = computed(() => categoryProfiles.value.some(profile => profile.status !== 'idle'))
type DetailNode = HTMLElement & { open: boolean }
let printDetails: { node: DetailNode; open: boolean }[] = []
function preparePrint(): void {
  printDetails = [...document.querySelectorAll<DetailNode>('.community details')].map(node => ({ node, open: node.open }))
  printDetails.forEach(({ node }) => { node.open = true })
}
function finishPrint(): void {
  printDetails.forEach(({ node, open }) => { node.open = open })
  printDetails = []
}
onMounted(() => { window.addEventListener('beforeprint', preparePrint); window.addEventListener('afterprint', finishPrint) })
onBeforeUnmount(() => { window.removeEventListener('beforeprint', preparePrint); window.removeEventListener('afterprint', finishPrint) })

type CategoryProfile = ServiceAssessment

interface MclpRecommendation {
  k: number
  names: string[]
  coveredCount: number
  gain: number
  status: 'ready' | 'unavailable'
  error?: string
}

const categoryProfiles = ref<CategoryProfile[]>(lifeServices.map(service => ({ ...service,
  status: 'idle', facilityCount: null, coveredCount: null, totalGrids: null, blindCount: null,
})))
const resultCache = new ResultCache<{ profile: CategoryProfile; evidence: CategoryEvidence }>()
function assessmentKey(profile: CategoryProfile): string {
  return JSON.stringify([SERVICE_MATCH_VERSION, iso.origin, 900, circleRing.value,
    iso.result?.algorithmVersion, iso.result?.frontier?.polygons,
    circleSamples.value, profile.id, profile.terms, profile.excludes ?? []])
}
const defaultPriorityIds = lifeServices.filter(service => service.priority).map(service => service.id)
const savedServiceIds = loadUserPrefs().serviceIds?.filter(id => lifeServices.some(s => s.id === id))
const chosenServiceIds = ref(savedServiceIds && savedServiceIds.length ? savedServiceIds : defaultPriorityIds)

function applyServicePreset(mode: 'priority' | 'basic' | 'all'): void {
  if (mode === 'priority') {
    chosenServiceIds.value = [...defaultPriorityIds]
  } else if (mode === 'basic') {
    chosenServiceIds.value = lifeServices.filter(service => service.group === 'basic').map(service => service.id)
  } else {
    chosenServiceIds.value = lifeServices.map(service => service.id)
  }
}

const selectedProfiles = computed(() => categoryProfiles.value.filter(profile => chosenServiceIds.value.includes(profile.id)))
const mclpRecommendations = ref<MclpRecommendation[]>([])
const circleRing = computed(() => iso.origin?.crs === 'BD09' && iso.result?.status === 'complete'
  && iso.result.thresholdSeconds === 900 ? isochroneRings(iso.origin, iso.result).flatMap(p => p.outer) : [])
const circleSamples = computed(() => iso.origin && iso.result?.status === 'complete' ? isochroneSamples(iso.origin, iso.result) : [])

const sampledGrids = computed(() => gridIds())
const candidateFacilities = computed(() => facilitiesForCoverage.value)
const activeCategoryLabel = computed(() => categoryProfiles.value.find(profile => profile.id === selectedCategory.value)?.label ?? '')
const activeEvidence = computed(() => categoryEvidence.value[selectedCategory.value])
const coverageRate = computed(() => {
  const r = result.value
  if (!r || r.totalGrids <= 0) return null
  return Math.round((r.coveredCount / r.totalGrids) * 100)
})

const scorecardItems = computed(() => [
  { label: `${activeCategoryLabel.value}覆盖`, value: coverageRate.value == null ? '—' : `${coverageRate.value}%`, tone: 'scorecard__value--blue' },
  { label: '参评设施', value: assessmentStarted.value ? `${new Set(candidateFacilities.value.map(place => place.uid ?? place.name)).size} 家` : '—', tone: 'scorecard__value--green' },
  { label: '采样点', value: result.value ? `${result.value.totalGrids} 点` : '—', tone: 'scorecard__value--purple' },
  { label: '未覆盖采样点', value: result.value ? `${result.value.blindGrids.length} 点` : '—', tone: result.value?.blindGrids.length ? 'scorecard__value--orange' : 'scorecard__value--muted' },
  { label: '步行时间', value: `${thresholdMinutes.value} 分`, tone: 'scorecard__value--muted' },
])

const averageCoverage = computed(() => averageServiceCoverage(selectedProfiles.value))
const simulationSnapshot = ref<FacilitySimulation | null>(null)

const prescriptionText = computed(() => {
  if (!result.value) return '先查看设施覆盖，再试算新增设施的效果。'
  if (result.value.delta) {
    const gain = result.value.delta.after - result.value.delta.before
    return gain > 0
      ? `这个模拟设施可新增覆盖 ${gain} 个采样点。`
      : '这里暂未增加覆盖，可以换个位置再试。'
  }
  if (result.value.blindGrids.length) {
    return `当前仍有 ${result.value.blindGrids.length} 个未覆盖采样点，可以试试在这些点附近新增设施。`
  }
  return '本次采样点已全部覆盖。'
})

function gridIds(): string[] {
  return circleSamples.value.map(cell => cell.id)
}

function routeGridCoords(): NamedCoord[] {
  return circleSamples.value.map(cell => cell.coord)
}

function resetAssessment(): void {
  mapInteraction.showBlindSpots = false
  generation++
  l2Stage.value = 'idle'
  simulationSnapshot.value = null
  radius.clear()
  pickedFacilityCoord.value = null
  mapInteraction.clearSelected('community-facility')
  result.value = null
  loading.value = false
  error.value = ''
  facilitiesForCoverage.value = []
  categoryEvidence.value = {}
  recommendationSequence++
  recommendationsLoading.value = false
  profilePlaceIds.value = {}
  selectedCategory.value = ''
  mclpRecommendations.value = []
  commute.setCommunityGridPoints([])
  categoryProfiles.value = categoryProfiles.value.map(profile => ({ ...profile, status: 'idle', facilityCount: null,
    coveredCount: null, totalGrids: null, blindCount: null, error: undefined, retrievalLimited: false, reused: false }))
}
watch(() => `${iso.origin?.lng},${iso.origin?.lat},${iso.origin?.crs},${thresholdMinutes.value}`, resetAssessment, { flush: 'sync' })
watch(() => iso.result, () => { if (!loading.value && assessmentStarted.value) resetAssessment() })
watch(chosenServiceIds, (ids) => {
  saveUserPrefs({ serviceIds: ids })
  resetAssessment()
}, { flush: 'sync' })

let circleWorkflow = 0
async function generateCircle(): Promise<void> {
  if (iso.busy || !iso.origin) return
  const current = ++circleWorkflow
  await iso.generateLifeCircle()
  if (current !== circleWorkflow || route.name !== 'community' || iso.result?.status !== 'complete' || iso.result.thresholdSeconds !== 900) return
  if (chosenServiceIds.value.length && !loading.value) await run(true)
}

async function evaluateCategory(profile: CategoryProfile, grids: string[], gridCoords: NamedCoord[]): Promise<void> {
  const current = generation
  const key = assessmentKey(profile)
  const cached = resultCache.get(key)
  if (cached) {
    Object.assign(profile, cached.profile, { reused: true })
    categoryEvidence.value[profile.id] = cached.evidence
    facilitiesForCoverage.value.push(...cached.evidence.facilities)
    return
  }
  profile.status = 'loading'
  profile.reused = false
  profile.error = undefined
  profile.retrievalLimited = false
  try {
    const corridor = await app.provider.getCorridorPois({
      routeGeometry: [iso.origin!, iso.origin!],
      queryTerms: serviceQueries(profile),
      category: profile.label,
      corridorBufferM: circleSearchRadius(iso.origin!, circleRing.value),
      windowRadiusM: circleSearchRadius(iso.origin!, circleRing.value),
      maxPagesPerWindow: 1,
      maxUnique: 100,
      detailLimit: 0,
    })
    if (current !== generation) return
    const expirations = [corridor.expiresAt]
    profile.reused = corridor.cacheHit === true
    profile.retrievalLimited = corridor.retrieval.truncated
    const insidePois = corridor.pois.filter(item => iso.origin && iso.result && isochroneContains(iso.origin, iso.result, item.place.naviCoord ?? item.place.coord))
    const uncertain = insidePois.some(item => serviceMatch(profile, item.place) === 'uncertain')
    profile.retrievalLimited ||= uncertain
    const circlePois = insidePois.filter(item => serviceMatch(profile, item.place) === 'matched')
    const facilities = circlePois.slice(0, 5)
    if (!facilities.length) {
      if (corridor.retrieval.truncated || uncertain) throw new Error('未取得可用候选，设施覆盖仍待查明')
      profile.status = 'ready'
      profile.facilityCount = 0
      profile.coveredCount = 0
      profile.totalGrids = grids.length
      profile.blindCount = grids.length
      categoryEvidence.value[profile.id] = {
        result: { coverage: Object.fromEntries(grids.map(id => [id, false])), coveredCount: 0, totalGrids: grids.length, blindGrids: [...grids] },
        times: [], facilities: [], candidates: [],
      }
      resultCache.put(key, { profile, evidence: categoryEvidence.value[profile.id]! }, expirations)
      return
    }
    profile.facilityCount = facilities.length
    profile.coveredCount = null
    profile.totalGrids = grids.length
    profile.blindCount = null
    l2Stage.value = 'upgrading'

    const times = await measureCoverage(grids.map((id, index) => ({ id, coord: gridCoords[index]! })),
      facilities.map(item => ({ id: item.place.uid ?? item.place.name, coord: item.place.naviCoord ?? item.place.coord })),
      thresholdMinutes.value * 60, async (origins, destinations) => {
        const matrix = await app.provider.getTravelMatrix(origins, destinations)
        expirations.push(matrix.expiresAt)
        profile.reused &&= matrix.cacheHit
        return matrix
      },
      () => current === generation)
    if (current !== generation) return
    const checked = await app.provider.checkCoverage({
      thresholdSeconds: thresholdMinutes.value * 60,
      gridIds: grids,
      facilityIds: facilities.map((item) => item.place.uid ?? item.place.name),
      times,
    })
    if (current !== generation) return
    profilePlaceIds.value[profile.id] = facilities.map(item => item.place.uid ?? item.place.name)
    facilitiesForCoverage.value.push(...facilities.map(item => item.place))
    profile.status = 'ready'
    profile.facilityCount = facilities.length
    profile.coveredCount = checked.coveredCount
    profile.totalGrids = checked.totalGrids
    profile.blindCount = checked.blindGrids.length
    categoryEvidence.value[profile.id] = { result: checked, times, facilities: facilities.map(item => item.place), candidates: circlePois.slice(5).map(item => item.place) }
    resultCache.put(key, { profile, evidence: categoryEvidence.value[profile.id]! }, expirations)
  } catch (err) {
    if (current !== generation) return
    profile.status = 'error'
    profile.reused = false
    profile.error = err instanceof Error ? err.message : String(err)
    profile.facilityCount = null
    profile.coveredCount = null
    profile.totalGrids = null
    profile.blindCount = null
  }
}

async function runCategoryAssessment(grids: string[], gridCoords: NamedCoord[]): Promise<void> {
  const current = generation
  for (const profile of selectedProfiles.value) {
    if (current !== generation) return
    await evaluateCategory(profile, grids, gridCoords)
  }
}

async function runMclp(grids: string[], gridCoords: NamedCoord[], baseTimes: CoverageTimeInput[]): Promise<void> {
  const current = generation
  const seq = ++recommendationSequence
  const scope = selectedCategory.value
  const evidence = categoryEvidence.value[scope]
  if (!evidence) return
  const existingIds = new Set(evidence.facilities.map(item => item.uid ?? item.name))
  const candidates = evidence.candidates.filter(candidate => !existingIds.has(candidate.uid ?? candidate.name)).slice(0, 8)
  mclpRecommendations.value = []
  recommendationsLoading.value = true
  try {
    const threshold = thresholdMinutes.value * 60
    const baseCovered = new Set(
      grids.filter((grid) => baseTimes.some((cell) => cell.fromGrid === grid && cell.status === 'ok' && cell.durationSeconds != null && cell.durationSeconds <= threshold)),
    )
    if (baseCovered.size === grids.length) {
      mclpRecommendations.value = [1, 2, 3].map(k => ({ k, names: [], coveredCount: grids.length, gain: 0, status: 'ready' }))
      return
    }
    if (!candidates.length) {
      mclpRecommendations.value = [{ k: 1, names: [], coveredCount: baseCovered.size, gain: 0, status: 'unavailable',
        error: `${activeCategoryLabel.value}仍有 ${grids.length - baseCovered.size} 个采样点未覆盖。本次没有可评估的候选位置，可在下方地图选点试算。` }]
      return
    }
    const missingIndices = grids.map((_grid, index) => index).filter(index => !baseCovered.has(grids[index]!))
    const matrix = await app.provider.getTravelMatrix(
      missingIndices.map(index => gridCoords[index]!),
      candidates.map((candidate) => candidate.naviCoord ?? candidate.coord),
    )
    if (current !== generation || seq !== recommendationSequence || scope !== selectedCategory.value) return
    if (matrix.cells.length !== missingIndices.length * candidates.length || matrix.cells.some(cell =>
      cell.status !== 'no_route' && (cell.status !== 'ok' || cell.durationSeconds == null))) {
      throw new Error('候选设施部分路线未查明，暂不推荐新增点')
    }
    const candidateSets = candidates.map((candidate, candidateIndex) => ({
      name: candidate.name,
      covered: new Set(
        missingIndices.filter((_grid, gridIndex) => {
          const cell = matrix.cells.find((item) => item.fromIndex === gridIndex && item.toIndex === candidateIndex)
          return cell?.status === 'ok' && cell.durationSeconds != null && cell.durationSeconds <= threshold
        }).map(index => grids[index]!),
      ),
    }))
    const recommendations: MclpRecommendation[] = []
    for (const k of [1, 2, 3]) {
      const selected: typeof candidateSets = []
      const covered = new Set(baseCovered)
      while (selected.length < k) {
        const available = candidateSets.filter((candidate) => !selected.includes(candidate))
        const next = [...available].sort((left, right) => {
          const gainLeft = [...left.covered].filter((grid) => !covered.has(grid)).length
          const gainRight = [...right.covered].filter((grid) => !covered.has(grid)).length
          return gainRight - gainLeft || left.name.localeCompare(right.name, 'zh-CN')
        })[0]
        if (!next || ![...next.covered].some(grid => !covered.has(grid))) break
        selected.push(next)
        next.covered.forEach((grid) => covered.add(grid))
      }
      recommendations.push({
        k,
        names: selected.map((candidate) => candidate.name),
        coveredCount: covered.size,
        gain: covered.size - baseCovered.size,
        status: 'ready',
      })
    }
    mclpRecommendations.value = recommendations
  } catch (err) {
    if (current !== generation || seq !== recommendationSequence || scope !== selectedCategory.value) return
    mclpRecommendations.value = [{
      k: 1,
      names: [],
      coveredCount: 0,
      gain: 0,
      status: 'unavailable',
      error: err instanceof Error ? err.message : String(err),
    }]
  } finally {
    if (seq === recommendationSequence) recommendationsLoading.value = false
  }
}

async function run(before: boolean): Promise<void> {
  error.value = ''
  if (!iso.origin || iso.origin.crs !== 'BD09') {
    error.value = '请先在上方选择社区中心'
    return
  }
  if (!selectedProfiles.value.length) { error.value = '请至少选择一项服务'; return }
  const current = ++generation
  if (!Number.isFinite(thresholdMinutes.value) || thresholdMinutes.value < 1) {
    error.value = '步行时间请填写大于 0 的分钟数'
    return
  }
  let grids = gridIds()
  let gridCoords = routeGridCoords()
  loading.value = true
  try {
    if (before) {
      l2Stage.value = 'l2-preview'
      simulationSnapshot.value = null
      result.value = null
      facilitiesForCoverage.value = []
      categoryEvidence.value = {}
      selectedCategory.value = ''
      mclpRecommendations.value = []
      recommendationSequence++
      radius.clear()
      commute.setCommunityGridPoints([])
      categoryProfiles.value = categoryProfiles.value.map(profile => ({ ...profile, status: 'idle', facilityCount: null,
        coveredCount: null, totalGrids: null, blindCount: null, error: undefined, retrievalLimited: false, reused: false }))
      if (current !== generation) return
      if (!circleRing.value.length) { error.value = iso.error || '15分钟生活圈尚未生成完成，请稍后重试'; return }
      grids = gridIds()
      gridCoords = routeGridCoords()
      if (!grids.length) { error.value = '当前等时圈暂无可检查的点，请更换地点或步行时间'; return }
      await runCategoryAssessment(grids, gridCoords)
      if (current !== generation) return
      l2Stage.value = 'full'
      const worst = selectedProfiles.value.filter(profile => profile.status === 'ready')
        .sort((a, b) => (a.coveredCount! / a.totalGrids!) - (b.coveredCount! / b.totalGrids!))[0]
      if (!worst) { error.value = '设施覆盖暂未查明，请稍后重试'; return }
      applyCategory(worst)
      mclpRecommendations.value = []
      if (current !== generation) return
      if (selectedProfiles.value.some(profile => profile.status !== 'ready')) error.value = '部分设施未查明，已完成项仍可查看'
      return
    }
    const evidence = activeEvidence.value
    if (!evidence) { error.value = '请先选择已完成的设施类别'; return }
    const facilities = [...new Set(evidence.facilities.map(place => place.uid ?? place.name))]
    const times = evidence.times
    if (!before && (!result.value || !newName.value.trim() || !pickedFacilityCoord.value)) {
      error.value = '请先计算覆盖，再填写设施名称并在地图选择新增点'
      return
    }
    const newFacility = !before && pickedFacilityCoord.value ? { name: newName.value.trim(), coord: { ...pickedFacilityCoord.value } } : null
    const newTimes: CoverageTimeInput[] = []
    if (!before) {
      const missingIndices = grids.map((_grid, index) => index).filter(index => !evidence.result.coverage[grids[index]!])
      const matrix = missingIndices.length ? await app.provider.getTravelMatrix(missingIndices.map(index => gridCoords[index]!), [newFacility!.coord]) : null
      if (current !== generation) return
      newTimes.push(...missingIndices.map((gridIndex, index) => {
        const cell = matrix?.cells.find(item => item.fromIndex === index && item.toIndex === 0)
        return { fromGrid: grids[gridIndex]!, toFacility: newFacility!.name, durationSeconds: cell?.durationSeconds ?? null, status: cell?.status ?? 'error' }
      }))
      if (newTimes.some(cell => cell.status !== 'no_route' && (cell.status !== 'ok' || cell.durationSeconds == null))) throw new Error('新增设施部分路线未查明，请稍后重试')
    }
    const checked = await app.provider.checkCoverage({
      thresholdSeconds: thresholdMinutes.value * 60, gridIds: grids, facilityIds: facilities, times,
      ...(!before ? { newFacilityId: newFacility!.name, newFacilityTimes: newTimes } : {}),
    })
    if (current !== generation) return
    result.value = checked
    if (newFacility) simulationSnapshot.value = { serviceId: selectedCategory.value, ...newFacility, result: checked, times: newTimes }
    commute.setCommunityGridPoints(gridCoords.map((coord, index) => ({ id: grids[index], coord, covered: checked.coverage[grids[index]] ?? false })))
  } catch (err) {
    if (current === generation) error.value = err instanceof Error ? err.message : String(err)
  } finally {
    if (current === generation) loading.value = false
  }
}

function applyCategory(profile: CategoryProfile): void {
  mapInteraction.showBlindSpots = false
  simulationSnapshot.value = null
  selectedCategory.value = profile.id
  result.value = categoryEvidence.value[profile.id]?.result ?? null
  const grids = gridIds()
  commute.setCommunityGridPoints(routeGridCoords().map((coord, index) => ({ id: grids[index], coord, covered: result.value?.coverage[grids[index]] ?? false })))
  radius.setFacilities(profile.id, profile.label, categoryEvidence.value[profile.id]?.facilities ?? [])
}
function focusCategory(profile: CategoryProfile): void {
  if (profile.status !== 'ready' || !categoryEvidence.value[profile.id]) return
  applyCategory(profile)
  recommendationSequence++
  recommendationsLoading.value = false
  mclpRecommendations.value = []
}
const selectedCategory = ref('')
const profilePlaceIds = ref<Record<string, string[]>>({})
const radius = useCommunityRadiusStore()
function printReport(): void { window.print() }
function exportLifeCircleReport(): void {
  const report = buildLifeCircleReport({ origin: iso.origin, originLabel: iso.originLabel,
    thresholdSeconds: 900, circle: iso.result?.thresholdSeconds === 900 ? iso.result : null, heatLayers: iso.heatLayers.filter(layer => [300, 600, 900].includes(layer.thresholdSeconds)),
    samples: circleSamples.value, profiles: selectedProfiles.value, evidence: categoryEvidence.value,
    activeServiceId: selectedCategory.value, recommendations: mclpRecommendations.value,
    recommendationsLoading: recommendationsLoading.value, simulation: simulationSnapshot.value })
  const url = URL.createObjectURL(new window.Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = '生活圈报告-15分钟.json'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
watch([() => route.name, () => iso.origin ? `${iso.origin.crs}:${iso.origin.lng}:${iso.origin.lat}` : ''], ([name, key]) => {
  if (name !== 'community' || !key || iso.busy) return
  if (iso.result?.status === 'complete' && iso.result.thresholdSeconds === 900
    && [300, 600, 900].every(seconds => iso.heatLayers.some(layer => layer.status === 'complete' && layer.thresholdSeconds === seconds))) return
  void generateCircle()
}, { immediate: true, flush: 'post' })
</script>

<template>
  <section class="community">
    <details
      v-if="activeEvidence?.facilities.length"
      class="facility-list"
    >
      <summary>{{ activeCategoryLabel }}设施列表 · {{ activeEvidence.facilities.length }}家</summary>
      <button
        v-for="place in activeEvidence.facilities"
        :key="radius.placeKey(place)"
        type="button"
        @click="radius.selectFacility(radius.placeKey(place))"
      >
        <span aria-hidden="true">📍</span><span><strong>{{ place.name }}</strong><small>{{ place.address || '点击查看地图位置' }}</small></span><em>查看 ›</em>
      </button>
    </details>

    <section
      class="community__iso"
      aria-label="社区等时圈体检"
    >
      <div class="community__section-head">
        <span class="pref-badge">步行生活圈</span>
      </div>
      <IsochronePage
        :show-report-export="false"
      />

      <div
        class="life-range-key"
        aria-label="步行时间分层"
      >
        <strong>15分钟生活圈</strong><span class="range-5">5分钟</span><span class="range-10">10分钟</span><span class="range-15">15分钟</span>
      </div>
      <p
        v-if="!iso.origin"
        class="empty"
      >
        选择地点，自动查看步行范围
      </p>
      <button
        v-if="iso.error && !iso.busy"
        type="button"
        @click="generateCircle"
      >
        重新生成生活圈
      </button>
      <button
        v-if="iso.heatError && !iso.error && !iso.busy"
        type="button"
        @click="iso.loadHeatLayers()"
      >
        重试加载范围
      </button>

      <div class="community__actions">
        <button
          type="button"
          :disabled="loading || iso.busy || !circleRing.length || !chosenServiceIds.length"
          aria-label="设施社区评分"
          @click="run(true)"
        >
          {{ loading ? '分析中…' : assessmentStarted ? '重新评分' : '设施社区评分' }}
        </button>
        <span>{{ thresholdMinutes }} 分钟步行范围内的设施覆盖</span>
      </div>
      <p
        v-if="error && error !== iso.error"
        class="error"
        role="alert"
      >
        {{ error }}
      </p>
    </section>

    <section
      v-if="assessmentStarted"
      class="scorecard"
      aria-label="社区覆盖摘要"
    >
      <div class="scorecard__ring">
        <strong>{{ averageCoverage == null ? '—' : averageCoverage }}</strong><small>设施社区评分</small>
      </div>
      <div class="scorecard__place">
        <h2>{{ iso.originLabel || '当前地点' }}</h2><p>{{ selectedProfiles.length }}类关注服务 · {{ selectedProfiles.filter(item => item.status === 'ready').length }}类已完成</p><small>{{ averageCoverage == null ? '部分结果待查明' : '满分100 · 按所选服务平均覆盖率计算' }}</small><small v-if="selectedProfiles.some(profile => profile.reused)"> · 已复用 {{ selectedProfiles.filter(profile => profile.reused).length }} 项结果</small>
      </div>
    </section>

    <CommunityInsight
      v-if="assessmentStarted"
      :key="`${iso.origin?.lng},${iso.origin?.lat}`"
      :profiles="selectedProfiles"
      :busy="loading || iso.busy"
    />

    <details class="service-picker">
      <summary>选择服务 · 已选 {{ chosenServiceIds.length }} 项</summary>
      <div class="service-presets">
        <button
          type="button"
          class="preset-chip"
          :disabled="loading"
          @click="applyServicePreset('priority')"
        >
          默认民生7项
        </button>
        <button
          type="button"
          class="preset-chip"
          :disabled="loading"
          @click="applyServicePreset('basic')"
        >
          基本保障
        </button>
        <button
          type="button"
          class="preset-chip"
          :disabled="loading"
          @click="applyServicePreset('all')"
        >
          全部29项
        </button>
      </div>
      <p class="category-card__hint">
        先查常用服务，也可按需增减；修改后将自动为您保留偏好。
      </p>
      <fieldset
        v-for="group in serviceGroups"
        :key="group.id"
        :disabled="loading"
      >
        <legend>{{ group.label }}</legend>
        <div class="service-picker__options">
          <label
            v-for="service in categoryProfiles.filter(item => item.group === group.id)"
            :key="service.id"
            :title="service.note"
          >
            <input
              v-model="chosenServiceIds"
              type="checkbox"
              :value="service.id"
            >
            <span aria-hidden="true">{{ serviceIcons[service.id] }}</span>{{ service.label }}
          </label>
        </div>
      </fieldset>
    </details>
    <section
      v-if="assessmentStarted"
      class="category-card"
      aria-label="所选服务覆盖"
    >
      <div class="card-head">
        <div>
          <h3>设施社区评分 · 服务覆盖</h3>
          <p class="category-card__hint">
            <template v-if="loading && l2Stage !== 'full'">
              正在逐类核对步行路线…
            </template>
          </p>
        </div>
        <span class="tag">{{ selectedProfiles.filter((item) => item.status === 'ready').length }}/{{ selectedProfiles.length }} 已完成</span>
      </div>
      <button
        v-if="result?.blindGrids.length"
        type="button"
        class="blind-toggle"
        :aria-pressed="mapInteraction.showBlindSpots"
        @click="mapInteraction.showBlindSpots = !mapInteraction.showBlindSpots"
      >
        {{ mapInteraction.showBlindSpots ? '隐藏未覆盖位置' : '查看未覆盖位置' }}
      </button>
      <div class="category-grid">
        <article
          v-for="profile in selectedProfiles"
          :key="profile.id"
          class="category-item"
          :class="`category-item--${profile.status}`"
          :data-selected="selectedCategory === profile.id"
        >
          <div class="category-item__head">
            <strong><span
              class="category-item__icon"
              aria-hidden="true"
            >{{ serviceIcons[profile.id] }}</span>{{ profile.label }}</strong>
            <b
              v-if="profile.status === 'ready' && profile.totalGrids"
              class="category-item__percent"
              :class="{ 'is-low': (profile.coveredCount ?? 0) / profile.totalGrids < .7 }"
            >{{ Math.round((profile.coveredCount! / profile.totalGrids) * 100) }}%</b>
          </div>
          <p v-if="profile.status === 'loading'">
            <template v-if="profile.totalGrids && profile.coveredCount != null">
              预估 {{ Math.round((profile.coveredCount / profile.totalGrids) * 100) }}% · 路线核对中…
            </template>
            <template v-else>
              计算中…
            </template>
          </p>
          <p v-else-if="profile.status === 'error'">
            待查明
          </p>
          <p v-else-if="profile.status === 'ready' && profile.totalGrids">
            圈内 {{ profile.facilityCount }} 家
          </p>
          <p v-else>
            尚未计算
          </p>
          <button
            type="button"
            class="coverage-chart"
            :disabled="profile.status !== 'ready'"
            :aria-pressed="selectedCategory === profile.id"
            :aria-label="`查看${profile.label}覆盖`"
            @click="focusCategory(profile)"
          >
            <span class="coverage-chart__track"><span
              class="coverage-chart__fill"
              :style="{ width: `${profile.totalGrids ? (profile.coveredCount ?? 0) / profile.totalGrids * 100 : 0}%`, background: profile.totalGrids && (profile.coveredCount ?? 0) / profile.totalGrids < .7 ? '#f59e0b' : undefined }"
            /></span>
            <span>{{ profile.status === 'ready' ? `${profile.coveredCount}/${profile.totalGrids} 点` : profile.status === 'error' ? '待查明' : '—' }}</span>
          </button>
          <small v-if="profile.status === 'ready' && profile.blindCount != null">
            未覆盖 {{ profile.blindCount }} 点
          </small>
        </article>
      </div>
    </section>

    <section
      v-if="result || loading"
      class="mclp-card"
      aria-label="新增设施覆盖处方"
    >
      <div class="card-head">
        <div>
          <h3>{{ activeCategoryLabel }}设施改善建议</h3>
          <p class="category-card__hint">
            只评估当前类别；候选位置试算不代表建设方案。
          </p>
        </div>
        <button
          type="button"
          :disabled="loading || recommendationsLoading || !activeEvidence"
          @click="runMclp(gridIds(), routeGridCoords(), activeEvidence!.times)"
        >
          查看建议
        </button>
      </div>
      <p
        v-if="recommendationsLoading"
        role="status"
      >
        正在评估{{ activeCategoryLabel }}候选位置…
      </p>
      <div
        v-if="mclpRecommendations.length"
        class="mclp-list"
      >
        <article
          v-for="recommendation in mclpRecommendations"
          :key="recommendation.k"
          class="mclp-row"
        >
          <strong>{{ recommendation.k }} 点</strong>
          <template v-if="recommendation.status === 'ready'">
            <span>{{ recommendation.names.join('、') || (result?.blindGrids.length ? '本次候选位置未增加覆盖' : '本次采样点已全部覆盖') }}</span>
            <em>覆盖 {{ recommendation.coveredCount }} 点（+{{ recommendation.gain }}）</em>
          </template>
          <span
            v-else
            class="mclp-error"
          >
            {{ recommendation.error }}
          </span>
        </article>
      </div>
      <p
        v-else
        class="empty"
      >
        点击“查看建议”，比较当前类别的候选位置。
      </p>
    </section>

    <details
      v-if="assessmentStarted"
      class="community-charts"
    >
      <summary>覆盖图表与测量详情</summary>
      <CoverageRadar
        v-if="selectedProfiles.length >= 3 && selectedProfiles.length <= 8"
        :items="selectedProfiles"
      />
      <div class="scorecard__grid">
        <div
          v-for="item in scorecardItems"
          :key="item.label"
        >
          <small>{{ item.label }}</small><strong>{{ item.value }}</strong>
        </div>
      </div>
    </details>
    <details
      v-if="result"
      class="coverage-details"
    >
      <summary>覆盖数据详情</summary>
      <div
        v-if="result"
        class="card"
      >
        <div class="card-head">
          <h3>{{ activeCategoryLabel }}覆盖详情</h3>
          <span class="tag">步行可达</span>
        </div>
        <p class="note">
          在当前 {{ thresholdMinutes }} 分钟等时圈内布置 {{ sampledGrids.length }} 个采样点，按实际步行用时检查设施。只标记已测点，每类最多 5 家，不推断整片区域。
        </p>
        <div
          v-if="result"
          class="summary"
        >
          <p class="big">
            覆盖 {{ result.coveredCount }}/{{ result.totalGrids }}<span v-if="coverageRate !== null"> · {{ coverageRate }}%</span>
          </p>
          <p class="sub">
            {{ sampledGrids.length }} 个采样点 · {{ activeEvidence?.facilities.length ?? 0 }} 家{{ activeCategoryLabel }}设施 · 步行 {{ thresholdMinutes }} 分钟
          </p>
          <p class="sub">
            未覆盖采样点 {{ result.blindGrids.map(grid => sampledGrids.indexOf(grid) + 1).join('、') || '无' }}
          </p>
        </div>
        <p
          v-else-if="!loading && !error"
          class="empty"
        >
          先选择地点和服务，再点「分析设施覆盖」。
        </p>
      </div>
    </details>

    <details
      v-if="result"
      class="card card--sim community__extra"
    >
      <summary>模拟新增设施</summary>
      <div class="card-head">
        <h3>新增{{ activeCategoryLabel }}设施试算</h3>
        <span class="tag">改善前后对比</span>
      </div>
      <div class="controls">
        <PlaceSearch
          :city="commute.city"
          label="搜索新增设施位置"
          @select="selectFacilityLocation"
        />
        <input
          v-model="newName"
          type="text"
          placeholder="模拟设施名称"
        >
        <button
          type="button"
          @click="mapInteraction.beginPick('community-facility')"
        >
          地图选点
        </button>
        <span
          v-if="pickedFacilityCoord"
          class="picked-coord"
        >
          已选：{{ pickedFacilityAddress || '地图位置' }}
        </span>
        <span
          v-else
          class="picked-coord"
        >选择新增设施的位置</span>
        <button
          type="button"
          :disabled="loading || !newName.trim() || !pickedFacilityCoord"
          @click="run(false)"
        >
          新增并对比
        </button>
      </div>
      <p
        v-if="result && result.delta"
        class="delta"
      >
        新增前后：{{ result.delta.before }} → {{ result.delta.after }}
      </p>
      <p class="prescription">
        {{ prescriptionText }}
      </p>
      <p class="note">
        模拟设施不代表实际存在。
      </p>
    </details>
    <details class="community-tools">
      <summary>报告与更多</summary>
      <header class="page-head">
        <RouterLink
          v-if="route.query.from === 'route-band'"
          to="/"
        >
          返回沿途
        </RouterLink>
        <div>
          <h2>生活圈</h2>
        </div>
        <button
          type="button"
          @click="printReport"
        >
          打印报告
        </button>
        <button
          v-if="iso.result"
          type="button"
          :disabled="loading"
          @click="exportLifeCircleReport"
        >
          导出报告
        </button>
        <RouterLink to="/cases">
          历史案例
        </RouterLink>
      </header>
    </details>
  </section>
</template>

<style scoped>
.community__actions { display:flex;align-items:center;gap:10px;flex-wrap:wrap; }
.community__actions button { background:#2563eb;color:#fff;min-height:44px;border:0;border-radius:12px;padding:10px 18px; }
.community__actions button:disabled { opacity:.45; }
.community__actions span { font-size:12px;color:#64748b; }
.community__extra { border:1px solid #e2e8f0;border-radius:12px;padding:10px;background:#f8faff; }
.community__extra summary { min-height:44px;align-content:center;cursor:pointer;font-size:13px;font-weight:600;color:#334155; }
.coverage-chart { width: 100%; min-height: 44px; display: flex; align-items: center; gap: 8px; background: transparent; border: 0; padding: 4px 0; color: #64748b; font-size: 12px; }
.coverage-chart__track { flex: 1; height: 12px; background: #eef2ff; border-radius: 6px; overflow: hidden; }
.coverage-chart__fill { display: block; height: 100%; background: linear-gradient(90deg, #3b82f6, #8b5cf6); border-radius: 6px; }

.community { display: grid; gap: 0.65rem; }
.community > .page-head button, .community > .page-head a { font-size: 12px; min-height: 44px; display: inline-flex; align-items: center; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.page-head h2 { margin: 0.25rem 0 0; font-size: 1.25rem; color: var(--color-text); }
.kicker { font-size: 0.7rem; letter-spacing: 0.05em; color: var(--color-muted); }
.community__iso { display: grid; gap: 0.55rem; padding: 0.7rem; border: 1px solid #bfdbfe; border-radius: 0.9rem; background: linear-gradient(135deg, #eff6ff, #ffffff 72%); }
.community__section-head { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; }
.community__section-head h3 { margin: 0.2rem 0 0; font-size: 1rem; color: #0f172a; }
.pref-badge { font-size: 0.68rem; color: #1d4ed8; background: #dbeafe; border-radius: 999px; padding: 0.15rem 0.55rem; font-weight: 600; }
.community__iso :deep(.isochrone-page) { gap: 0.55rem; }
.community__iso :deep(.isochrone-page > .page-head) { display: none; }
.service-presets { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.45rem 0 0.2rem; }
.preset-chip { font-size: 0.72rem; padding: 0.25rem 0.65rem; border-radius: 999px; border: 1px solid #cbd5e1; background: #fff; color: #334155; cursor: pointer; }
.preset-chip:hover { border-color: #2563eb; color: #2563eb; }
.scorecard { display: grid; grid-template-columns: minmax(8rem, 0.8fr) minmax(0, 1.7fr); gap: 0.6rem; border: 1px solid #dbeafe; border-radius: 0.9rem; padding: 0.75rem; background: linear-gradient(135deg, #eff6ff, #ffffff 72%); }
.scorecard__hero { display: grid; align-content: center; gap: 0.15rem; padding: 0.25rem 0.35rem; }
.scorecard__eyebrow { color: #2563eb; font-size: 0.68rem; font-weight: 700; }
.scorecard__hero strong { color: #0f172a; font-size: 2rem; line-height: 1; }
.scorecard__hero small { font-size: 0.75rem; color: #64748b; }
.scorecard__hero > span:last-child { color: #64748b; font-size: 0.63rem; line-height: 1.35; }
.scorecard__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.4rem; }
.scorecard__item { display: grid; gap: 0.15rem; padding: 0.45rem 0.5rem; border: 1px solid rgb(226 232 240 / 80%); border-radius: 0.6rem; background: rgb(255 255 255 / 80%); }
.scorecard__item > span { color: #64748b; font-size: 0.62rem; }
.scorecard__item > strong { font-size: 0.82rem; }
.scorecard__value--blue { color: #2563eb; }
.scorecard__value--green { color: #059669; }
.scorecard__value--purple { color: #7c3aed; }
.scorecard__value--orange { color: #d97706; }
.scorecard__value--muted { color: #475569; }
.category-card { border: 1px solid #e2e8f0; border-radius: 0.9rem; padding: 0.85rem; background: #fff; display: grid; gap: 0.55rem; }
.category-card__hint { margin: 0.15rem 0 0; color: #64748b; font-size: 0.65rem; line-height: 1.35; }
.service-picker { margin-top: 0.5rem; }
.service-picker summary { color: #475569; cursor: pointer; font-size: 0.85rem; }
.service-picker fieldset { margin: 0.5rem 0; border: 0; padding: 0; }
.service-picker legend { font-size: 0.8rem; font-weight: 600; color: #334155; }
.service-picker__options { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.4rem; margin-top: 0.4rem; }
.service-picker__options label { display: flex; align-items: center; gap: 0.3rem; font-size: 0.75rem; min-height: 32px; }
.category-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.35rem; }
.category-item { min-width: 0; display: grid; gap: 0.2rem; padding: 0.45rem; border: 1px solid #e2e8f0; border-radius: 0.55rem; background: #f8fafc; }
.category-item[data-selected=true] { outline: 2px solid #6366f1; outline-offset: 1px; }
.category-item__head { display: flex; justify-content: space-between; gap: 0.15rem; align-items: center; }
.category-item__head strong { font-size: 0.7rem; }
.category-item__head span { color: #94a3b8; font-size: 0.58rem; }
.category-item p { margin: 0; min-height: 1.7rem; color: #475569; font-size: 0.62rem; line-height: 1.35; }
.category-item small { color: #64748b; font-size: 0.58rem; }
.category-item--loading { border-color: #bfdbfe; background: #eff6ff; }
.category-item--ready { border-color: #a7f3d0; background: #ecfdf5; }
.category-item--error { border-color: #fecaca; background: #fef2f2; }
.category-card__error { margin: 0; color: #b91c1c; font-size: 0.68rem; line-height: 1.4; }
.mclp-card { border: 1px solid #ddd6fe; border-radius: 0.9rem; padding: 0.85rem; background: linear-gradient(135deg, #faf5ff, #ffffff 74%); display: grid; gap: 0.55rem; }
.mclp-list { display: grid; gap: 0.35rem; }
.mclp-row { display: grid; grid-template-columns: 2rem minmax(0, 1fr) auto; gap: 0.45rem; align-items: center; padding: 0.45rem 0.55rem; border-radius: 0.55rem; background: rgb(255 255 255 / 80%); border: 1px solid #ede9fe; font-size: 0.68rem; }
.mclp-row strong { color: #6d28d9; }
.mclp-row span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #475569; }
.mclp-row em { color: #7c3aed; font-style: normal; white-space: nowrap; }
.mclp-error { color: #b91c1c !important; }
.card { border: 1px solid var(--color-border); border-radius: 0.9rem; background: var(--color-surface); padding: 0.85rem; display: grid; gap: 0.55rem; box-shadow: 0 2px 8px rgb(15 23 42 / 4%); }
.card--warn { background: #fffbeb; border-color: #fde68a; }
.card--sim { background: #f8fafc; }
.card-head { display: flex; align-items: center; justify-content: space-between; }
.card-head h3 { margin: 0; font-size: 0.95rem; }
.tag { font-size: 0.7rem; color: var(--color-muted); border: 1px solid var(--color-border); border-radius: 999px; padding: 0.1rem 0.55rem; background: #fff; }
.tag--warn { color: #b45309; border-color: #fde68a; background: #fff; }
.note { color: var(--color-muted); font-size: 0.76rem; line-height: 1.45; margin: 0; }
.controls { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: end; }
.field { display: grid; gap: 0.25rem; font-size: 0.82rem; color: var(--color-muted); }
.controls input { border: 1px solid var(--color-border); border-radius: 0.5rem; padding: 0.4rem 0.6rem; background: #fff; min-width: 0; }
.controls button { border: 1px solid var(--color-border); border-radius: 0.5rem; padding: 0.4rem 0.9rem; background: #2563eb; color: #fff; cursor: pointer; }
.controls button:disabled { opacity: 0.6; cursor: default; }
.error { color: #dc2626; font-size: 0.85rem; margin: 0; }
.summary { display: grid; gap: 0.25rem; }
.big { margin: 0; font-size: 1.1rem; font-weight: 700; }
.sub { margin: 0; font-size: 0.85rem; color: var(--color-muted); }
.empty { margin: 0; font-size: 0.85rem; color: var(--color-muted); }
.delta { margin: 0; font-size: 0.9rem; font-weight: 700; color: #047857; }
.prescription { margin: 0; padding: 0.55rem 0.65rem; border-radius: 0.55rem; background: #eff6ff; color: #1e40af; font-size: 0.72rem; line-height: 1.45; }
.grid-list { margin: 0.25rem 0 0; padding-left: 1.1rem; display: grid; gap: 0.2rem; font-size: 0.85rem; }
.grid-list--all { color: var(--color-muted); }
@media (min-width: 720px) {
  .community { gap: 1rem; }
  .card { padding: 1.25rem; }
}
@media (max-width: 430px) {
  .scorecard { grid-template-columns: 5.8rem minmax(0, 1fr); }
  .scorecard__hero strong { font-size: 1.65rem; }
  .scorecard__item { padding: 0.38rem; }
  .category-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

.community{gap:11px;padding:0;font-size:12px}.community-tools summary{font-size:11px;color:#718098;cursor:pointer;text-align:right;min-height:28px;display:block}.community-tools .page-head{margin:6px 0}.page-head h2{display:none}.page-head button,.page-head a{font-size:11px;padding:6px;min-height:34px}.community__iso{padding:0;border:0;background:none;box-shadow:none}.community__section-head{display:none}.service-picker{background:none;border:0;padding:0;margin-top:8px}.service-picker summary{font-size:12px;min-height:34px;color:#3d5f90}.service-picker__options{gap:5px}.service-picker__options label{font-size:11px}.community__actions{margin-top:8px;gap:7px}.community__actions button{font-size:12px;min-height:36px;padding:8px 12px;background:#2563eb;border:1px solid #2563eb;border-radius:10px;color:white}.community__actions>span{display:none}.scorecard{display:flex;align-items:center;gap:11px;background:linear-gradient(120deg,#eff5ff,#fafcff);border:1px solid #cedffc;padding:11px;border-radius:14px}.scorecard__ring{width:62px;height:62px;flex:none;border:4px solid #477bfa;border-radius:50%;background:white;display:flex;flex-direction:column;align-items:center;justify-content:center}.scorecard__ring strong{font-size:21px;line-height:1.2}.scorecard__ring small{font-size:9px;color:#6a7f9d}.scorecard__place{min-width:0}.scorecard__place h2{font-size:14px;margin:0;line-height:1.5}.scorecard__place p{font-size:11px;margin:5px 0;color:#6d7d93}.scorecard__place small{font-size:10px;color:#6d7d93}.category-card{padding:0;border:0;box-shadow:none;background:none}.category-card .card-head h3{font-size:12px}.category-card__hint:empty{display:none}.tag{font-size:10px;padding:3px 7px}.category-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.category-item{padding:9px 10px;border-radius:11px;background:white;min-width:0;gap:5px;border:1px solid #dde5ef}.category-item--ready{background:white;border-color:#dde5ef}.category-item[data-selected="true"]{background:#f7faff;border-color:#6094f8;box-shadow:0 2px 9px #2563eb14}.category-item__head strong{font-size:12px}.category-item p{font-size:11px;line-height:1.5;margin:3px 0}.category-item small{font-size:10px;color:#74869e}.coverage-chart{min-height:30px;gap:6px;padding:3px 0;font-size:10px;border:0}.coverage-chart__track{height:5px}.coverage-chart__fill{background:#19b78e}.category-item--error{background:#fff9ee;border-color:#f3dfb8}.mclp-card{padding:11px;background:#f0faf5;border-color:#cdebdc;border-radius:13px}.mclp-card .card-head h3{font-size:12px;color:#167458}.mclp-card .category-card__hint{font-size:10px}.mclp-card button{font-size:11px;min-height:34px}.mclp-row{font-size:11px;padding:8px}.card,.radius-card{padding:11px;border-radius:13px}.card h3,.radius-card h3{font-size:13px}.community-charts summary{font-size:12px;cursor:pointer;padding:8px 0;color:#5b7194}.scorecard__grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.scorecard__grid strong{display:block;font-size:14px}.big{font-size:18px}.note,.sub,.empty{font-size:11px}.community :deep(button),.community :deep(input),.community :deep(select){font-family:inherit}

.community__iso{gap:8px}.community__actions{margin-top:0}.community__actions button{min-height:36px}.category-item p{min-height:0}.category-item[data-selected=true]{outline:0}.coverage-chart>span:last-child{font-size:9px}.community-tools{margin-top:8px}.scorecard{margin:0}.service-picker{margin:0}.service-picker summary{min-height:32px}.blind-toggle{font-size:11px;min-height:34px;border-radius:9px;border:1px solid #dce6f4;color:#3566a9;background:#f7faff;padding:6px 10px;justify-self:start}

.facility-list summary,.coverage-details summary{font-size:12px;color:#5d7495;min-height:34px;display:flex;align-items:center;cursor:pointer}.facility-list button{display:flex;align-items:center;gap:9px;width:100%;border:0;border-bottom:1px solid #e7edf5;border-radius:0;padding:10px 0;background:white;text-align:left;min-height:48px}.facility-list button>span:nth-child(2){display:grid;gap:3px;min-width:0;flex:1}.facility-list strong{font-size:12px;overflow-wrap:anywhere}.facility-list small{font-size:10px;color:#74879f}.facility-list em{font-size:11px;color:#3d78db;font-style:normal;flex:none}.coverage-details .card{margin-top:6px}
.life-range-key{display:flex;align-items:center;gap:10px;padding:8px 0;font-size:11px;color:#718098}.life-range-key strong{font-size:14px;color:#334966;margin-right:auto}.life-range-key span{white-space:nowrap}.life-range-key span:before{content:'';display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:4px;background:var(--range-color)}.range-5{--range-color:#17b684}.range-10{--range-color:#39afa7}.range-15{--range-color:#3975ed}

/* 以真实内容为主的两列卡片，尺寸对齐截图规范。 */
.community{gap:16px;font-size:13px;line-height:1.55}
.scorecard{gap:14px;padding:15px;border-radius:16px;background:linear-gradient(120deg,#eff6ff,#f8fbff)}
.scorecard__ring{width:66px;height:66px;border-width:4px}.scorecard__ring strong{font-size:28px;letter-spacing:-1px}.scorecard__ring sup{font-size:13px;letter-spacing:0;margin-left:1px}.scorecard__ring small{font-size:11px}
.scorecard__place h2{font-size:16px;line-height:1.45}.scorecard__place p{font-size:13px;margin:5px 0}.scorecard__place small{font-size:12px}
.category-grid{gap:10px}.category-card .card-head h3{font-size:15px}.category-card .tag{font-size:12px}
.category-item{display:grid;grid-template-columns:1fr auto;gap:7px;padding:12px;border-radius:15px;transition:border-color .18s,box-shadow .18s,background .18s;position:relative}
.category-item__head{grid-column:1/-1;display:flex;align-items:flex-start;justify-content:space-between;gap:5px}.category-item__head strong{font-size:14px;display:flex;gap:5px;align-items:center;line-height:1.5;overflow-wrap:anywhere}.category-item__icon{font-size:18px;flex:none;line-height:1.3}
.category-item__percent{font-size:15px;color:#059669;line-height:1.5;flex:none;font-variant-numeric:tabular-nums}.category-item__percent.is-low{color:#d97706}
.category-item p{grid-row:3;font-size:12px;margin:0;color:#657b98}.category-item small{grid-row:3;font-size:11px;align-self:center;justify-self:end;white-space:nowrap}
.category-item .coverage-chart{grid-column:1/-1;grid-row:2;min-height:22px;padding:4px 0}.coverage-chart__track{height:6px;border-radius:6px;background:#f0f4f9}.coverage-chart__fill{border-radius:6px;transition:width .4s ease}.coverage-chart>span:last-child{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
.category-item[data-selected="true"]{border-color:#2563eb;box-shadow:0 0 0 1px #2563eb,0 4px 16px #2563eb0c;background:#f8fbff}
.category-item--error{background:#fffaf2;border-color:#f2dfb8}.category-item--loading .coverage-chart__track{background:linear-gradient(90deg,#f0f4f9,#dae6f9,#f0f4f9);background-size:200% 100%;animation:facility-shimmer 1.8s ease infinite}
.service-picker summary{font-size:14px;min-height:40px}.service-picker__options{gap:7px}.service-picker__options label{font-size:13px;display:inline-flex;align-items:center;gap:5px;min-height:34px;border-radius:20px;padding:4px 9px;box-sizing:border-box}.service-picker__options label>span{font-size:17px}.service-picker__options label:has(input:checked){background:#eff6ff;border-color:#9dc5ff;color:#1f5ed5}.service-picker__options input{accent-color:#2563eb}
.mclp-card{padding:14px;border-radius:16px;background:#effcf6;border-color:#b3eed4}.mclp-card .card-head h3{font-size:15px}.mclp-card .category-card__hint{font-size:12px}.mclp-card button{font-size:13px;min-height:40px}.mclp-row{font-size:13px;padding:10px}.card h3,.radius-card h3{font-size:15px}.facility-list strong{font-size:14px}.facility-list small{font-size:12px}.community-charts summary{font-size:13px}.note,.sub,.empty{font-size:12px}
@keyframes facility-shimmer{to{background-position:-200% 0}}
.category-item__head .category-item__icon{font-size:18px;color:inherit}.category-item[data-selected="true"]{outline:0}.coverage-chart:not(:disabled)::after{content:'';position:absolute;inset:0;border-radius:15px;cursor:pointer}.category-item:has(.coverage-chart:focus-visible){outline:3px solid #93c5fd;outline-offset:2px}.coverage-chart:focus-visible{outline:0}.category-item p{min-height:18px}
.service-picker__options input[type="checkbox"]{width:14px;height:14px;min-height:14px;flex:none;padding:0;margin:0}.service-picker__options label{border-radius:12px;min-height:38px;padding:6px;line-height:1.4}.service-presets button{font-size:12px;min-height:36px;border-radius:10px}.community__actions button{font-size:13px;min-height:40px}.service-picker .category-card__hint{font-size:12px}
@media(max-width:360px){.category-item{padding:10px}.category-item__head strong{font-size:13px}.category-item__head .category-item__icon{font-size:16px}.category-item small{font-size:10px}.category-item p{font-size:11px}.category-grid{gap:8px}}
@media(prefers-reduced-motion:reduce){.category-item,.coverage-chart__fill{transition:none}.category-item--loading .coverage-chart__track{animation:none}}
</style>
