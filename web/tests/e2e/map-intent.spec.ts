import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

test('blank map clicks do not query an address until the user explicitly starts point selection', async ({ page }) => {
  await mockApi(page)
  let addressQueries = 0
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/locations/resolve') addressQueries++ })
  await page.goto('/community')
  await expect(page.locator('.baidu-map__legend')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '显示或隐藏图例', exact: true })).toHaveCount(0)
  await expect(page.locator('.origin-name')).toHaveText('搜索社区、地标或地址')
  await expect(page.locator('.thresholds')).toHaveCount(0)
  const map = page.locator('.baidu-map__container')
  await map.click({ position: { x: 80, y: 200 } })
  await expect(page.getByRole('button', { name: '确认位置', exact: true })).toHaveCount(0)
  expect(addressQueries).toBe(0)
  await page.locator('.shell__search').click()
  await page.getByRole('button', { name: '地图选位置', exact: true }).click()
  await expect(page.getByText('选择地点，查看路线和步行范围。', { exact: true })).toHaveCount(0)
  await expect(page.locator('.shell__omni')).not.toBeVisible()
  const guide = await page.locator('.baidu-map__pick-guide').boundingBox()
  expect(guide!.y).toBeGreaterThanOrEqual(0)
  expect(guide!.y).toBeLessThanOrEqual(20)
  await map.click({ position: { x: 80, y: 200 } })
  await expect(page.getByLabel('所选地点名称')).toHaveValue('构造验收地址')
  expect(addressQueries).toBe(1)
})
