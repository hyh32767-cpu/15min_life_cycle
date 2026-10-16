import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test('community rating combines coverage and uncovered places without a second blind-spot panel', async ({ page }, testInfo) => {
  await page.setViewportSize({width:390,height:844})
  await mockApi(page)
  await page.goto('/community')
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill('回龙观')
  await page.getByRole('button',{name:'搜索',exact:true}).click()
  await page.getByRole('button',{name:'选择 回龙观小区',exact:true}).click()
  const action = page.getByRole('button',{name:'设施社区评分',exact:true})
  await expect(action).toBeEnabled()
  await action.click()
  await expect(page.getByText('7/7 已完成',{exact:true})).toBeVisible()
  await expect(page.locator('.scorecard__ring small')).toHaveText('设施社区评分')
  await expect(page.locator('.scorecard__place')).toContainText('满分100')
  await expect(page.locator('.category-card h3')).toHaveText('设施社区评分 · 服务覆盖')
  await expect(page.locator('.card--warn')).toHaveCount(0)
  await expect(page.locator('.category-item')).toHaveCount(7)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({path:testInfo.outputPath('community-rating.png')})
})
