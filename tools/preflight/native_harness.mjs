// 独立原生窗口验收：构造数据、零百度业务外呼，不能当作 live 成功证据。
import { chromium } from '../../web/node_modules/playwright/index.mjs'
import { mockApi } from '../../web/tests/e2e/mocks.ts'

const browser = await chromium.launch({ headless: false, args: ['--window-size=500,920'] })
const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
const page = await context.newPage()
const realMap = process.env.NATIVE_REAL_MAP === '1'
await mockApi(page, { realMap })
if (realMap) await page.route('**/api/maps/config', async route => {
  const response = await fetch('http://127.0.0.1:18080/api/maps/config')
  await route.fulfill({ json: await response.json() })
})
await page.addInitScript(realMap => {
  navigator.geolocation.getCurrentPosition = success => success({ coords: { longitude: 116.36, latitude: 40.09, accuracy: 100 }, timestamp: Date.now() })
  addEventListener('DOMContentLoaded', () => {
    document.title = '验收数据 · 顺手'
    const badge = document.createElement('div')
    badge.textContent = realMap ? '真实底图 / 构造业务数据 / 零业务外呼' : '交互验收：构造数据 / 零业务外呼'
    badge.style.cssText = 'position:fixed;top:0;right:0;z-index:9999;background:#fff3cd;font-size:11px;padding:3px;color:#7c4a03'
    document.body.append(badge)
  })
}, realMap)
await page.route('**/api/pois/corridor', async route => {
  const body = route.request().postDataJSON()
  if (body.routeGeometry[0].lng !== body.routeGeometry.at(-1).lng || body.routeGeometry[0].lat !== body.routeGeometry.at(-1).lat) return route.fallback()
  const origin = body.routeGeometry[0]
  const pois = Array.from({ length: process.env.NATIVE_ELDERLY_EMPTY === '1' && body.category === '养老' ? 0 : 6 }, (_, i) => ({ place: { uid: `${body.category || '设施'}-${i}`,
    name: `${body.category || '设施'}验收点${i + 1}`, address: '构造验收地址',
    coord: { lng: origin.lng + (i < 5 ? i * .0002 : -.0005), lat: origin.lat, crs: 'BD09' }, source: 'synthetic-assumption' }, distanceToRouteM: 100 + i }))
  await route.fulfill({ json: { traceId: 'native-constructed', mode: 'live', sourceKind: 'derived', cacheHit: false,
    pois, retrieval: { queryTerms: body.queryTerms, category: body.category, windows: 1, pages: 1,
      rawCount: pois.length, uniqueCount: pois.length, truncated: pois.length > 0, truncationReason: pois.length ? 'page_budget' : null, sourceKind: 'derived' }, warnings: [] } })
})
await page.route('**/api/travel-matrix', async route => {
  const body = route.request().postDataJSON()
  const cells = body.origins.flatMap((origin, i) => body.destinations.map((dest, j) => ({ fromIndex: i, toIndex: j,
    durationSeconds: origin.lng < 116.36 && origin.lat < 40.09 && dest.lng >= 116.37 ? 1200 : 300,
    distanceM: 400, status: 'ok', sourceKind: 'derived' })))
  await route.fulfill({ json: { traceId: 'native-constructed', mode: 'live', sourceKind: 'derived', cacheHit: false, cells, warnings: [] } })
})
await page.route('**/api/community/coverage', async route => {
  const body = route.request().postDataJSON()
  const covered = times => Object.fromEntries(body.gridIds.map(id => [id, times.some(t => t.fromGrid === id && t.status === 'ok' && t.durationSeconds <= body.thresholdSeconds)]))
  const baseline = covered(body.times)
  const after = covered([...body.times, ...(body.newFacilityTimes || [])])
  await route.fulfill({ json: { coverage: baseline, coveredCount: Object.values(baseline).filter(Boolean).length,
    totalGrids: body.gridIds.length, blindGrids: body.gridIds.filter(id => !baseline[id]),
    ...(body.newFacilityId ? { delta: { before: Object.values(baseline).filter(Boolean).length, after: Object.values(after).filter(Boolean).length } } : {}) } })
})
await page.route('**/api/route-bands', async route => {
  const body = route.request().postDataJSON()
  await route.fulfill({ json: { routeHash: 'native-constructed-band', thresholdSeconds: body.thresholdSeconds,
    status: 'unknown', completeCount: 0, nodes: [body.routeGeometry[0]].map((origin, index) => ({ origin, index, status: 'partial', cached: true, warnings: [] })),
    fills: [], boundaries: [], maxGapM: 0, cacheHit: true, cost: { liveRequests: 0, cacheHits: 0, pairs: 0, livePairs: 0 } } })
})
await page.route('**/api/explore/check', async route => {
  const body = route.request().postDataJSON()
  await route.fulfill({ json: { results: body.candidates.map(candidate => {
    const leg = body.legs.find(leg => leg.candidateId === candidate.placeId)
    const known = leg?.statusStart === 'ok' && leg?.statusReturn === 'ok'
    const total = known ? leg.durationSecondsStart + leg.durationSecondsReturn + body.serviceSeconds + body.waitSeconds : null
    return { placeId: candidate.placeId, totalSeconds: total, feasible: total != null && total <= body.budgetSeconds,
      reason: total == null ? 'OD_UNAVAILABLE' : total > body.budgetSeconds ? 'OVER_BUDGET' : '' }
  }) } })
})
await page.goto('http://127.0.0.1:5173/community')
console.log('Native harness ready: constructed data, no business network requests.')
await new Promise(resolve => browser.on('disconnected', resolve))
