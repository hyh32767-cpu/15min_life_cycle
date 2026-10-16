import { describe, expect, it } from 'vitest'
import { placeMapLabels } from '@/components/map/mapTheme'

describe('map label placement', () => {
  it('keeps labels inside visible map, avoids overlap and prioritizes the selected place', () => {
    const anchors = [
      { index: 0, x: 160, y: 160, width: 150, height: 54, priority: 1 },
      { index: 1, x: 165, y: 165, width: 150, height: 54, priority: 200 },
      { index: 2, x: 300, y: 350, width: 150, height: 54, priority: 0 },
    ]
    const bounds = { left: 12, top: 16, right: 324, bottom: 340 }
    const placed = placeMapLabels(anchors, bounds, 2)
    expect(placed.has(1)).toBe(true)
    expect(placed.has(2)).toBe(false)
    const rectangles = [...placed].map(([i, p]) => ({ ...p, w: anchors[i]!.width, h: anchors[i]!.height }))
    for (const p of rectangles) {
      expect(p.x).toBeGreaterThanOrEqual(bounds.left)
      expect(p.x + p.w).toBeLessThanOrEqual(bounds.right)
      expect(p.y).toBeGreaterThanOrEqual(bounds.top)
      expect(p.y + p.h).toBeLessThanOrEqual(bounds.bottom)
    }
    if (rectangles.length === 2) {
      const [a, b] = rectangles
      expect(a!.x + a!.w <= b!.x || b!.x + b!.w <= a!.x || a!.y + a!.h <= b!.y || b!.y + b!.h <= a!.y).toBe(true)
    }
  })
  it('leaves crowded labels collapsed and never changes input coordinates', () => {
    const anchors = Array.from({ length: 20 }, (_, index) => ({ index, x: 100, y: 90, width: 160, height: 54, priority: index }))
    const before = JSON.stringify(anchors)
    const placed = placeMapLabels(anchors, { left: 0, top: 0, right: 210, bottom: 200 }, 4)
    expect(placed.has(19)).toBe(true)
    expect(placed.size).toBeLessThan(4)
    expect(JSON.stringify(anchors)).toBe(before)
    expect(placeMapLabels(anchors, { left: 0, top: 0, right: 210, bottom: 200 }, 4,
      [{ left: 0, top: 0, right: 210, bottom: 200 }]).size).toBe(0)
    expect(placeMapLabels(anchors, { left: 500, top: 0, right: 900, bottom: 100 }, 4).size).toBe(0)
  })
})
