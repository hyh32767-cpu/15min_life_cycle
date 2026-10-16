export function formatDurationSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return '未知'
  }
  const total = Math.round(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  if (hours > 0) {
    return `${hours}小时${minutes}分`
  }
  if (minutes > 0) {
    return `${minutes}分${secs > 0 ? `${secs}秒` : ''}`
  }
  return `${secs}秒`
}

export function parseClockToSeconds(value: string): number | null {
  const match = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(value.trim())
  if (!match) {
    return null
  }
  const hours = Number(match[1])
  const minutes = Number(match[2])
  const seconds = Number(match[3] ?? '0')
  if (hours > 23 || minutes > 59 || seconds > 59) {
    return null
  }
  return hours * 3600 + minutes * 60 + seconds
}

export function formatClockSeconds(seconds: number): string {
  const normalized = ((Math.round(seconds) % 86400) + 86400) % 86400
  const hours = Math.floor(normalized / 3600)
  const minutes = Math.floor((normalized % 3600) / 60)
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}
