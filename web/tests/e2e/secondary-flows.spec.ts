import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true })

test('removed time-gap URL returns to commute and does not expose duplicated controls', async ({ page }) => {
  await mockApi(page)
  await page.goto('/explore')
  await expect(page).toHaveURL('/')
  await expect(page.getByRole('link', { name: '时间空档' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: '生活圈', exact: true })).toBeVisible()
})

test('cases can reload after errors, switch details and close; ledger refresh and Escape work', async ({ page }) => {
  await mockApi(page)
  let failed = true
  await page.route('**/api/cases', route => failed
    ? route.fulfill({ status: 503, json: { error: { code: 'UPSTREAM_ERROR', message: '案例暂时不可用' } } })
    : route.fulfill({ json: { cases: [{ id: 'case-a', title: '社区甲', region: '北京' }, { id: 'case-b', title: '社区乙', region: '哈尔滨' }] } }))
  await page.route('**/api/cases/*', route => route.fulfill({ json: {
    title: route.request().url().endsWith('case-a') ? '案例甲详情' : '案例乙详情',
    radii: { '0': 600, '90': 800 }, metrics: { iou: 0.75 },
  } }))
  let ledgerCalls = 0
  await page.route('**/api/ledger/summary', route => route.fulfill({ json: {
    rows: 5, requests: 3, liveRequests: ++ledgerCalls, cacheHits: 2, pairs: 20, errors: 0,
  } }))
  await page.goto('/cases')
  await expect(page.getByRole('alert')).toBeVisible()
  failed = false
  await page.getByRole('button', { name: '重新加载' }).click()
  await expect(page.locator('.case-card')).toHaveCount(2)
  await page.locator('.case-card').first().getByRole('button', { name: '打开' }).click()
  await expect(page.locator('.detail')).toContainText('600–800 米')
  await expect(page.locator('.detail')).toContainText('75.0%')
  await page.locator('.case-card').nth(1).getByRole('button', { name: '打开' }).click()
  await expect(page.locator('.detail')).toContainText('案例乙详情')
  await page.getByRole('button', { name: '关闭案例' }).click()
  await expect(page.locator('.detail')).toHaveCount(0)
  await page.getByRole('button', { name: '使用记录', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '地图使用记录' })
  await expect(dialog.locator('dd').first()).toHaveText('1')
  await dialog.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(dialog.locator('dd').first()).toHaveText('2')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
})
