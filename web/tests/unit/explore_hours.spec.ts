import { expect, it } from 'vitest'
import { openingWaitForActivity } from '@/domain/exploreHours'
import type { PlaceRef } from '@/domain/types'

const place = (shopHours: string): PlaceRef => ({ name: '测试店', coord: { lng: 116, lat: 40, crs: 'BD09' }, source: 'api-cache', shopHours })

it('includes opening wait, accepts exact close and rejects service crossing close', () => {
  const p = place('18:00-19:00')
  expect(openingWaitForActivity(p, 17 * 3600, 3600)).toBe(3600)
  expect(openingWaitForActivity(p, 18 * 3600, 3600)).toBe(0)
  expect(openingWaitForActivity(p, 18 * 3600 + 1, 3600)).toBeNull()
})

it('uses a later valid interval and keeps unknown hours unknown', () => {
  expect(openingWaitForActivity(place('12:00-13:00;18:00-20:00'), 15 * 3600, 60)).toBe(3 * 3600)
  expect(openingWaitForActivity(place(''), 18 * 3600, 60)).toBeUndefined()
})
