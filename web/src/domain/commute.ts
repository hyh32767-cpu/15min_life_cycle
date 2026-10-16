import { resolveOpeningWindows } from './openingHours'
import type { PlaceRef } from './types'

export interface CandidateTimingInput {
  startToPoiSeconds: number | null
  poiToEndSeconds: number | null
  baselineSeconds: number
  waitSeconds?: number
  serviceSeconds?: number
  departureSeconds?: number
  deadlineSeconds?: number
  maxExtraTravelSeconds?: number
  place?: PlaceRef
}

export interface CandidateTiming {
  feasible: boolean
  extraTravelSeconds: number | null
  finishSeconds: number | null
  slackSeconds: number | null
  reasons: string[]
  windowSource?: 'structured' | 'text' | 'unknown'
}
export function rankCandidate(input: CandidateTimingInput): CandidateTiming {
  const reasons: string[] = []
  // F38：v-model.number 在清空/非法文本时产生 NaN；NaN 不得进入排序计算，直接判不可行。
  const finiteOrNull = (v: number | null | undefined): boolean => v == null || Number.isFinite(v)
  if (!finiteOrNull(input.startToPoiSeconds) || !finiteOrNull(input.poiToEndSeconds)
    || !Number.isFinite(input.baselineSeconds) || !finiteOrNull(input.waitSeconds)
    || !finiteOrNull(input.serviceSeconds) || !finiteOrNull(input.departureSeconds)
    || !finiteOrNull(input.deadlineSeconds) || !finiteOrNull(input.maxExtraTravelSeconds)) {
    return { feasible: false, extraTravelSeconds: null, finishSeconds: null,
             slackSeconds: null, reasons: ['INVALID_INPUT'] }
  }
  if (input.startToPoiSeconds == null || input.poiToEndSeconds == null) {
    return { feasible: false, extraTravelSeconds: null, finishSeconds: null,
             slackSeconds: null, reasons: ['NO_ROUTE'] }
  }
  const total = input.startToPoiSeconds + input.poiToEndSeconds
  const extra = total - input.baselineSeconds
  // F36：已知营业窗口纳入可行性。到达=出发+去程；多段取最早可完成；跨午夜 closes<=opens 则 +86400。
  // 未知营业时间保持 unknown，不推断全天营业。
  const resolved = input.place
    ? resolveOpeningWindows(input.place.structuredHours, input.place.shopHours)
    : { windows: [], source: 'unknown' as const }
  const arrival = (input.departureSeconds ?? 0) + input.startToPoiSeconds
  let serviceStart = arrival
  if (resolved.windows.length) {
    let best: { start: number; finish: number } | null = null
    for (const window of resolved.windows) {
      const opens = window.opensSeconds
      let closes = window.closesSeconds
      if (closes <= opens) closes += 86400
      if (arrival > closes) continue
      const candidateStart = Math.max(arrival, opens)
      const finish = candidateStart + (input.serviceSeconds ?? 0)
      if (finish > closes) continue
      if (!best || finish < best.finish) best = { start: candidateStart, finish }
    }
    if (!best) {
      reasons.push('CLOSED')
    } else {
      serviceStart = best.start
    }
  }
  const finish = serviceStart + total - input.startToPoiSeconds
    + (input.waitSeconds ?? 0) + (input.serviceSeconds ?? 0)
  if (input.maxExtraTravelSeconds != null && extra > input.maxExtraTravelSeconds) {
    reasons.push('EXTRA_BUDGET')
  }
  if (input.deadlineSeconds != null && finish > input.deadlineSeconds) {
    reasons.push('DEADLINE')
  }
  return {
    feasible: reasons.length === 0,
    extraTravelSeconds: extra,
    finishSeconds: finish,
    slackSeconds: input.deadlineSeconds != null ? input.deadlineSeconds - finish : null,
    reasons,
    windowSource: resolved.source,
  }
}
