import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test('initial route is ready before search becomes interactive', async ({ page }) => {
  await mockApi(page)
  let release!: () => void
  let requested!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const started = new Promise<void>(resolve => { requested = resolve })
  await page.route('**/src/features/community/CommunityPage.vue*', async route => {
    requested()
    await gate
    await route.continue()
  })
  const navigation = page.goto('/community', { waitUntil: 'domcontentloaded' })
  await started
  try {
    // A late initial navigation used to close a search opened in the shell.
    await expect(page.locator('.shell__search')).toHaveCount(0)
  } finally {
    release()
    await navigation
  }
  await expect(page.getByRole('region', { name: '社区等时圈体检' })).toBeVisible()
  await page.locator('.shell__search').click()
  const search = page.getByRole('searchbox', { name: '搜索地点', exact: true })
  await search.fill('回龙观')
  await expect(search).toHaveValue('回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
  await expect(page.getByText('7/7 已完成', { exact: true })).toBeVisible()
})
