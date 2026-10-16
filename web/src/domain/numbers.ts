/** F38：数值输入统一校验。v-model.number 在清空/非法文本时产生 NaN/null，HTML min/max 不能替代运行时校验。 */
export interface NumberFieldError {
  field: string
  message: string
}

export function sanitizeMinutes(
  value: unknown,
  field: string,
  { min = 0, max = 480, label }: { min?: number; max?: number; label: string },
): { ok: true; value: number } | { ok: false; error: NumberFieldError } {
  const num = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(num)) {
    return { ok: false, error: { field, message: `${label}必须是数字` } }
  }
  if (num < min || num > max) {
    return { ok: false, error: { field, message: `${label}必须在 ${min}—${max} 之间` } }
  }
  return { ok: true, value: num }
}
