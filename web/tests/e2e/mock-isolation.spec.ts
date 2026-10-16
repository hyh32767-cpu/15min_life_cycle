import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test('unconfigured endpoint fails inside mock without reaching the backend', async ({ page }) => {
  await mockApi(page)
  let leaked = 0
  await page.route('**/api/**', async route => { leaked++; await route.fulfill({ status: 598, body: 'unexpected network' }) }, { times: 1 })
  // 最新 handler 优先；再次安装 mock 后，故意调用没有构造响应的接口。
  await mockApi(page)
  await page.goto('/community')
  const result = await page.evaluate(async () => {
    const response = await fetch('/api/unconfigured')
    return { status: response.status, body: await response.json() }
  })
  expect(result.status).toBe(501)
  expect(result.body.error.code).toBe('MOCK_NOT_CONFIGURED')
  expect(leaked).toBe(0)
})
