import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

test('service selection is explicit, synonyms share one query and public facilities remain separate', async ({ page }) => {
  await mockApi(page)
  await page.route('**/api/pois/corridor', route => {
    const input = route.request().postDataJSON()
    const related: Record<string, { name: string; tags: string[] }> = {
      托育托管: { name: '三一国际儿童学院', tags: ['教育培训;幼儿园'] },
      养老: { name: '街道老年活动中心', tags: ['文化活动'] },
      菜市场: { name: '社区生鲜超市', tags: ['购物;超市'] },
    }
    const place = related[input.category]
    if (!place) return route.fallback()
    return route.fulfill({ json: {
      traceId: 'kindergarten-test', mode: 'live', sourceKind: 'live-api', warnings: [],
      retrieval: { truncated: false, rawCount: 1, uniqueCount: 1 },
      pois: [{ place: { uid: `related-${input.category}`, ...place,
        coord: input.routeGeometry[0], source: 'live-api' }, distanceToRouteM: 0 }],
    } })
  })
  const searches: { category: string; queryTerms: string[] }[] = []
  page.on('request', r => { if (r.url().endsWith('/api/pois/corridor')) searches.push(r.postDataJSON()) })
  await page.goto('/community')
  await page.getByText('选择服务 · 已选 7 项', { exact: true }).click()
  await expect(page.getByRole('group', { name: '基本便民' })).toBeVisible()
  await expect(page.getByRole('group', { name: '品质生活' })).toBeVisible()
  await expect(page.getByRole('group', { name: '公共配套' })).toBeVisible()
  await expect(page.getByRole('checkbox')).toHaveCount(29)
  await page.getByRole('checkbox', { name: '小学', exact: true }).check()
  expect(searches).toEqual([])
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill('回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()

  await expect(page.getByText('8/8 已完成')).toBeVisible()
  for (const category of ['托育托管', '养老', '菜市场']) {
    const card = page.locator('.category-item').filter({ hasText: category })
    await expect(card).toContainText('100%')
    await expect(card).toContainText('圈内 1 家')
  }
  expect(searches.find(s => s.category === '菜市场')?.queryTerms).toEqual(['菜市场$农贸市场$农副产品市场$菜场$生鲜$蔬菜店$超市'])
  expect(searches.find(s => s.category === '托育托管')?.queryTerms).toEqual(['托育$托儿所$幼儿托管$幼儿园'])
  expect(searches.every(s => s.queryTerms.length === 1)).toBe(true)
  expect(searches.some(s => s.category === '小学')).toBe(true)
  expect(searches.some(s => s.category === '综合超市')).toBe(false)
  await page.getByRole('checkbox', { name: '综合超市', exact: true }).check()
  await expect(page.locator('.scorecard')).toHaveCount(0)
  expect(searches).toHaveLength(8)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('brand without service evidence stays unknown; genuine API category tags resolve it', async ({ page }) => {
  await mockApi(page)
  let withTags = false
  await page.route('**/api/pois/corridor', route => {
    const origin = route.request().postDataJSON().routeGeometry[0]
    return route.fulfill({ json: { pois: [{ place: { uid: 'brand', name: '同仁堂', address: '幼儿园附近',
      coord: origin, source: 'synthetic-assumption', tags: withTags ? ['医疗;药店'] : [] }, distanceToRouteM: 0 }],
    retrieval: { truncated: false }, warnings: [] } })
  })
  await page.goto('/community')
  await page.getByText('选择服务 · 已选 7 项', { exact: true }).click()
  for (const name of ['便利店', '菜市场', '早餐', '小修小补', '养老', '托育托管']) {
    await page.getByRole('checkbox', { name, exact: true }).uncheck()
  }
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill('回龙观')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByRole('button', { name: '选择 回龙观小区', exact: true }).click()
  await expect(page.getByText('0/1 已完成')).toBeVisible()
  await expect(page.locator('.scorecard__ring strong')).toHaveText('—')
  await expect(page.locator('.summary')).toHaveCount(0)
  const incompleteDownload = page.waitForEvent('download')
  if (!await page.locator('.community-tools').evaluate((el: HTMLDetailsElement) => el.open)) await page.locator('.community-tools > summary').click()
  await page.getByRole('button', { name: '导出报告', exact: true }).click()
  const incompleteStream = await (await incompleteDownload).createReadStream()
  let incompleteContent = ''
  for await (const chunk of incompleteStream!) incompleteContent += chunk.toString()
  const incomplete = JSON.parse(incompleteContent)
  expect(incomplete.schemaVersion).toBe('life-circle-report-v2')
  expect(incomplete.serviceMatching.version).toBe('broad-related-v1')
  expect(incomplete.status).toBe('partial')
  expect(incomplete.summary.averageCoveragePercent).toBeNull()
  expect(incomplete.services[0].coveragePercent).toBeNull()
  expect(incomplete.services[0].baseline).toBeNull()
  expect(incomplete.serviceCatalog.find((service: { id: string }) => service.id === 'primary-school').selection).toBe('not-selected')
  withTags = true
  await page.getByRole('button', { name: '设施社区评分' }).click()
  await expect(page.getByText('1/1 已完成')).toBeVisible()
  await expect(page.locator('.scorecard__ring strong')).toHaveText('100')
  await expect(page.locator('.coverage-radar')).toHaveCount(0)
  const completeDownload = page.waitForEvent('download')
  if (!await page.locator('.community-tools').evaluate((el: HTMLDetailsElement) => el.open)) await page.locator('.community-tools > summary').click()
  await page.getByRole('button', { name: '导出报告', exact: true }).click()
  const completeStream = await (await completeDownload).createReadStream()
  let completeContent = ''
  for await (const chunk of completeStream!) completeContent += chunk.toString()
  const complete = JSON.parse(completeContent)
  expect(complete.status).toBe('complete')
  expect(complete.summary.averageCoveragePercent).toBe(100)
  expect(complete.services[0].facilities[0].tags).toEqual(['医疗;药店'])
  expect(complete.services[0].measuredTimes.length).toBeGreaterThan(9)
  expect(complete.scope.samples.length).toBeGreaterThan(9)
  expect(complete.isochrone.thresholdSeconds).toBe(900)
  expect(complete.charts.bars).toHaveLength(1)
})
