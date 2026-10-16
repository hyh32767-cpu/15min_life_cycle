import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

for (const width of [390, 1280]) {
  test(`facility labels avoid the panel and preserve click identity (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 })
    await mockApi(page)
    // 屏幕投影/Label替身用于真实DOM尺寸验收，所有业务请求仍由mockApi封闭。
    await page.addInitScript(() => {
      type Point = { lng: number; lat: number }
      type Label = { content?: string; options?: { position: Point; offset: { width: number; height: number } }; styles?: Record<string, string> }
      const w = window as unknown as { BMap: { Map: { prototype: Record<string, unknown> }; Label: unknown }; mapStyles: unknown[] }
      w.mapStyles = []
      w.BMap.Label = class {
        styles: Record<string, string> = {}
        constructor(public content: string, public options: Label['options']) {}
        setStyle(styles: Record<string, string>) { this.styles = styles }
      }
      const project = (p: Point) => ({ x: (innerWidth > 820 ? (innerWidth + 422) / 2 : innerWidth / 2) + (p.lng - 116.36) * 90000,
        y: 220 - (p.lat - 40.09) * 90000 })
      Object.assign(w.BMap.Map.prototype, {
        pointToPixel: project,
        setMapStyle: (style: unknown) => w.mapStyles.push(style),
        addOverlay(o: Label) {
          if (!o.content || !o.options) return
          const node = document.createElement('div')
          const p = project(o.options.position)
          node.className = 'BMapLabel'
          node.innerHTML = o.content
          Object.assign(node.style, { position: 'absolute', left: `${p.x + o.options.offset.width}px`,
            top: `${p.y + o.options.offset.height}px`, zIndex: '10', ...o.styles })
          document.querySelector('.baidu-map__container')!.append(node)
        },
      })
    })
    await page.route('**/api/pois/corridor', route => {
      const body = route.request().postDataJSON()
      return route.fulfill({ json: { pois: [ [-.001, .0007], [.001, .0006], [.0017, -.0005], [-.0015, -.0007], [.0002, -.0013] ].map(([x, y], i) => ({ place: {
        uid: `${body.category}-${i}`, name: `${body.category}测试店${i + 1}`, tags: body.queryTerms, address: '测试地址',
        coord: { lng: 116.36 + x!, lat: 40.09 + y!, crs: 'BD09' }, source: 'synthetic-assumption',
      }, distanceToRouteM: 0 })), retrieval: { truncated: false }, warnings: [] } })
    })
    await page.goto('/community')
    await page.locator('.shell__search').click()
    await page.getByRole('searchbox').fill('回龙观')
    await page.getByRole('button', { name: '搜索', exact: true }).click()
    await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
    await expect(page.getByText('7/7 已完成', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '查看药店覆盖', exact: true }).click()
    const map = page.locator('.baidu-map__container')
    await expect(map.getByRole('button', { name: /药店测试店/ })).toHaveCount(5)
    expect(await page.evaluate(() => (window as unknown as { mapStyles: unknown[] }).mapStyles.length)).toBe(1)
    const bubbles = page.locator('.map-place')
    expect(await bubbles.count()).toBeGreaterThan(1)
    expect(await bubbles.count()).toBeLessThanOrEqual(width < 600 ? 4 : 7)
    const boxes = await bubbles.evaluateAll(nodes => nodes.map(n => {
      const r = n.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom }
    }))
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i]!, b = boxes[j]!
      expect(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top).toBe(true)
    }
    const sheet = (await page.locator('.sheet').boundingBox())!
    for (const b of boxes) {
      expect(b.right).toBeLessThanOrEqual(width - 66)
      expect(width < 820 ? b.bottom <= sheet.y - 12 : b.left >= sheet.x + sheet.width + 12).toBe(true)
    }
    await map.getByRole('button', { name: '药店测试店1 · 药店 · 参评设施', exact: true }).click()
    await expect(page.getByRole('region', { name: '生活圈设施详情' })).toContainText('药店测试店1')
    await expect(map.locator('.map-place--active')).toContainText('药店测试店1')
    const card = (await page.getByRole('region', { name: '生活圈设施详情' }).boundingBox())!
    const selectedBoxes = await bubbles.evaluateAll(nodes => nodes.map(n => {
      const r = n.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom }
    }))
    for (const b of selectedBoxes) expect(b.right <= card.x || b.left >= card.x + card.width || b.bottom <= card.y || b.top >= card.y + card.height).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('facility-labels.png') })
    await map.getByRole('button', { name: '回龙观小区', exact: true }).click()
    await expect(page.getByRole('region', { name: '生活圈设施详情' })).toHaveCount(0)
    await page.getByRole('button', { name: '查看早餐覆盖', exact: true }).click()
    await expect(map.getByRole('button', { name: /药店测试店/ })).toHaveCount(0)
    await expect(map.getByRole('button', { name: /早餐测试店/ })).toHaveCount(5)
  })
}
