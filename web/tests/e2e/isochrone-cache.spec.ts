import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'
import { mockApi } from './mocks'

async function chooseCenter(page: Page, query = '回龙观', name = '回龙观小区') {
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill(query)
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: `选择 ${name}`, exact: true }).click()
}

test('a center automatically draws only 5/10/15 layers, analyses at 15 and reuses cached circles', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page)
  const calls: number[] = [], analyses: number[] = []
  page.on('request', r => { if (new URL(r.url()).pathname === '/api/community/coverage') analyses.push(r.postDataJSON().thresholdSeconds) })
  await page.route('**/api/isochrones', route => {
    const b = route.request().postDataJSON()
    calls.push(b.thresholdSeconds)
    return route.fulfill({ json: { taskId: `circle-${calls.length}`, status: 'complete', origin: b.origin,
      expiresAt: new Date(Date.now() + 300_000).toISOString(), cacheHit: false, thresholdSeconds: b.thresholdSeconds,
      sourceKind: 'synthetic-assumption', pairsUsed: 0, failedBearings: [], skippedBearings: [], warnings: [],
      algorithmVersion: 'test', radiiM: Object.fromEntries(Array.from({ length: 16 }, (_, i) => [i * 22.5, b.thresholdSeconds / 1.5])) } })
  })
  await page.goto('/community')
  await page.evaluate(() => {
    const w = window as unknown as { BMap: { Polygon: unknown }; circleColors: string[] }
    w.circleColors = []
    w.BMap.Polygon = class { constructor(_: unknown, options: { fillColor: string }) { w.circleColors.push(options.fillColor) } }
  })
  await expect(page.getByRole('button', { name: /^(5|10|15|20) 分钟$/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '时间分层', exact: true })).toHaveCount(0)
  await chooseCenter(page)
  await expect(page.getByText('7/7 已完成', { exact: true })).toBeVisible()
  expect(calls).toEqual([900, 300, 600])
  // Reselecting the same center must not clear the circle and leave it disabled.
  await chooseCenter(page)
  await expect(page.getByText('7/7 已完成', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '设施社区评分', exact: true })).toBeEnabled()
  expect(calls).toEqual([900, 300, 600])
  expect(analyses.length).toBeGreaterThan(0)
  expect(analyses.every(s => s === 900)).toBe(true)
  expect(await page.evaluate(() => (window as unknown as { circleColors: string[] }).circleColors.slice(-3))).toEqual(['#3975ed', '#39afa7', '#17b684'])
  await page.getByText('报告与更多', { exact: true }).click()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出报告', exact: true }).click()
  const download = await downloadPromise
  const report = JSON.parse(await readFile((await download.path())!, 'utf8'))
  expect(report.scope.thresholdSeconds).toBe(900)
  expect(report.isochrone.thresholdSeconds).toBe(900)
  expect(report.charts.timeHeatLayers.map((l: { thresholdSeconds: number }) => l.thresholdSeconds)).toEqual([900, 600, 300])
  await chooseCenter(page, '另一处位置', '另一处位置候选')
  await expect.poll(() => calls.length).toBe(6)
  await expect(page.getByText('7/7 已完成', { exact: true })).toBeVisible()
  await chooseCenter(page)
  await expect(page.locator('.status-line')).toContainText('已复用步行范围')
  await expect(page.getByText('7/7 已完成', { exact: true })).toBeVisible()
  expect(calls).toHaveLength(6)
})

test('main-circle failure unlocks and requires explicit retry without analysing another threshold', async ({ page }) => {
  await mockApi(page)
  let calls = 0
  await page.route('**/api/isochrones', route => { calls++; return route.fulfill({ status: 503, json: { error: { code: 'UPSTREAM_UNAVAILABLE', message: '暂时无法测量' } } }) })
  await page.goto('/community')
  await chooseCenter(page)
  await expect(page.getByRole('button', { name: '重新生成生活圈', exact: true })).toBeVisible()
  await expect(page.locator('.shell__search')).toBeEnabled()
  await expect(page.getByRole('button', { name: '设施社区评分', exact: true })).toBeDisabled()
  expect(calls).toBe(1)
  await page.getByRole('button', { name: '重新生成生活圈', exact: true }).click()
  await expect.poll(() => calls).toBe(2)
})
