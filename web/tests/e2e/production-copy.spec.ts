import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

for (const width of [320, 375, 1440]) {
  test(`community long address stays readable and time controls stay in one row at ${width}px`, async ({ page }) => {
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
    const buttons = page.locator('.thresholds button')
    const boxes = await Promise.all([0, 1, 2, 3].map(index => buttons.nth(index).boundingBox()))
    expect(new Set(boxes.map(box => Math.round(box!.y))).size).toBe(1)
    expect(boxes.every(box => box!.height >= 44)).toBe(true)
    expect(circleCalls).toBe(0)
    await buttons.nth(2).click()
    await expect(page.locator('.status-line')).toContainText('已完成')
    expect(circleCalls).toBe(1)
    await page.locator('.shell__search').click()
    await page.getByRole('button', { name: '关闭地点选择', exact: true }).click()
    await page.getByRole('button', { name: '重新开始', exact: true }).click()
    await expect(name).toHaveText('选择一个地点')
    await expect(buttons.first()).toBeDisabled()
    expect(circleCalls).toBe(1)
  })
}
