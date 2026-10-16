import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test('estimated preview upgrades to measured boundary, then starts facilities once', async ({ page }) => {
  await mockApi(page)
  let polls = 0
  let prematureFacilities = false
  let center: unknown
  const base = { taskId: 'background-test', thresholdSeconds: 900, algorithmVersion: 'adaptive-test',
    radiiM: Object.fromEntries(Array.from({ length: 16 }, (_, i) => [i * 22.5, 600])),
    failedBearings: [], skippedBearings: [], warnings: [], cacheHit: false, pairsUsed: 140,
    expiresAt: new Date(Date.now() + 300_000).toISOString() }
  await page.route('**/api/isochrones', route => {
    const request = route.request().postDataJSON()
    expect(request.frontier).toBe(true)
    expect(request.l2First).toBe(true)
    center = request.origin
    if (request.thresholdSeconds !== 900) return route.fulfill({ json: { ...base, origin: center,
      thresholdSeconds: request.thresholdSeconds, status: 'complete', backgroundStatus: 'completed' } })
    return route.fulfill({ json: { ...base, origin: center, status: 'degraded', backgroundStatus: 'running' } })
  })
  await page.route('**/api/isochrones/background-test/status', route => {
    polls++
    return route.fulfill({ json: { ...base, origin: center, status: 'complete', backgroundStatus: polls < 4 ? 'running' : 'completed' } })
  })
  page.on('request', request => {
    if (request.url().includes('/api/pois/corridor') && polls < 4) prematureFacilities = true
  })
  await page.goto('/community')
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill('回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
  await expect(page.locator('.l2-banner')).toContainText('预估范围')
  await expect(page.locator('.l2-banner')).toContainText('正在完善边界')
  await expect(page.getByText('7/7 已完成', { exact: true })).toBeVisible()
  expect(polls).toBe(4)
  expect(prematureFacilities).toBe(false)
  await expect(page.locator('.l2-banner')).toHaveCount(0)
  await expect(page.locator('.status-line')).toContainText('已完成')
})
