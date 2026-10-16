import { expect, test } from '@playwright/test'
import { mockApi, setupRoute } from './mocks'

test('selected center automatically measures layers and covered grids skip unnecessary facility pairs', async ({ page }) => {
  await mockApi(page)
  const isoCalls: number[] = []
  let pairs = 0
  page.on('request', request => {
    if (request.url().endsWith('/api/isochrones')) isoCalls.push(request.postDataJSON().thresholdSeconds)
    if (request.url().endsWith('/api/travel-matrix')) {
      const body = request.postDataJSON()
      pairs += body.origins.length * body.destinations.length
    }
  })
  await page.route('**/api/pois/corridor', route => {
    const body = route.request().postDataJSON()
    return route.fulfill({ json: { traceId: 'test', mode: 'live', sourceKind: 'derived',
      pois: Array.from({ length: 6 }, (_, i) => ({ place: { uid: `${body.category}-${i}`, name: `设施${i}`, tags: body.queryTerms,
        address: '构造响应', source: 'synthetic-assumption', coord: { lng: 116.36 + i * .001, lat: 40.09, crs: 'BD09' } }, distanceToRouteM: i * 100 })),
      retrieval: { truncated: false, queryTerms: body.queryTerms }, warnings: [] } })
  })
  await page.goto('/community')
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox', { name: '搜索地点', exact: true }).fill('回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  const checked = page.waitForRequest(r => r.url().endsWith('/api/community/coverage'))
  await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
  await expect(page.locator('.origin-name')).toHaveText('回龙观小区')
  const sampleCount = (await checked).postDataJSON().gridIds.length
  await expect(page.getByText('7/7 已完成')).toBeVisible()
  expect(isoCalls).toEqual([900, 300, 600])
  await page.getByRole('button', { name: '查看建议', exact: true }).click()
  await expect(page.locator('.mclp-row').getByText('本次采样点已全部覆盖')).toHaveCount(3)
  expect(pairs).toBe(sampleCount * 7) // 七类共用圈内采样，每点第一家可达便不再追加测量。
})

test('restoring saved commute on community page does not requery routes or pois', async ({ page }) => {
  await mockApi(page)
  await setupRoute(page)
  await expect(page.locator('.poi-main').first()).toBeVisible()
  await page.getByRole('link', { name: '生活圈', exact: true }).click()
  await expect(page).toHaveURL(/\/community$/)
  const requests: string[] = []
  page.on('request', request => { if (/\/api\/(routes\/walking|pois\/corridor|travel-matrix)$/.test(request.url())) requests.push(request.url()) })
  await page.reload()
  await expect(page.getByRole('button', { name: '设施社区评分', exact: true })).toBeVisible()
  await expect(page.locator('.baidu-map__container')).toBeVisible()
  await expect(page.getByText('地图服务已连接')).toHaveCount(0)
  await page.getByRole('button', { name: '展开或收起面板' }).click()
  expect(requests).toEqual([])
})

test('limited candidate coverage is explicit and does not claim an exhaustive supply score', async ({ page }) => {
  await mockApi(page)
  const pageLimits: number[] = []
  await page.route('**/api/pois/corridor', route => {
    const body = route.request().postDataJSON()
    pageLimits.push(body.maxPagesPerWindow)
    return route.fulfill({ json: { traceId: 'limited-test', mode: 'live', sourceKind: 'derived',
      pois: [{ place: { uid: `${body.category}-1`, name: '构造候选', tags: body.queryTerms, source: 'synthetic-assumption',
        coord: { lng: 116.36, lat: 40.09, crs: 'BD09' } }, distanceToRouteM: 100 }],
      retrieval: { truncated: true, truncationReason: 'page_budget' }, warnings: [] } })
  })
  await page.goto('/community')
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox', { name: '搜索地点', exact: true }).fill('回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
  await expect(page.getByText('7/7 已完成')).toBeVisible()
  await expect(page.locator('.scorecard__ring small')).toHaveText('设施社区评分')
  await expect(page.getByText(/仅评估本次可确认服务类型的设施/)).toHaveCount(0)
  expect(pageLimits).toEqual([1, 1, 1, 1, 1, 1, 1])
})
