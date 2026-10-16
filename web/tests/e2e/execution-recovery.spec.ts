import { expect, test } from '@playwright/test'
import { mockApi, setupRoute } from './mocks'

test('closed required task blocks execution, removing event recovers and persists the new plan', async ({ page }) => {
  await mockApi(page)
  await page.route('**/api/replan', async (route) => {
    const request = route.request().postDataJSON()
    const closed = request.events.some((event: { type: string }) => event.type === 'close_place')
    const plan = closed ? { status: 'infeasible', alternatives: [], infeasibleReasons: { REQUIRED_TASK_CLOSED: 1 }, warnings: [], suggestions: [] }
      : { status: 'ready', alternatives: [{
        stops: request.tasks.map((task: { id: string; options: { placeId: string }[] }) => ({
          taskId: task.id, placeId: task.options[0].placeId,
          arrivalSeconds: 65000, startSeconds: 65000, finishSeconds: 65060,
          waitSeconds: 0, travelSeconds: 200, travelSourceKind: 'live-api',
          serviceSourceKind: 'user-input', windowSourceKind: 'unknown',
        })), timeline: [], departureSeconds: 64800, finishSeconds: 65400, deadlineSeconds: 70200,
        slackSeconds: 4800, totalTravelSeconds: 500, totalWaitSeconds: 0, totalServiceSeconds: 60,
        totalWalkingM: 300, returnTravelSeconds: 340, returnTravelSourceKind: 'live-api',
      }], infeasibleReasons: {}, warnings: [], suggestions: [] }
    await route.fulfill({ json: { status: plan.status, plan, lockedCompleted: [], appliedEvents: request.events.map((e: { id: string }) => e.id), reason: '' } })
  })
  await setupRoute(page)
  await page.getByRole('button', { name: '买药', exact: true }).click()
  await page.locator('.poi-main').first().click()
  await page.getByRole('button', { name: '加入今天安排', exact: true }).click()
  await page.locator('.plan-bar').click()
  await page.getByRole('button', { name: '规划行程', exact: true }).click()
  await page.getByRole('button', { name: '预演行程' }).click()
  await page.getByText('模拟事件', { exact: true }).click()
  await page.getByRole('combobox', { name: '选择关店目标' }).selectOption('poi-1')
  await page.getByRole('button', { name: '模拟关店', exact: true }).click()
  await page.getByRole('button', { name: '更新后续路线' }).click()
  await expect(page.getByText(/后续路线暂时无法安排/).first()).toBeVisible()
  await expect(page.getByRole('button', { name: '完成', exact: true })).toBeDisabled()
  await page.locator('.plan-panel__event-list button').click()
  await page.getByRole('button', { name: '更新后续路线' }).click()
  await expect(page.getByRole('button', { name: '完成', exact: true })).toBeEnabled()
  await expect(page.locator('.plan-panel__diff')).toContainText('18:10')
  await page.getByRole('combobox', { name: '选择延误目标' }).selectOption('poi-1')
  await page.getByRole('spinbutton', { name: '延误时间（分钟）' }).fill('5')
  await page.getByRole('button', { name: '模拟延误', exact: true }).click()
  const delayed = page.waitForRequest(r => new URL(r.url()).pathname === '/api/replan')
  await page.getByRole('button', { name: '更新后续路线' }).click()
  expect((await delayed).postDataJSON().events[0].delaySeconds).toBe(300)
  await page.getByRole('button', { name: '移除延误事件' }).click()
  await page.getByRole('button', { name: '更新后续路线' }).click()
  const clock = await page.getByRole('textbox', { name: '预演时间' }).inputValue()
  page.once('dialog', dialog => dialog.accept())
  await page.getByRole('button', { name: '跳过', exact: true }).click()
  await expect(page.locator('.plan-panel__runlist')).toContainText('已跳过')
  await expect(page.getByRole('textbox', { name: '预演时间' })).toHaveValue(clock)
  await page.getByRole('button', { name: '恢复', exact: true }).click()
  await page.getByRole('button', { name: '更新后续路线' }).click()
  await page.getByRole('button', { name: '完成', exact: true }).click()
  await expect(page.locator('.plan-panel__runlist')).toContainText('已完成')
  await page.getByRole('button', { name: '关闭今天行程' }).click()
  await expect(page.locator('.plan-bar')).toContainText('18:10')
  await page.reload()
  await expect(page.locator('.plan-bar')).toContainText('18:10')
  await page.getByRole('button', { name: '重新开始' }).click()
  await expect(page.locator('.plan-bar__badge')).toHaveText('0')
})
