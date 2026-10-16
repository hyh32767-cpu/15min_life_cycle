import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

for (const width of [320, 390, 1280]) {
  test(`reconstructed geometry, progressive loading and readable controls (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 })
    await mockApi(page)
    let phase = 0
    let origin: { lng: number; lat: number; crs: 'BD09' }
    const contour = () => [origin, { ...origin, lng: origin.lng + .003 }, { ...origin, lat: origin.lat + .002 }]
    const response = (seconds = 900) => ({ taskId: 'visual-circle', thresholdSeconds: seconds, origin,
      algorithmVersion: 'test-adaptive', status: phase ? 'complete' : 'degraded',
      backgroundStatus: phase === 2 ? 'completed' : 'running',
      radiiM: Object.fromEntries(Array.from({ length: 16 }, (_, i) => [i * 22.5, 600])),
      reconstruction: phase ? { method: 'test-contour', sampleCount: 100, contours: [contour()],
        clipMarginM: 80, classificationBoundary: 'ray-polygon', note: '构造数据' } : null,
      failedBearings: [], skippedBearings: [], warnings: [], cacheHit: false, pairsUsed: 100,
      expiresAt: new Date(Date.now() + 300_000).toISOString() })
    await page.route('**/api/isochrones', route => {
      origin = route.request().postDataJSON().origin
      return route.fulfill({ json: response(route.request().postDataJSON().thresholdSeconds) })
    })
    await page.route('**/api/isochrones/visual-circle/status', route => route.fulfill({ json: response() }))
    await page.goto('/community')
    // The shell is eager, but this route is lazy-loaded. Wait for its consumer
    // before starting the measurement, especially on a cold development server.
    await expect(page.getByRole('region', { name: '社区等时圈体检' })).toBeVisible({ timeout: 15_000 })
    await page.evaluate(() => {
      const w = window as unknown as { BMap: { Polyline: unknown }; contourLines: unknown[][] }
      w.contourLines = []
      w.BMap.Polyline = class { constructor(points: unknown[]) { w.contourLines.push(points) } }
    })
    await page.locator('.shell__search').click()
    await page.getByRole('searchbox').fill('回龙观')
    await page.getByRole('button', { name: '搜索', exact: true }).click()
    await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
    const loading = page.locator('.map-circle-loading')
    await expect(loading).toContainText('首轮完成后')
    await expect(loading).toHaveCSS('opacity', '1')
    await expect(loading.locator('.circle-loading__radar i')).toHaveCSS('animation-name', /^circle-scan/)
    await page.screenshot({ path: testInfo.outputPath('circle-loading.png') })
    phase = 1
    await expect(loading).toContainText('已显示 16 个方向')
    // Rendering rounds corners; the original contour remains the analysis input.
    await expect.poll(() => page.evaluate(() => (window as unknown as { contourLines: unknown[][] }).contourLines.at(-1)?.length ?? 0)).toBeGreaterThan(3)
    const drawn = await page.evaluate(() => (window as unknown as { contourLines: { lng: number; lat: number }[][] }).contourLines.at(-1)!)
    expect(drawn[0]).toEqual({ lng: origin.lng, lat: origin.lat })
    expect(drawn.at(-1)).toEqual({ lng: origin.lng, lat: origin.lat + .002 })
    expect(drawn.every(p => p.lng >= origin.lng && p.lng <= origin.lng + .003 && p.lat >= origin.lat && p.lat <= origin.lat + .002)).toBe(true)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await expect(loading.locator('.circle-loading__radar i')).toHaveCSS('animation-name', 'none')
    phase = 2
    await expect(loading).toHaveCount(0)
    await expect(page.getByText('7/7 已完成', { exact: true })).toBeVisible()
    await expect(page.locator('.category-item').first().locator('.category-item__icon')).toBeVisible()
    await expect(page.getByRole('button', { name: '定位到当前位置' }).locator('svg')).toHaveCount(1)
    await page.getByRole('button', { name: '展开或收起面板' }).click()
    await page.locator('.category-grid').scrollIntoViewIfNeeded()
    await page.locator('.category-item').nth(1).click({ position: { x: 20, y: 20 } })
    await expect(page.locator('.category-item').nth(1).getByRole('button')).toHaveAttribute('aria-pressed', 'true')
    await page.screenshot({ path: testInfo.outputPath('facility-cards.png') })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}
