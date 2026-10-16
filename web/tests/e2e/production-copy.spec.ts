import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

for (const width of [320, 375, 1440]) {
  test(`community long address stays readable with automatic fixed layers at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await mockApi(page)
    let circleCalls = 0
    page.on('request', request => { if (request.url().endsWith('/api/isochrones')) circleCalls++ })
    await page.goto('/community')
    const address = '示例市示例区文化街道社区服务中心东门二层公共活动室'
    await page.locator('.shell__search').click()
    await page.getByRole('searchbox').fill(address)
    await page.getByRole('button', { name: '搜索', exact: true }).click()
    await page.getByRole('button', { name: `选择 ${address}候选`, exact: true }).click()
    const name = page.locator('.origin-name')
    await expect(name).toHaveText(`${address}候选`)
    const styles = await name.evaluate(el => {
      const css = getComputedStyle(el)
      return { size: parseFloat(css.fontSize), weight: Number(css.fontWeight), overflow: el.scrollWidth > el.clientWidth }
    })
    expect(styles.size).toBeGreaterThanOrEqual(14)
    expect(styles.weight).toBeGreaterThanOrEqual(700)
    expect(styles.overflow).toBe(false)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await expect(page.locator('.thresholds button')).toHaveCount(0)
    await expect(page.locator('.life-range-key')).toContainText('15分钟生活圈')
    await expect(page.getByText('7/7 已完成', { exact: true })).toBeVisible()
    expect(circleCalls).toBe(3)
    await expect(page.getByRole('button', { name: '重新开始', exact: true })).toHaveCount(0)
    await page.locator('.shell__search').click()
    await page.getByRole('button', { name: '关闭地点选择', exact: true }).click()
    expect(circleCalls).toBe(3)
  })
}
