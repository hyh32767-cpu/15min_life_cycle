import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

test('favorites has an explicit empty state; adding persists and can select a circle center', async ({ page }) => {
  await mockApi(page)
  let circles = 0
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/isochrones') circles++ })
  await page.goto('/community')
  await page.getByRole('button', { name: '我的收藏', exact: true }).click()
  const favorites = page.getByRole('dialog', { name: '我的收藏', exact: true })
  await expect(favorites.getByText('还没有收藏地点', { exact: true })).toBeVisible()
  await expect(favorites.getByRole('searchbox')).toHaveCount(0)
  await favorites.getByRole('button', { name: '＋ 添加收藏', exact: true }).click()
  const add = page.getByRole('dialog', { name: '添加收藏', exact: true })
  await expect(add.getByRole('textbox', { name: '搜索城市', exact: true })).toHaveCount(0)
  const searchRequest = page.waitForRequest(request => new URL(request.url()).pathname === '/api/locations/search')
  await add.getByRole('searchbox').fill('图书馆')
  await add.getByRole('button', { name: '搜索', exact: true }).click()
  expect(new URL((await searchRequest).url()).searchParams.get('city')).toBe('全国')
  await add.getByRole('button', { name: '收藏 图书馆候选', exact: true }).click()
  await expect(favorites.getByRole('heading', { name: '我的收藏' })).toBeVisible()
  await expect(favorites.getByRole('button', { name: '图书馆候选 图书馆候选地址', exact: true })).toBeVisible()
  await expect(favorites.getByRole('status')).toContainText('已收藏')
  await page.getByRole('button', { name: '关闭地点选择', exact: true }).click()
  await page.reload()
  await page.getByRole('button', { name: '我的收藏', exact: true }).click()
  await favorites.getByRole('button', { name: '图书馆候选 图书馆候选地址', exact: true }).click()
  await expect(page.locator('.origin-name')).toHaveText('图书馆候选')
  await expect(favorites).toHaveCount(0)
  await expect(page.getByText('7/7 已完成', { exact: true })).toBeVisible()
  expect(circles).toBe(3)
})

test('existing saved places appear immediately without opening search or querying APIs', async ({ page }) => {
  await mockApi(page)
  await page.addInitScript(() => localStorage.setItem('shunshou-places-v1', JSON.stringify({ places: [{
    id: 'favorite-fixture', label: '常去的书店', createdAt: '2026-10-15T00:00:00Z',
    place: { uid: 'bookshop', name: '构造书店', address: '构造验收地址',
      coord: { lng: 116.36, lat: 40.09, crs: 'BD09' }, source: 'user-input' },
  }] })))
  let searches = 0
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/locations/search') searches++ })
  await page.goto('/community')
  await page.getByRole('button', { name: '我的收藏', exact: true }).click()
  const favorites = page.getByRole('dialog', { name: '我的收藏', exact: true })
  await expect(favorites.getByText('1 个收藏地点', { exact: true })).toBeVisible()
  await expect(favorites.getByRole('button', { name: '常去的书店 构造验收地址', exact: true })).toBeVisible()
  await expect(favorites.getByRole('searchbox')).toHaveCount(0)
  await page.getByRole('button', { name: '关闭地点选择', exact: true }).click()
  await expect(page.locator('.shell__saved')).toBeFocused()
  expect(searches).toBe(0)
})

async function seedSharedFavorites(page: import('@playwright/test').Page, withRoute: boolean) {
  await page.addInitScript((includeRoute: boolean) => {
    const start = { uid: 'shared-start', name: '构造书店', address: '书店地址', coord: { lng: 116.36, lat: 40.09, crs: 'BD09' }, source: 'user-input' }
    const end = { uid: 'shared-end', name: '构造药店', address: '药店地址', coord: { lng: 116.34, lat: 40.08, crs: 'BD09' }, source: 'user-input' }
    if (!localStorage.getItem('shunshou-places-v1')) localStorage.setItem('shunshou-places-v1', JSON.stringify({ places: [
      { id: 'shared-a', label: '常去书店', place: start }, { id: 'shared-b', label: '常去药店', place: end },
    ] }))
    if (!localStorage.getItem('shunshou-route-presets-v1')) localStorage.setItem('shunshou-route-presets-v1', JSON.stringify({ presets: includeRoute ? [{
      id: 'old-shared-route', name: '原有收藏路线', company: start, home: end,
      companyQuery: start.name, homeQuery: end.name, waypointTasks: [], visitOrder: [],
    }] : [] }))
  }, withRoute)
}

test('life circle shows places only while commute retains shared routes and places', async ({ page }) => {
  await mockApi(page)
  await seedSharedFavorites(page, true)
  let circles = 0
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/isochrones') circles++ })
  await page.goto('/community')
  await page.getByRole('button', { name: '我的收藏', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '我的收藏', exact: true })
  await expect(dialog.getByRole('button', { name: '常去书店 书店地址', exact: true })).toBeVisible()
  await expect(dialog.getByRole('tab')).toHaveCount(0)
  await expect(dialog.locator('.favorite-routes')).toHaveCount(0)
  await page.getByRole('button', { name: '关闭地点选择', exact: true }).click()
  await page.getByRole('link', { name: '顺路办事', exact: true }).click()
  await page.getByRole('button', { name: '我的收藏', exact: true }).click()
  await dialog.getByRole('tab', { name: '路线 1', exact: true }).click()
  await dialog.getByRole('button', { name: '原有收藏路线 构造书店 → 构造药店', exact: true }).click()
  await expect(page).toHaveURL('/')
  await expect(page.locator('.endpoint').first()).toContainText('构造书店')
  await expect(page.locator('.endpoint').nth(1)).toContainText('构造药店')
  await expect(page.getByRole('button', { name: '我的地点', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '我的路径', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '我的收藏', exact: true }).click()
  await dialog.getByRole('tab', { name: '地点 2', exact: true }).click()
  await dialog.getByRole('button', { name: '生活圈中心', exact: true }).click()
  await dialog.getByRole('button', { name: '常去药店 药店地址', exact: true }).click()
  await expect(page).toHaveURL(/\/community$/)
  await expect(page.locator('.origin-name')).toHaveText('构造药店')
  await expect(page.getByText('7/7 已完成', { exact: true })).toBeVisible()
  expect(circles).toBe(3)
})

test('a route created from shared favorite places persists without querying routes', async ({ page }) => {
  await mockApi(page)
  await seedSharedFavorites(page, false)
  let routeCalls = 0
  page.on('request', request => { if (new URL(request.url()).pathname === '/api/routes/walking') routeCalls++ })
  await page.goto('/')
  await page.getByRole('button', { name: '我的收藏', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '我的收藏', exact: true })
  await dialog.getByRole('tab', { name: '路线 0', exact: true }).click()
  await dialog.locator('.favorite-route-create > summary').click()
  await dialog.getByLabel('收藏路线名称', { exact: true }).fill('书店到药店')
  await dialog.getByLabel('收藏路线起点', { exact: true }).selectOption('shared-a')
  await dialog.getByLabel('收藏路线终点', { exact: true }).selectOption('shared-b')
  await dialog.getByRole('button', { name: '从收藏地点创建路线', exact: true }).click()
  await expect(dialog.getByRole('tab', { name: '路线 1', exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: '书店到药店 构造书店 → 构造药店', exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: '我的收藏', exact: true }).click()
  await dialog.getByRole('tab', { name: '路线 1', exact: true }).click()
  await expect(dialog.getByRole('button', { name: '书店到药店 构造书店 → 构造药店', exact: true })).toBeVisible()
  expect(routeCalls).toBe(0)
})
