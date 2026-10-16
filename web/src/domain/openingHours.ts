import type { NamedCoord } from './types'

export interface OpeningWindowInput {
  opensSeconds: number
  closesSeconds: number
  source: 'structured' | 'text'
  /** F43：百度 regular_open_hour 按星期分组；缺 day 时为 -1（调用方按场景星期过滤，无日期则 unknown）。 */
  day?: number
  closeDay?: number
}

/**
 * 营业时间解析（F27）：
 * - 优先 structuredHours（百度结构化字段），支持多时段/跨午夜/按星期；
 * - 仅有文本 shopHours 时做单段提取，失败即 unknown；
 * - 从不假设全天营业；无时间窗返回空数组。
 */
function toSeconds(hour: unknown, minute: unknown): number | null {
  const h = Number(hour)
  const m = Number(minute ?? 0)
  if (!Number.isFinite(h) || !Number.isFinite(m)) return null
  if (h < 0 || h > 24 || m < 0 || m > 59) return null
  if (h === 24 && m !== 0) return null
  return h * 3600 + m * 60
}

function parseClockText(text: string): number | null {
  const match = /(\d{1,2})(?::(\d{2}))?/.exec(text.trim())
  if (!match) return null
  return toSeconds(match[1], match[2] ?? 0)
}

function parseRangeText(text: string): { opens: number; closes: number } | null {
  const parts = text.split(/[-—~至]+/)
  if (parts.length !== 2) return null
  const opens = parseClockText(parts[0])
  const closes = parseClockText(parts[1])
  if (opens == null || closes == null) return null
  return { opens, closes }
}

function asDay(value: unknown): number | null {
  const day = Number(value)
  if (!Number.isInteger(day) || day < 0 || day > 6) return null
  return day
}

/** F43：百度 regular_open_hour.periods 归一化（open/close 嵌套 day/hour/minute）。 */
export function parseRegularOpenPeriods(
  periods: Record<string, unknown>[] | null | undefined,
): OpeningWindowInput[] {
  if (!Array.isArray(periods)) return []
  const out: OpeningWindowInput[] = []
  for (const period of periods) {
    if (!period || typeof period !== 'object') continue
    const record = period as Record<string, unknown>
    const open = (record.open ?? {}) as Record<string, unknown>
    const close = (record.close ?? {}) as Record<string, unknown>
    const day = asDay(open.day)
    if (day == null) continue
    const opens = toSeconds(open.hour, open.minute ?? 0)
    if (opens == null) continue
    if (close && Object.keys(close).length) {
      const closeDay = asDay(close.day ?? day)
      const closes = toSeconds(close.hour, close.minute ?? 0)
      if (closeDay == null || closes == null) continue
      out.push({ opensSeconds: opens, closesSeconds: closes, source: 'structured', day, closeDay })
    } else {
      // 只有 open、无 close：当天 00:00 → 次日 00:00（closes 00:00 + closeDay 次日，与后端一致）。
      out.push({ opensSeconds: 0, closesSeconds: 0, source: 'structured', day, closeDay: (day + 1) % 7 })
    }
  }
  return out
}

export function parseStructuredHours(
  structured: Record<string, unknown>[] | null | undefined,
): OpeningWindowInput[] {
  if (!Array.isArray(structured)) return []
  const out: OpeningWindowInput[] = []
  for (const entry of structured) {
    if (!entry || typeof entry !== 'object') continue
    const record = entry as Record<string, unknown>
    // 兼容多种百度结构化形态：{open, close} / {opens, closes} / {start, end} / {time: "08:00-22:00"}
    const rawOpen = record.open ?? record.opens ?? record.start ?? record.startTime
    const rawClose = record.close ?? record.closes ?? record.end ?? record.endTime
    if (typeof rawOpen === 'number' && typeof rawClose === 'number'
      && Number.isFinite(rawOpen) && Number.isFinite(rawClose)
      && rawOpen >= 0 && rawClose >= 0) {
      out.push({ opensSeconds: Math.round(rawOpen), closesSeconds: Math.round(rawClose), source: 'structured' })
      continue
    }
    if (typeof rawOpen === 'string' && typeof rawClose === 'string') {
      const opens = parseClockText(rawOpen)
      const closes = parseClockText(rawClose)
      if (opens != null && closes != null) {
        out.push({ opensSeconds: opens, closesSeconds: closes, source: 'structured' })
      }
      continue
    }
    const rawTime = record.time ?? record.hours ?? record.period
    if (typeof rawTime === 'string') {
      const range = parseRangeText(rawTime)
      if (range) out.push({ opensSeconds: range.opens, closesSeconds: range.closes, source: 'structured' })
    }
  }
  return out
}

