export class ResultCache<T> {
  private entries = new Map<string, { value: T; expires: number }>()
  get(key: string): T | null {
    const entry = this.entries.get(key)
    if (!entry) return null
    if (entry.expires <= Date.now()) { this.entries.delete(key); return null }
    return JSON.parse(JSON.stringify(entry.value)) as T
  }
  put(key: string, value: T, sourceExpirations: (string | null | undefined)[]): void {
    if (!sourceExpirations.length || sourceExpirations.some(value => !value || !Number.isFinite(Date.parse(value)))) return
    const expires = Math.min(Date.now() + 10 * 60_000, ...sourceExpirations.map(value => Date.parse(value!)))
    if (expires <= Date.now()) return
    this.entries.delete(key)
    this.entries.set(key, { value: JSON.parse(JSON.stringify(value)) as T, expires })
    while (this.entries.size > 50) this.entries.delete(this.entries.keys().next().value!)
  }
}
