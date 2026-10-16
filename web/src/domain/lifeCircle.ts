import type { IsochroneResult, NamedCoord } from './types'

export function inLifeCircle(point: NamedCoord, ring: NamedCoord[]): boolean {
  if (ring.length < 3 || ring.some(p => p.crs !== point.crs)) return false
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[j], b = ring[i]
    const cross = (point.lng - a.lng) * (b.lat - a.lat) - (point.lat - a.lat) * (b.lng - a.lng)
    if (Math.abs(cross) < 1e-12 && point.lng >= Math.min(a.lng, b.lng) - 1e-10 && point.lng <= Math.max(a.lng, b.lng) + 1e-10
      && point.lat >= Math.min(a.lat, b.lat) - 1e-10 && point.lat <= Math.max(a.lat, b.lat) + 1e-10) return true
    if ((a.lat > point.lat) !== (b.lat > point.lat) && point.lng < (b.lng - a.lng) * (point.lat - a.lat) / (b.lat - a.lat) + a.lng) inside = !inside
  }
  return inside
}

/** 在当前实测近似边界内均匀布点，最多25点；只显示点结论，不推断整片区域。 */
export function lifeCircleSamples(origin: NamedCoord, ring: NamedCoord[]): { id: string; coord: NamedCoord }[] {
  if (!inLifeCircle(origin, ring)) return []
  const minLng = Math.min(...ring.map(p => p.lng)), maxLng = Math.max(...ring.map(p => p.lng))
  const minLat = Math.min(...ring.map(p => p.lat)), maxLat = Math.max(...ring.map(p => p.lat))
  if (maxLng - minLng < 1e-10 || maxLat - minLat < 1e-10) return []
  const points = new Map<string, NamedCoord>()
  function add(coord: NamedCoord): void { if (inLifeCircle(coord, ring)) points.set(`${coord.lng.toFixed(9)},${coord.lat.toFixed(9)}`, coord) }
  add(origin)
  // 使用格中心，避开边界上数值敏感的位置。
  for (let x = 0; x < 5; x++) for (let y = 0; y < 5; y++) add({
    lng: minLng + (x + 0.5) / 5 * (maxLng - minLng), lat: minLat + (y + 0.5) / 5 * (maxLat - minLat), crs: origin.crs,
  })
  return [...points.values()].slice(0, 25).map((coord, index) => ({ id: `circle-${index}`, coord }))
}

export function haversineMeters(a: NamedCoord, b: NamedCoord): number {
  const rad = Math.PI / 180
  const h = Math.sin((b.lat - a.lat) * rad / 2) ** 2
    + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin((b.lng - a.lng) * rad / 2) ** 2
  return 6371000 * 2 * Math.asin(Math.min(1, Math.sqrt(h)))
}

export function circleSearchRadius(origin: NamedCoord, ring: NamedCoord[]): number {
  return Math.max(100, Math.ceil(Math.max(...ring.map(p => haversineMeters(origin, p)))))
}

/**
 * E5 实验 16 城实测步行绕行系数表（步行路网距离 / 直线距离中位数）。
 * 用于 L2 先行降级链预览（先秒级展示 L2 估算圈与设施初筛，后台渐进升级为 L0/L1 路网实测）。
 */
export const CITY_DETOUR_FACTORS: Record<string, number> = {
  北京: 1.38,
  上海: 1.36,
  广州: 1.42,
  深圳: 1.44,
  成都: 1.35,
  杭州: 1.39,
  武汉: 1.46,
  重庆: 1.62,
  南京: 1.37,
  天津: 1.36,
  苏州: 1.38,
  西安: 1.34,
  长沙: 1.41,
  沈阳: 1.33,
  青岛: 1.43,
  郑州: 1.34,
}

export const DEFAULT_DETOUR_FACTOR = 1.40
export const WALK_SPEED_M_PER_S = 1.167 // 4.2 km/h ≈ 70 m/min

export function inferDetourFactor(origin: NamedCoord, cityHint?: string): number {
  if (cityHint) {
    for (const [name, factor] of Object.entries(CITY_DETOUR_FACTORS)) {
      if (cityHint.includes(name)) return factor
    }
  }
  const { lng, lat } = origin
  if (lng >= 106.0 && lng <= 107.2 && lat >= 29.0 && lat <= 30.2) return CITY_DETOUR_FACTORS['重庆']
  if (lng >= 115.8 && lng <= 117.0 && lat >= 39.4 && lat <= 40.6) return CITY_DETOUR_FACTORS['北京']
  if (lng >= 120.8 && lng <= 122.1 && lat >= 30.6 && lat <= 31.6) return CITY_DETOUR_FACTORS['上海']
  if (lng >= 113.7 && lng <= 114.6 && lat >= 22.4 && lat <= 22.9) return CITY_DETOUR_FACTORS['深圳']
  if (lng >= 113.0 && lng <= 113.7 && lat >= 22.8 && lat <= 23.5) return CITY_DETOUR_FACTORS['广州']
  return DEFAULT_DETOUR_FACTOR
}

export function estimateL2WalkSeconds(origin: NamedCoord, dest: NamedCoord, cityHint?: string): number {
  const straightM = haversineMeters(origin, dest)
  const rho = inferDetourFactor(origin, cityHint)
  return Math.max(1, Math.round((straightM * rho) / WALK_SPEED_M_PER_S))
}

export function estimateL2Circle(origin: NamedCoord, thresholdSeconds: number, cityHint?: string): IsochroneResult {
  const rho = inferDetourFactor(origin, cityHint)
  const walkBudgetM = thresholdSeconds * WALK_SPEED_M_PER_S
  const straightRadiusM = Number(Math.max(60, walkBudgetM / rho).toFixed(1))
  const bearings = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330]
  const radiiM: Record<string, number> = {}
  for (const b of bearings) {
    radiiM[String(b)] = straightRadiusM
  }
  return {
    taskId: 'l2-preview',
    traceId: 'l2-preview',
    mode: 'live',
    sourceKind: 'derived',
    status: 'degraded',
    origin,
    thresholdSeconds,
    radiiM,
    failedBearings: [],
    skippedBearings: [],
    algorithmVersion: 'l2-detour-factor-v1',
    warnings: [`已先行生成 L2 预估圈（绕行系数 ρ=${rho.toFixed(2)}，直线折算半径 ${Math.round(straightRadiusM)} 米），正在后台实测真实步行路网…`],
    cacheHit: false,
    pairsUsed: 0,
    backgroundStatus: 'running',
  }
}

export interface UserPreferences {
  thresholdSeconds?: number
  serviceIds?: string[]
  commuteCategory?: string
  commuteBudgetMinutes?: number
  commuteStayMinutes?: number
}

const PREFS_STORAGE_KEY = 'shunshou-user-prefs-v1'

export function loadUserPrefs(): UserPreferences {
  if (typeof window === 'undefined' || !window.localStorage) return {}
  try {
    const raw = window.localStorage.getItem(PREFS_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as UserPreferences
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function saveUserPrefs(patch: Partial<UserPreferences>): UserPreferences {
  const next = { ...loadUserPrefs(), ...patch }
  if (typeof window !== 'undefined' && window.localStorage) {
    try {
      window.localStorage.setItem(PREFS_STORAGE_KEY, JSON.stringify(next))
    } catch {
      // ignore storage errors
    }
  }
  return next
}
