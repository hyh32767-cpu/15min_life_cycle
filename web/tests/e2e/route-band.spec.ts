import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test('mobile cached band supplements incrementally at fixed fifteen minutes', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await mockApi(page)
  const requests: { cacheOnly: boolean; centerIndex?: number; thresholdSeconds: number }[] = []
  let complete = 0
  await page.route('**/api/route-bands', async route => {
    const body = route.request().postDataJSON()
    requests.push(body)
    if (!body.cacheOnly) complete++
    const points = body.routeGeometry
    const center = points[0]
    const ring = [center, { ...center, lng: center.lng + .1 }, { ...center, lng: center.lng + .1, lat: center.lat + .1 }, { ...center, lat: center.lat + .1 }]
    const measured = body.thresholdSeconds === 900 ? complete : 0
    await route.fulfill({ json: { routeHash: 'r', thresholdSeconds: body.thresholdSeconds,
      status: measured === 2 ? 'complete' : 'unknown', completeCount: measured,
      nodes: [center, points.at(-1)].map((origin, index) => ({ origin, index,
        status: index < measured ? 'complete' : 'partial', cached: body.cacheOnly, warnings: [] })),
      fills: measured ? [ring] : [], boundaries: measured ? [ring] : [], maxGapM: 800, cacheHit: body.cacheOnly,
      cost: { liveRequests: body.cacheOnly ? 0 : 1, cacheHits: 0, pairs: 8, livePairs: body.cacheOnly ? 0 : 8 } } })
  })
  await page.goto('/')
  for (const [index, query, name] of [[0, '回龙观', '回龙观小区'], [1, '龙泽园', '龙泽苑']] as const) {
    await page.locator('button.endpoint').nth(index).click()
    await page.getByPlaceholder('搜索任意地点').fill(query)
    await page.getByRole('button', { name: '搜索', exact: true }).click()
    await page.locator('.result').filter({ hasText: name }).first().click()
  }
  await expect(page.getByRole('button', { name: '沿途生活圈', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '沿途生活圈', exact: true }).click()
  const panel = page.getByRole('region', { name: '沿途生活圈' })
  await expect(panel.getByText('0/2 处已测')).toBeVisible()
  expect(requests.every(request => request.cacheOnly)).toBe(true)
  await panel.getByRole('button', { name: '补齐沿途范围' }).click()
  await expect(panel.getByText('2/2 处已测')).toBeVisible()
  expect(requests.filter(request => !request.cacheOnly).map(request => request.centerIndex)).toEqual([0, 1])
  await panel.getByRole('button', { name: '仅看已测范围内地点' }).click()
  await expect(panel.getByRole('button', { name: '仅看已测范围内地点' })).toHaveAttribute('aria-pressed', 'true')
  await expect(panel.getByRole('button', { name: /^(5|10|15|20) 分钟$/ })).toHaveCount(0)
  expect(requests.every(request => request.thresholdSeconds === 900)).toBe(true)
  await page.getByRole('button', { name: '沿途生活圈', exact: true }).click()
  await expect(panel).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