export function parseHoursText(shopHours: string | null | undefined): OpeningWindowInput[] {
  // F43：文本支持逗号/分号/顿号分隔的多段（如 "08:30-11:30,13:30-17:00"）；单段失败即 unknown。
  if (!shopHours) return []
  const out: OpeningWindowInput[] = []
  for (const segment of shopHours.split(/[,;；、\n]+/)) {
    const text = segment.trim()
    if (!text) continue
    const match = /(\d{1,2}):(\d{2})\s*[-—~至]+\s*(\d{1,2}):(\d{2})/.exec(text)
    if (!match) continue
    const opens = toSeconds(match[1], match[2])
    const closes = toSeconds(match[3], match[4])
    if (opens == null || closes == null) continue
    out.push({ opensSeconds: opens, closesSeconds: closes, source: 'text' })
  }
  return out
}

export interface ResolvedWindows {
  windows: OpeningWindowInput[]
  source: 'structured' | 'text' | 'unknown'
}

/**
 * F43：结构化优先（含 regular_open_hour.periods 与后端归一化形态），文本多段兜底，否则 unknown。
 * 无场景日期时不能把某星期窗口套到所有日期：此时按天窗口全部降级为 unknown，
 * 由调用方在有日期前保持“未知未限”；跨午夜原样保留，后端处理。
 */
export function resolveOpeningWindows(
  structured: Record<string, unknown>[] | null | undefined,
  shopHours: string | null | undefined,
  opts?: { weekday?: number | null },
): ResolvedWindows {
  const entries = structured ?? []
  const normalized = entries.filter(
    (entry): entry is Record<string, unknown> =>
      !!entry && typeof entry === 'object'
      && typeof (entry as Record<string, unknown>).opensSeconds === 'number'
      && typeof (entry as Record<string, unknown>).closesSeconds === 'number'
      && typeof (entry as Record<string, unknown>).day === 'number',
  )
  if (normalized.length) {
    if (opts?.weekday == null) return { windows: [], source: 'unknown' }
    const windows = normalized
      .filter((entry) => (entry.day as number) === opts.weekday)
      .map((entry) => ({
        opensSeconds: entry.opensSeconds as number,
        closesSeconds: entry.closesSeconds as number,
        source: 'structured' as const,
        day: entry.day as number,
        closeDay: entry.closeDay as number | undefined,
      }))
    if (windows.length) return { windows, source: 'structured' }
    return { windows: [], source: 'unknown' }
  }
  // F43 回退：只有“百度 periods 形态”（open 为嵌套对象）才按星期处理；
  // 旧扁平形态（open/close 为字符串/数字）继续走 parseStructuredHours，不受星期门控。
  const maybePeriods = entries.filter(
    (entry): entry is Record<string, unknown> => {
      if (!entry || typeof entry !== 'object') return false
      const record = entry as Record<string, unknown>
      const open = record.open
      return !!open && typeof open === 'object'
    },
  )
  if (maybePeriods.length) {
    if (opts?.weekday == null) return { windows: [], source: 'unknown' }
    const windows = parseRegularOpenPeriods(maybePeriods)
      .filter((window) => window.day === opts.weekday)
    if (windows.length) return { windows, source: 'structured' }
    return { windows: [], source: 'unknown' }
  }
  const structuredWindows = parseStructuredHours(structured)
  if (structuredWindows.length) return { windows: structuredWindows, source: 'structured' }
  const textWindows = parseHoursText(shopHours)
  if (textWindows.length) return { windows: textWindows, source: 'text' }
  return { windows: [], source: 'unknown' }
}

export function primaryWindow(windows: OpeningWindowInput[]): OpeningWindowInput | null {
  return windows[0] ?? null
}

export type { NamedCoord }
