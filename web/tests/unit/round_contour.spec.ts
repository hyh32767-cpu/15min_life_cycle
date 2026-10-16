import { expect, it } from 'vitest'
import { roundContour } from '@/components/map/roundContour'
import type { NamedCoord } from '@/domain/types'

it('rounds only the display copy, keeps open endpoints and stays inside the original bounds', () => {
  const line: NamedCoord[] = [{lng:116.4,lat:39.9,crs:'BD09'}, {lng:116.401,lat:39.9,crs:'BD09'}, {lng:116.401,lat:39.901,crs:'BD09'}]
  const saved = JSON.stringify(line), display = roundContour(line)
  expect(display.length).toBeGreaterThan(line.length)
  expect(display[0]).toEqual(line[0])
  expect(display.at(-1)).toEqual(line.at(-1))
  expect(display.every(p => p.lng >= 116.4 && p.lng <= 116.401 && p.lat >= 39.9 && p.lat <= 39.901)).toBe(true)
  expect(JSON.stringify(line)).toBe(saved)
  const closed = roundContour([...line, line[0]!])
  expect(closed[0]).toEqual(closed.at(-1))
})
