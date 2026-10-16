import { resolveOpeningWindows } from './openingHours'
import type { PlaceRef } from './types'

/** 返回额外营业等待；未知保持未知，已知但办不完返回 null。 */
export function openingWaitForActivity(place: PlaceRef, arrivalSeconds: number, serviceSeconds: number): number | null | undefined {
  const resolved = resolveOpeningWindows(place.structuredHours, place.shopHours)
  if (!resolved.windows.length) return undefined
  const waits = resolved.windows.flatMap((window) => {
    const close = window.closesSeconds <= window.opensSeconds ? window.closesSeconds + 86400 : window.closesSeconds
    const start = Math.max(arrivalSeconds, window.opensSeconds)
    return start + serviceSeconds <= close ? [start - arrivalSeconds] : []
  })
  return waits.length ? Math.min(...waits) : null
}
