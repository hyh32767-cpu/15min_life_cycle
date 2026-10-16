import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test('one life-circle flow shares time, excludes outside facilities and reuses pharmacy for basic checks', async ({ page }) => {
  await mockApi(page)
  const circles: number[] = []
  const searches: { category: string; windowRadiusM: number }[] = []
  await page.route('**/api/isochrones', route => {
    const body = route.request().postDataJSON()
    circles.push(body.thresholdSeconds)
    return route.fulfill({ json: { taskId: 'scoped-circle', status: 'complete', origin: body.origin,
      thresholdSeconds: body.thresholdSeconds, sourceKind: 'derived', failedBearings: [], skippedBearings: [],
      radiiM: Object.fromEntries([0, 45, 90, 135, 180, 225, 270, 315].map(b => [b, body.thresholdSeconds / 2])) } })
  })
  await page.route('**/api/pois/corridor', route => {
    const body = route.request().postDataJSON()
    searches.push(body)
    const origin = body.routeGeometry[0]
    return route.fulfill({ json: { pois: ['inside', 'outside'].map(id => ({ place: { uid: `${body.category}-${id}`, name: `${body.category}-${id}`,
      coord: { ...origin, lng: origin.lng + (id === 'inside' ? 0 : 0.02) }, source: 'synthetic-assumption' }, distanceToRouteM: id === 'inside' ? 0 : 1700 })),
    retrieval: { truncated: false }, warnings: [] } })
  })
  const facilities: string[][] = []
  page.on('request', request => {
    if (request.url().endsWith('/api/community/coverage')) facilities.push(request.postDataJSON().facilityIds)
  })
  await page.goto('/community')
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill('回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
  await page.getByRole('button', { name: '设施社区评分' }).click()
  await expect(page.getByText('7/7 已完成')).toBeVisible()
  expect(circles).toEqual([900])
  expect(searches.filter(s => s.category === '药店')).toHaveLength(1)
  expect(searches.some(s => s.category === '菜市场')).toBe(true)
  expect(searches.some(s => s.category === '托育托管')).toBe(true)
  expect(facilities.flat().every(id => id.endsWith('-inside'))).toBe(true)
  expect(searches.every(s => s.windowRadiusM < 500)).toBe(true)
  await page.getByRole('button', { name: '5 分钟', exact: true }).click()
  await expect(page.locator('.scorecard')).toHaveCount(0)
  expect(searches).toHaveLength(7)
  await page.getByRole('button', { name: '设施社区评分' }).click()
  await expect(page.getByText('7/7 已完成')).toBeVisible()
  expect(circles).toEqual([900, 300])
  expect(searches.slice(7).every(s => s.windowRadiusM < 200)).toBe(true)
  await expect(page.getByText('1 公里基本设施', { exact: true })).toHaveCount(0)
  await expect(page.getByText('自定义步行时间', { exact: true })).toHaveCount(0)
})

test('incomplete isochrone does not start facility coverage or claim a blind area', async ({ page }) => {
  await mockApi(page)
  await page.route('**/api/isochrones', route => {
    const body = route.request().postDataJSON()
    return route.fulfill({ json: { taskId: 'partial', status: 'partial', origin: body.origin, thresholdSeconds: body.thresholdSeconds,
      radiiM: { 0: 300, 90: 300 }, failedBearings: [180], skippedBearings: [270], sourceKind: 'derived' } })
  })
  let searches = 0
  page.on('request', r => { if (r.url().endsWith('/api/pois/corridor')) searches++ })
  await page.goto('/community')
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill('回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
  await page.getByRole('button', { name: '设施社区评分' }).click()
  await expect(page.getByRole('alert').filter({ hasText: '部分步行范围未能查到' })).toBeVisible()
  await expect(page.locator('.scorecard')).toHaveCount(0)
  expect(searches).toBe(0)
})
