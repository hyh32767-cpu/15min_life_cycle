import { describe, expect, it } from 'vitest'

import { describeSource, reasonLabel, sourceKindLabel, timelineKindLabel } from '@/domain/sourceExplain'

describe('sourceExplain', () => {
  it('explains each source kind without changing API shapes', () => {
    for (const kind of ['live-api', 'api-cache', 'user-input', 'synthetic-assumption', 'derived', 'unknown']) {
      const detail = describeSource('travel', '10分钟', kind)
      expect(detail.title).toBe('路段用时')
      expect(detail.source).toBe(sourceKindLabel(kind))
      expect(detail.detail.length).toBeGreaterThan(0)
    }
  })

  it('translates infeasible reasons and timeline kinds', () => {
    expect(reasonLabel('NO_ROUTE')).not.toBe('NO_ROUTE')
    // 未知原因给出可操作提示，不暴露内部代码。
    expect(reasonLabel('SOME_FUTURE_CODE')).not.toContain('SOME_FUTURE_CODE')
    expect(reasonLabel('SOME_FUTURE_CODE')).not.toBe('SOME_FUTURE_CODE')
    expect(timelineKindLabel('returnTravel')).toBe('返程')
    expect(timelineKindLabel('whatever')).toBe('whatever')
  })
})

describe('T212 OD status wording', () => {
  it('distinguishes missing measurement from genuine no-route', async () => {
    const { reasonLabel } = await import('@/domain/sourceExplain')
    expect(reasonLabel('OD_UNAVAILABLE')).toMatch('用时查询未完成')
    expect(reasonLabel('OD_UNAVAILABLE')).not.toBe(reasonLabel('NO_ROUTE'))
  })
})

describe('F53 total travel badge', () => {
  it('describes totals as segment aggregates, not a single leg source', async () => {
    const { describeSource } = await import('@/domain/sourceExplain')
    const detail = describeSource('totalTravel', '共20分钟（各段来源见时间线）', 'derived')
    expect(detail.title).toMatch('各段之和')
    expect(detail.source).toBe('计算结果')
  })
})
