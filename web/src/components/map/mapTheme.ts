// 百度JSAPI 4.0 setMapStyle({styleJson, merge:true})；保留底图道路/POI与版权标识。
// https://lbs.baidu.com/docs/jsapi?title=jsapi4/guide/map/style
export const MAP_STYLE = [
  { featureType: 'land', elementType: 'geometry', stylers: { color: '#f5f5f0ff' } },
  { featureType: 'water', elementType: 'geometry', stylers: { color: '#b7dfebff' } },
  { featureType: 'green', elementType: 'geometry', stylers: { color: '#d7e8d7ff' } },
  { featureType: 'building', elementType: 'geometry', stylers: { color: '#e5e7e6ff' } },
  { featureType: 'manmade', elementType: 'geometry', stylers: { color: '#eeeee8ff' } },
  { featureType: 'road', elementType: 'geometry.fill', stylers: { color: '#ffffffff' } },
  { featureType: 'road', elementType: 'geometry.stroke', stylers: { color: '#dedfd7ff' } },
  { featureType: 'road', elementType: 'labels.text.fill', stylers: { color: '#697980ff' } },
  { featureType: 'road', elementType: 'labels.text.stroke', stylers: { color: '#ffffffff' } },
  { featureType: 'poilabel', elementType: 'labels.text.fill', stylers: { color: '#73828aff' } },
  { featureType: 'poilabel', elementType: 'labels.text.stroke', stylers: { color: '#ffffffee' } },
]

export interface LabelBounds { left: number; top: number; right: number; bottom: number }
export interface LabelAnchor { index: number; x: number; y: number; width: number; height: number; priority: number }
export interface LabelPlacement { x: number; y: number; side: 'above' | 'below' | 'left' | 'right' }

/** 只避让文字，不移动地理坐标；未放下文字的设施保留原位图标。 */
export function placeMapLabels(anchors: LabelAnchor[], bounds: LabelBounds, limit: number, obstacles: LabelBounds[] = []): Map<number, LabelPlacement> {
  const placed = new Map<number, LabelPlacement>()
  const occupied: LabelBounds[] = [...obstacles]
  for (const a of [...anchors].sort((a, b) => b.priority - a.priority || a.index - b.index)) {
    if (placed.size >= limit) break
    if (a.x < bounds.left || a.x > bounds.right || a.y < bounds.top || a.y > bounds.bottom) continue
    const choices: LabelPlacement[] = [
      { x: a.x - a.width / 2, y: a.y - a.height - 14, side: 'above' },
      { x: a.x + 16, y: a.y - a.height / 2, side: 'right' },
      { x: a.x - a.width - 16, y: a.y - a.height / 2, side: 'left' },
      { x: a.x - a.width / 2, y: a.y + 14, side: 'below' },
    ]
    for (const c of choices) {
      const r = { left: c.x, top: c.y, right: c.x + a.width, bottom: c.y + a.height }
      if (r.left < bounds.left || r.top < bounds.top || r.right > bounds.right || r.bottom > bounds.bottom) continue
      if (occupied.some(o => r.left < o.right + 8 && r.right + 8 > o.left && r.top < o.bottom + 8 && r.bottom + 8 > o.top)) continue
      // 不遮挡其他设施的锚点，保证收起的图标仍可点击。
      if (anchors.some(other => other.index !== a.index && other.x > r.left - 10 && other.x < r.right + 10 && other.y > r.top - 10 && other.y < r.bottom + 10)) continue
      placed.set(a.index, c)
      occupied.push(r)
      break
    }
  }
  return placed
}
