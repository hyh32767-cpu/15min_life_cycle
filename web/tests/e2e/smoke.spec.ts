import { expect, test } from '@playwright/test'

import { mockApi } from './mocks'

test('M0 shell renders navigation and commute route card', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await expect(page.locator('.baidu-map__container')).toBeVisible()
  await expect(page.getByText('地图服务已连接')).toHaveCount(0)
  await expect(page.getByRole('link', { name: '顺路办事' })).toBeVisible()
  await expect(page.locator('.endpoint').first()).toContainText('起点')
})

test('endpoint picker searches company/home from mocked api', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await page.locator('button.endpoint').first().click()
  await page.getByPlaceholder('搜索任意地点').fill('北京市昌平区回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await expect(page.getByText('回龙观小区').first()).toBeVisible()
  await page.locator('.result').filter({ hasText: '回龙观小区' }).first().click()

  await page.locator('button.endpoint').nth(1).click()
  await page.getByPlaceholder('搜索任意地点').fill('北京市昌平区龙泽园')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await expect(page.getByText('龙泽苑').first()).toBeVisible()
})

test('legacy plan routes redirect to the single commute page', async ({ page }) => {
  await mockApi(page)
  await page.goto('/plan')
  await expect(page).toHaveURL('/')
  await expect(page.locator('.endpoint').first()).toBeVisible()
  await page.goto('/plans/0/run')
  await expect(page).toHaveURL('/')
})
