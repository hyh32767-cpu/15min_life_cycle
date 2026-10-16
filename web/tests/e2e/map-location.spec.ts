import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })

test('side location button converts GPS and centers map without changing circle or querying business APIs', async ({ page }) => {
  await mockApi(page)
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition(success: (value: { coords: { longitude: number; latitude: number } }) => void) {
      success({ coords: { longitude: 116.36, latitude: 40.09 } })
    } } })
    window.addEventListener('DOMContentLoaded', () => {
      const w = window as unknown as { BMap: { Convertor?: unknown }; coordinateConversion?: number[] }
      w.BMap.Convertor = class {
        translate(_points: unknown[], from: number, to: number, callback: (result: { status: number; points: { lng: number; lat: number }[] }) => void) {
          w.coordinateConversion = [from, to]
          callback({ status: 0, points: [{ lng: 116.372, lat: 40.097 }] })
        }
      }
    })
  })
  const requests: string[] = []
  page.on('request', r => { if (/\/api\/(isochrones|routes\/walking|travel-matrix|pois\/|locations\/)/.test(r.url())) requests.push(r.url()) })
  await page.goto('/community')
  const locate = page.getByRole('button', { name: '定位到当前位置', exact: true })
  await expect(locate).toBeEnabled()
  await locate.click()
  await expect(page.locator('.baidu-map__container').getByRole('button', { name: '当前位置', exact: true })).toBeVisible()
  await expect(page.locator('.origin-name')).toHaveText('搜索社区、地标或地址')
  expect(await page.evaluate(() => (window as unknown as { coordinateConversion: number[] }).coordinateConversion)).toEqual([1, 5])
  expect(requests).toEqual([])
  await expect(locate).toHaveAttribute('aria-busy', 'false')
})

test('denied and insecure location give actionable messages without pretending to locate', async ({ page }) => {
  await mockApi(page)
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition(_success: unknown, failure: (value: { code: number }) => void) { failure({ code: 1 }) } } })
  })
  await page.goto('/community')
  const locate = page.getByRole('button', { name: '定位到当前位置', exact: true })
  await expect(locate).toBeEnabled()
  await locate.click()
  await expect(page.getByRole('alert').filter({ hasText: '定位权限未开启' })).toBeVisible()
  await expect(locate).toBeEnabled()
  await page.evaluate(() => Object.assign(navigator.geolocation, { getCurrentPosition(_success: unknown, failure: (value: { code: number }) => void) { failure({ code: 3 }) } }))
  await locate.click()
  await expect(page.getByRole('alert').filter({ hasText: '定位超时' })).toBeVisible()
  await page.evaluate(() => Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true }))
  await locate.click()
  await expect(page.getByRole('alert').filter({ hasText: '定位需要 HTTPS' })).toBeVisible()
  await expect(page.locator('.baidu-map__container').getByRole('button', { name: '当前位置', exact: true })).toHaveCount(0)
})
