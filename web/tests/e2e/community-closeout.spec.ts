import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

async function prepare(page: import('@playwright/test').Page) {
  await mockApi(page)
  await page.route('**/api/isochrones', route => {
    const body = route.request().postDataJSON()
    return route.fulfill({ json: { taskId: 'unit-iso', origin: body.origin, thresholdSeconds: body.thresholdSeconds,
      status: 'complete', mode: 'live', sourceKind: 'derived', cacheHit: false, pairsUsed: 48,
      algorithmVersion: 'test', radiiM: Object.fromEntries([0,45,90,135,180,225,270,315].map(b => [b, body.thresholdSeconds])),
      failedBearings: [], skippedBearings: [], warnings: ['source-mix:live-api+api-cache'], report: { effectiveBearings: 8, approxAreaM2: 1000000 } } })
  })
  await page.route('**/api/community/coverage', route => {
    const body = route.request().postDataJSON()
    return route.fulfill({ json: { coverage: Object.fromEntries(body.gridIds.map((id: string) => [id, true])),
      coveredCount: body.gridIds.length, totalGrids: body.gridIds.length, blindGrids: [],
      ...(body.newFacilityId ? { delta: { before: body.gridIds.length, after: body.gridIds.length } } : {}) } })
  })
  await page.route('**/api/reports/export', route => route.fulfill({ json: { content: JSON.stringify({ status: 'complete', sourceKind: 'derived', thresholdSeconds: 900 }) } }))
  await page.goto('/community')
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox', { name: '搜索地点', exact: true }).fill('回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
  await expect(page.getByRole('button', { name: '设施社区评分', exact: true })).toBeEnabled()
}

test('real threshold requests build heat layers; community coverage uses selected center and has chart/map links', async ({ page }) => {
  const calls: number[] = []
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/isochrones') calls.push(request.postDataJSON().thresholdSeconds) })
  const requests: unknown[] = []
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/pois/corridor') requests.push(request.postDataJSON().routeGeometry) })
  await prepare(page)
  await expect(page.locator('.life-range-key')).toContainText('15分钟生活圈')
  await expect(page.getByRole('button', { name: '◉ 时间分层', exact: true })).toHaveCount(0)
  expect(calls).toEqual([900, 300, 600])
  await expect(page.getByText(/部分方向未能完成测量/)).toHaveCount(0)

  await expect(page.getByText('7/7 已完成')).toBeVisible()
  await expect(page.locator('.coverage-chart')).toHaveCount(7)
  await page.getByRole('button', { name: '查看便利店覆盖' }).click()
  if (!await page.locator('.coverage-details').evaluate((el: HTMLDetailsElement) => el.open)) await page.locator('.coverage-details > summary').click()
  await expect(page.getByRole('heading', { name: '便利店覆盖详情' })).toBeVisible()
  expect(requests).toHaveLength(7)
  expect(requests.every(value => JSON.stringify(value) === JSON.stringify([{ lng: 116.36, lat: 40.09, crs: 'BD09' }, { lng: 116.36, lat: 40.09, crs: 'BD09' }]))).toBe(true)
  const downloaded = page.waitForEvent('download')
  if (!await page.locator('.community-tools').evaluate((el: HTMLDetailsElement) => el.open)) await page.locator('.community-tools > summary').click()
  await page.getByRole('button', { name: '导出报告' }).click()
  expect((await downloaded).suggestedFilename()).toContain('生活圈报告')
  await page.emulateMedia({ media: 'print' })
  await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')))
  await expect(page.locator('.coverage-details .summary')).toBeVisible()
  await expect(page.locator('.service-picker')).toHaveAttribute('open', '')
  await expect(page.locator('.shell__map')).toBeHidden()
  await expect(page.locator('.coverage-chart').first()).toBeVisible()
  expect(await page.locator('.sheet__content').evaluate(node => getComputedStyle(node).overflow)).toBe('visible')
  await page.emulateMedia({ media: 'screen' })
  await page.evaluate(() => window.dispatchEvent(new Event('afterprint')))
  await expect(page.locator('.service-picker')).not.toHaveAttribute('open', '')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('facility gaps share the circle, truncated searches stay unknown and removed panels stay absent', async ({ page }) => {
  await prepare(page)
  await expect(page.getByText('7/7 已完成')).toBeVisible()
  await page.route('**/api/pois/corridor', route => route.fulfill({ json: { traceId: 't', mode: 'live', sourceKind: 'derived',
    retrieval: { truncated: true, truncationReason: 'page_budget' }, pois: [], warnings: [] } }))
  await page.getByRole('button', { name: '设施社区评分', exact: true }).click()
  await expect(page.getByText('0/7 已完成')).toBeVisible()
  await expect(page.locator('.scorecard__ring strong')).toHaveText('—')
  await expect(page.getByText('1 公里基本设施', { exact: true })).toHaveCount(0)
  await expect(page.getByText('自定义步行时间', { exact: true })).toHaveCount(0)
  await expect(page.locator('.category-item').filter({ hasText: '菜市场' })).toBeVisible()
  await expect(page.locator('.category-item').filter({ hasText: '托育托管' })).toBeVisible()
  await expect(page.getByRole('button', { name: '重新开始', exact: true })).toHaveCount(0)
  await expect(page.locator('.origin-name')).toHaveText('回龙观小区')
})
