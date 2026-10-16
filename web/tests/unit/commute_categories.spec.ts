import { describe, expect, it } from 'vitest'
import { commuteCategories, commuteCategoryLabel, commuteCategoryQueries, shortcutCategoryIds } from '@/domain/commuteCategories'

describe('daily commute categories', () => {
  it('maps everyday actions to real POI terms and preserves legacy selection keys', () => {
    expect(commuteCategoryLabel('菜市场')).toBe('买菜')
    expect(commuteCategoryLabel('药店')).toBe('买药')
    expect(commuteCategoryQueries('菜市场')).toEqual(['菜市场$农贸市场$生鲜超市$蔬菜店'])
    expect(commuteCategoryQueries('卫生间')).toEqual(['公共厕所$卫生间'])
    expect(commuteCategoryQueries('医院')).toEqual(['医院'])
    expect(commuteCategoryQueries('未收录的旧类别')).toEqual(['未收录的旧类别'])
  })
  it('keeps one bounded query per category and unique persisted ids', () => {
    expect(new Set(commuteCategories.map(item => item.id)).size).toBe(commuteCategories.length)
    expect(shortcutCategoryIds.every(id => commuteCategories.some(item => item.id === id))).toBe(true)
    for (const item of commuteCategories) {
      const queries = commuteCategoryQueries(item.id)
      expect(queries).toHaveLength(1)
      expect(queries[0]!.length).toBeLessThanOrEqual(45)
      expect(queries[0]!.split('$').length).toBeLessThanOrEqual(10)
    }
  })
})
