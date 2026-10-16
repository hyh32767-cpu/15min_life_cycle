import { expect, test } from '@playwright/test'
import { mockApi, setupRoute } from './mocks'

test('community results and draft survive navigation without remeasurement; stale picks are canceled', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page)
  const calls: string[] = []
  page.on('request', request => { if (/\/api\/(isochrones|pois\/corridor|travel-matrix)$/.test(request.url())) calls.push(request.url()) })
  await page.goto('/community')
  await expect(page.getByRole('button', { name: '设施社区评分', exact: true })).toBeDisabled()
  await expect(page.getByRole('region', { name: '所选服务覆盖' })).toHaveCount(0)
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill('回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
  await page.getByRole('button', { name: '设施社区评分', exact: true }).click()
  await expect(page.getByText('7/7 已完成')).toBeVisible()
  await page.getByText('模拟新增设施', { exact: true }).click()
  await page.getByPlaceholder('模拟设施名称').fill('保留的草稿')
  await page.getByRole('button', { name: '地图选点', exact: true }).click()
  await page.locator('.baidu-map__container').click({ position: { x: 80, y: 200 } })
  await expect(page.getByRole('button', { name: '确认位置' })).toBeVisible()
  await page.getByRole('link', { name: '顺路办事', exact: true }).click()
  await expect(page.getByRole('button', { name: '确认位置' })).toHaveCount(0)
  await expect(page.locator('.endpoint').first()).toBeVisible()
  const measured = calls.length
  await page.getByRole('link', { name: '生活圈', exact: true }).click()
  await expect(page.getByText('7/7 已完成')).toBeVisible()
  await expect(page.getByPlaceholder('模拟设施名称')).toHaveValue('保留的草稿')
  expect(calls).toHaveLength(measured)
})

test('route band handoff uses fifteen minutes and returns to the selected route', async ({ page }) => {
  await mockApi(page)
  await page.route('**/api/route-bands', route => {
    const body = route.request().postDataJSON()
    return route.fulfill({ json: { routeHash: 'handoff', thresholdSeconds: body.thresholdSeconds,
      status: 'unknown', completeCount: 0, nodes: [body.routeGeometry[0]].map((origin, index) => ({ index, origin, status: 'partial', cached: true, warnings: [] })),
      fills: [], boundaries: [], maxGapM: 0, cacheHit: true, cost: { liveRequests: 0, cacheHits: 0, pairs: 0, livePairs: 0 } } })
  })
  let circles = 0
  page.on('request', request => { if (request.url().endsWith('/api/isochrones')) circles++ })
  await setupRoute(page)
  await expect(page.locator('.poi-main').first()).toBeVisible()
  await page.getByRole('button', { name: '沿途生活圈', exact: true }).click()
  const panel = page.getByRole('region', { name: '沿途生活圈' })
  await panel.getByRole('button', { name: '查看此处社区评分' }).click()
  await expect(page).toHaveURL(/community\?from=route-band/)
  await expect(page.locator('.life-range-key')).toContainText('15分钟生活圈')
  await expect.poll(() => circles).toBeGreaterThan(0)
  await page.getByText('报告与更多', { exact: true }).click()
  await page.getByRole('link', { name: '返回沿途' }).click()
  await expect(panel.getByText('沿途15分钟生活圈', { exact: true })).toBeVisible()
})
