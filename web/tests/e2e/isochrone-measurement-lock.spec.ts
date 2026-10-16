import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

for (const width of [390, 1280]) {
  test(`measurement locks navigation and edits while each measured boundary reaches the map (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    await mockApi(page)
    let phase = 0
    let requests = 0
    let center: unknown
    const response = (seconds = 900) => ({
      taskId: 'staged-circle', thresholdSeconds: seconds, origin: center,
      algorithmVersion: 'adaptive-test', status: phase ? 'complete' : 'degraded',
      backgroundStatus: phase === 3 ? 'completed' : 'running',
      radiiM: Object.fromEntries(Array.from({ length: phase < 2 ? 16 : phase === 2 ? 24 : 32 },
        (_, i) => [i * 360 / (phase < 2 ? 16 : phase === 2 ? 24 : 32), 600])),
      failedBearings: [], skippedBearings: [], warnings: [], cacheHit: false, pairsUsed: 140,
      expiresAt: new Date(Date.now() + 300_000).toISOString(),
    })
    await page.route('**/api/isochrones', route => {
      requests++
      center = route.request().postDataJSON().origin
      return route.fulfill({ json: response(route.request().postDataJSON().thresholdSeconds) })
    })
    await page.route('**/api/isochrones/staged-circle/status', route => route.fulfill({ json: response() }))
    await page.goto('/')
    await page.getByRole('link', { name: '生活圈', exact: true }).click()
    await expect(page).toHaveURL(/\/community$/)
    // 记录真正交给地图适配层的多边形顶点数，API及地图SDK均为构造替身。
    await page.evaluate(() => {
      const w = window as unknown as { BMap: { Polygon: unknown }; drawnCircleSizes: number[] }
      w.drawnCircleSizes = []
      w.BMap.Polygon = class {
        constructor(points: unknown[]) { w.drawnCircleSizes.push(points.length) }
      }
    })
    await page.locator('.shell__search').click()
    await page.getByRole('searchbox').fill('回龙观')
    await page.getByRole('button', { name: '搜索', exact: true }).click()
    await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
    await expect(page.locator('.measurement-status')).toBeVisible()
    await expect(page.locator('.shell__search')).toBeDisabled()
    await expect(page.getByRole('button', { name: '设施社区评分', exact: true, includeHidden: true })).toBeDisabled()
    await expect(page.getByRole('button', { name: '重新开始', includeHidden: true })).toHaveCount(0)
    const link = page.locator('.shell__nav-item').filter({ hasText: '顺路办事' })
    await expect(link).toHaveAttribute('aria-disabled', 'true')
    await link.dispatchEvent('click')
    await expect(page).toHaveURL(/\/community$/)
    await page.evaluate(() => window.history.back())
    await expect(page).toHaveURL(/\/community$/)
    await expect(page.getByRole('button', { name: '放大地图', exact: true })).toBeEnabled()

    phase = 1
    await expect(page.locator('.l2-banner')).toContainText('正在完善边界')
    await expect.poll(() => page.evaluate(() => (window as unknown as { drawnCircleSizes: number[] }).drawnCircleSizes.at(-1))).toBe(16)
    phase = 2
    await expect.poll(() => page.evaluate(() => (window as unknown as { drawnCircleSizes: number[] }).drawnCircleSizes.at(-1))).toBe(24)
    await expect(page.locator('.shell__search')).toBeDisabled()
    phase = 3
    await expect(page.locator('.measurement-status')).toHaveCount(0)
    await expect.poll(() => page.evaluate(() => (window as unknown as { drawnCircleSizes: number[] }).drawnCircleSizes.at(-1))).toBe(32)
    await expect(page.locator('.shell__search')).toBeEnabled()
    await expect(page.locator('.sheet__actions')).not.toHaveAttribute('inert')
    expect(requests).toBe(3)
    await link.click()
    await expect(page).toHaveURL('http://127.0.0.1:5173/')
  })
}

test('polling failure releases the measurement lock and permits retry', async ({ page }) => {
  await mockApi(page)
  let requests = 0
  await page.route('**/api/isochrones', route => {
    requests++
    return route.fulfill({ json: {
    taskId: 'failed-poll', status: 'degraded', backgroundStatus: 'running',
    origin: route.request().postDataJSON().origin, thresholdSeconds: 900, radiiM: {},
    failedBearings: [], skippedBearings: [], warnings: [], algorithmVersion: 'adaptive-test',
    cacheHit: false, pairsUsed: 0,
    } })
  })
  await page.route('**/api/isochrones/failed-poll/status', route => route.fulfill({
    status: 503, json: { error: { code: 'UPSTREAM_UNAVAILABLE', message: '暂时无法查询' } },
  }))
  await page.goto('/community')
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill('回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
  await expect(page.locator('.shell__search')).toBeDisabled()
  await expect(page.locator('.measurement-status')).toHaveCount(0)
  await expect(page.locator('.shell__search')).toBeEnabled()
  await expect(page.getByRole('button', { name: '重新生成生活圈', exact: true })).toBeEnabled()
  expect(requests).toBe(1)
  await page.getByRole('link', { name: '顺路办事', exact: true }).click()
  await expect(page).toHaveURL('http://127.0.0.1:5173/')
})
