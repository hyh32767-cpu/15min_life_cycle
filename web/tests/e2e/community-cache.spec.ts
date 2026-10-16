import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test('same circle reuses finished services; added service alone queries and new center invalidates reuse', async ({ page }) => {
  await mockApi(page)
  const expiry = new Date(Date.now() + 300_000).toISOString()
  const searches: string[] = []
  let matrixCalls = 0
  await page.route('**/api/pois/corridor', route => {
    const body = route.request().postDataJSON()
    searches.push(body.category)
    return route.fulfill({ json: { expiresAt: expiry, cacheHit: false,
      pois: [{ place: { uid: body.category, name: body.category, tags: body.queryTerms,
        coord: body.routeGeometry[0], source: 'synthetic-assumption' }, distanceToRouteM: 0 }],
      retrieval: { truncated: false }, warnings: [] } })
  })
  await page.route('**/api/travel-matrix', route => {
    matrixCalls++
    const body = route.request().postDataJSON()
    return route.fulfill({ json: { cacheHit: false, expiresAt: expiry, cells: body.origins.flatMap((_origin: unknown, fromIndex: number) =>
      body.destinations.map((_destination: unknown, toIndex: number) => ({ fromIndex, toIndex,
        durationSeconds: 200, status: 'ok', sourceKind: 'synthetic-assumption' }))), warnings: [] } })
  })
  await page.goto('/community')
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill('回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
  await page.getByRole('button', { name: '设施社区评分' }).click()
  await expect(page.getByText('7/7 已完成')).toBeVisible()
  expect(searches).toHaveLength(7)
  expect(matrixCalls).toBe(7)
  await page.getByRole('button', { name: '设施社区评分' }).click()
  await expect(page.getByText('已复用 7 项结果')).toBeVisible()
  expect(searches).toHaveLength(7)
  expect(matrixCalls).toBe(7)
  await page.getByText('选择服务 · 已选 7 项', { exact: true }).click()
  await page.getByRole('checkbox', { name: '综合超市', exact: true }).check()
  await page.getByRole('button', { name: '设施社区评分' }).click()
  await expect(page.getByText('8/8 已完成')).toBeVisible()
  expect(searches.slice(7)).toEqual(['综合超市'])
  expect(matrixCalls).toBe(8)
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill('龙泽园')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '选择 龙泽苑', exact: true }).click()
  await page.getByRole('button', { name: '设施社区评分' }).click()
  await expect(page.getByText('8/8 已完成')).toBeVisible()
  expect(searches).toHaveLength(16)
  expect(matrixCalls).toBe(16)
})
