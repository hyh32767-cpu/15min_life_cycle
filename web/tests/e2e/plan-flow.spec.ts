import { expect, test } from '@playwright/test'

import { mockApi, openPlan } from './mocks'

// 焦点卡流：路线 → 类别 → 候选列表 → 单店详情 → 加入安排（抽屉）→ 规划 → 行程 → 持久化 → 复位。
// 全程无路由跳转。

async function setupEndpoints(page: import('@playwright/test').Page): Promise<void> {
  await page.goto('/')
  await page.locator('button.endpoint').first().click()
  await page.getByPlaceholder('搜索任意地点').fill('北京市昌平区回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.locator('.result').filter({ hasText: '回龙观小区' }).first().click()
  await page.locator('button.endpoint').nth(1).click()
  await page.getByPlaceholder('搜索任意地点').fill('北京市昌平区龙泽园')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.locator('.result').filter({ hasText: '龙泽苑' }).first().click()
}

test('route flow: candidate -> waypoint -> editable plan -> trip -> persisted waypoint removal', async ({ page }) => {
  await mockApi(page)
  await setupEndpoints(page)

  // 计算基准路线 → 路线焦点卡 + 类别入口
  await expect(page.locator('.route-box')).toBeVisible({ timeout: 15000 })

  // 类别 tile → 候选列表焦点
  await page.getByRole('button', { name: '买药', exact: true }).click()
  await expect(page.getByText(/顺路药店/)).toBeVisible({ timeout: 15000 })
  await expect(page.getByText(/测试药店|计算失败/).first()).toBeVisible({ timeout: 15000 })

  // 候选行 → 单店详情焦点
  await page.locator('.poi-main').first().click()
  await expect(page.getByRole('button', { name: '加入今天安排', exact: true })).toBeVisible()

  // 加入今天安排 → 安排抽屉自动打开
  await page.getByRole('button', { name: '加入今天安排', exact: true }).click()
  await openPlan(page)
  await expect(page.getByRole('dialog', { name: '今天安排' })).toBeVisible()
  await expect(page.getByText('测试药店').first()).toBeVisible()

  // 规划行程 → 方案与行程入口
  await page.getByRole('button', { name: '重新规划', exact: true }).click()
  await expect(page.getByRole('button', { name: '重新规划' })).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '预演行程' }).click()
  await expect(page.getByText('下一步').first()).toBeVisible()
  await expect(page.getByRole('button', { name: '完成' }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: /调整安排/ })).toBeVisible()

  // 关闭抽屉 → 底部安排条可见
  await page.getByRole('button', { name: '关闭今天行程' }).click()
  await expect(page.getByRole('button', { name: '查看行程', exact: true })).toBeVisible()


  // 刷新后任务仍在（版本化 localStorage），安排条常驻
  await page.reload()
  await expect(page.locator('.waypoints')).toContainText('测试药店')
  await openPlan(page)
  await expect(page.getByText('测试药店').first()).toBeVisible()
  await page.getByRole('button', { name: '关闭今天安排' }).click()
  await expect(page.locator('.plan-sheet')).toHaveCount(0)

  // 重新开始清空任务
  await page.getByRole('button', { name: '调整顺序', exact: true }).click()
  await page.getByRole('button', { name: '删除途经点 测试药店', exact: true }).click()
  await expect(page.locator('.waypoints__row')).toHaveCount(0)
  await page.reload()
  await expect(page.locator('.waypoints__row')).toHaveCount(0)
})

test('keyboard: route form and category tiles are reachable', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  const companySlot = page.locator('button.endpoint').first()
  await companySlot.focus()
  await expect(companySlot).toBeFocused()
  // 类别 tile 键盘可用
  await page.getByRole('button', { name: '购物', exact: true }).focus()
  await expect(page.getByRole('button', { name: '购物', exact: true })).toBeFocused()
})
