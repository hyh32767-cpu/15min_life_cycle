import type { Page, Route } from '@playwright/test'
import { expect } from '@playwright/test'

export async function openPlan(page: Page): Promise<void> {
  const launcher = page.getByRole('button', { name: '查看行程', exact: true })
  if (!await launcher.count()) {
    await page.getByRole('button', { name: '安排路线', exact: true }).click()
  }
  await expect(launcher).toBeVisible()
  await launcher.click()
  await expect(page.getByRole('dialog', { name: '今天安排' })).toBeVisible()
}

export async function openFavorites(page: Page, tab: 'places' | 'routes' = 'places') {
  await page.getByRole('button', { name: '我的收藏', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '我的收藏', exact: true })
  const selector = dialog.getByRole('tab', { name: tab === 'routes' ? /^路线 / : /^地点 / })
  if (await selector.count()) await selector.click()
  return dialog
}

export async function saveRoute(page: Page, name: string): Promise<void> {
  const dialog = await openFavorites(page, 'routes')
  await dialog.locator('.favorite-route-create > summary').click()
  await dialog.getByLabel('收藏路线名称', { exact: true }).fill(name)
  await dialog.getByRole('button', { name: '收藏当前路线', exact: true }).click()
  await expect(dialog.getByRole('status')).toHaveText('路线已收藏')
  await page.getByRole('button', { name: '关闭地点选择', exact: true }).click()
}

export async function useRoute(page: Page, name: string): Promise<void> {
  const dialog = await openFavorites(page, 'routes')
  await dialog.locator('.favorite-route-row').filter({ hasText: name }).getByRole('button').first().click()
}

export async function pickFavorite(page: Page): Promise<void> {
  const dialog = await openFavorites(page)
  await dialog.getByRole('button', { name: '＋ 添加收藏', exact: true }).click()
  await page.getByRole('button', { name: '地图选位置', exact: true }).click()
  await page.locator('.baidu-map__container').click({ position: { x: 80, y: 200 } })
}

function candidate(uid: string, name: string, address: string, lng: number, lat: number) {
  return {
    uid, name, address,
    coord: { lng, lat, crs: 'BD09' },
    source: 'live-api',
  }
}

// Explicitly choose endpoints: the product no longer queries default addresses on mount.
export async function setupRoute(page: Page): Promise<void> {
  await page.goto('/')
  for (const [index, query, name] of [[0, '回龙观', '回龙观小区'], [1, '龙泽园', '龙泽苑']] as const) {
    await page.locator('button.endpoint').nth(index).click()
    await page.getByPlaceholder('搜索任意地点').fill(query)
    await page.getByRole('button', { name: '搜索', exact: true }).click()
    await page.locator('.result').filter({ hasText: name }).first().click()
  }
}

export async function mockApi(page: Page, options: { realMap?: boolean } = {}): Promise<void> {
  // T110/UI-M: E2E 不加载真实百度 SDK；BMap 全局替身只画空容器，不触网。
  if (!options.realMap) await page.addInitScript(() => {
    const w = window as unknown as Record<string, unknown>
    if (!w.BMap) {
      w.BMap = {
        Map: class {
          center = { lng: 116.36, lat: 40.09 }
          zoom = 13
          centerAndZoom(): void {}
          getCenter() { return this.center }
          getZoom() { return this.zoom }
          setViewport(): void {}
          addOverlay(overlay: { content?: string }): void {
            if (!overlay.content) return
            const container = document.querySelector('.baidu-map__container')!
            const element = document.createElement('div')
            element.className = 'BMapLabel'
            element.innerHTML = overlay.content
            const index = container.querySelectorAll('.BMapLabel').length
            element.style.cssText = `position:absolute;left:${(innerWidth > 820 ? 460 : 8) + (index % 5) * 50}px;top:${160 + Math.floor(index / 5) * 40}px;z-index:10;background:white`
            container.append(element)
          }
          removeOverlay(): void {}
          clearOverlays(): void { document.querySelectorAll('.baidu-map__container .BMapLabel').forEach(element => element.remove()) }
          addEventListener(event: string, handler: (event: { point: { lng: number; lat: number } }) => void): void {
            if (event === 'click') document.querySelector('.baidu-map__container')?.addEventListener('click', () => {
              handler({ point: { lng: 116.35, lat: 40.08 } })
            })
          }
          removeEventListener(): void {}
        },
        Point: class {
          lng: number
          lat: number
          constructor(lng: number, lat: number) {
            this.lng = lng
            this.lat = lat
          }
        },
        Marker: class {
          constructor() {}
        },
        Label: class {
          content: string
          constructor(content: string) { this.content = content }
          setStyle(): void {}
        },
        Polyline: class {
          constructor() {}
        },
        Polygon: class {
          constructor() {}
        },
      }
    }
  })
  await page.route('**/api/**', (route: Route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()

    if (method === 'GET' && path === '/api/health') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok', mode: 'live', baiduConfigured: true,
          warnings: [], features: { liveApi: true },
        }),
      })
    }

    if (method === 'GET' && path === '/api/maps/config') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ configured: true, ak: 'e2e-mock-ak', version: '4.0' }),
      })
    }

    if (method === 'POST' && path === '/api/locations/resolve') {
      const { coord } = request.postDataJSON()
      return route.fulfill({ json: { traceId: 'test-resolve', place: { name: '构造验收地址', address: '构造验收地址', coord, source: 'live-api' } } })
    }
    if (method === 'GET' && path.startsWith('/api/locations/poi/')) {
      const uid = decodeURIComponent(path.split('/').at(-1)!)
      return route.fulfill({ json: { traceId: 'mock-detail', place: candidate(uid, '底图真实地点', '底图地点地址', 116.34, 40.08) } })
    }
    if (method === 'GET' && path === '/api/locations/search') {
      const q = url.searchParams.get('q') ?? ''
      const candidates = q.includes('回龙观')
        ? [candidate('hLG', '回龙观小区', '回龙观小区地址', 116.36, 40.09),
           candidate('hLG2', '回龙观小区东门', '回龙观小区东门地址', 116.361, 40.091)]
        : q.includes('龙泽')
          ? [candidate('lZY', '龙泽苑', '龙泽苑地址', 116.33, 40.07),
             candidate('lZY2', '龙泽苑西区', '龙泽苑西区地址', 116.331, 40.071)]
          : [candidate('generic', `${q || '通用'}候选`, `${q || '通用'}候选地址`, 116.34, 40.08),
             candidate('generic2', `${q || '通用'}候选二`, `${q || '通用'}候选二地址`, 116.341, 40.081)]
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ traceId: 'mock', mode: 'live', candidates, warnings: [] }),
      })
    }

    if (method === 'POST' && path === '/api/routes/walking') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          traceId: 'mock', mode: 'live', sourceKind: 'live-api', cacheHit: false,
          route: {
            durationSeconds: 1200,
            distanceM: 1500,
            geometry: [
              { lng: 116.36, lat: 40.09, crs: 'BD09' },
              { lng: 116.33, lat: 40.07, crs: 'BD09' },
            ],
            steps: [],
          },
          warnings: [],
        }),
      })
    }

    if (method === 'POST' && path === '/api/pois/corridor') {
      const body = request.postDataJSON()
      const category = body.category || '药店'
      const origin = body.routeGeometry[0]
      const community = origin.lng === body.routeGeometry.at(-1).lng && origin.lat === body.routeGeometry.at(-1).lat
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          traceId: 'mock', mode: 'live', sourceKind: 'live-api',
          retrieval: {
            queryTerms: [category], category, windows: 1, pages: 1,
            rawCount: 1, uniqueCount: 1, truncated: false, truncationReason: null,
            sourceKind: 'live-api',
          },
          pois: [{
            place: candidate(category === '药店' ? 'poi-1' : `poi-${category}`, `测试${category}`, `测试${category}地址`, community ? origin.lng : 116.345, community ? origin.lat : 40.08),
            distanceToRouteM: 100,
          }],
          warnings: [],
        }),
      })
    }

    if (method === 'POST' && path === '/api/travel-matrix') {
      const body = (request.postDataJSON() ?? {}) as { origins?: unknown[]; destinations?: unknown[] }
      const origins = Array.isArray(body.origins) ? body.origins : []
      const destinations = Array.isArray(body.destinations) ? body.destinations : []
      const cells = origins.flatMap((_, i) => destinations.map((_, j) => ({
        fromIndex: i, toIndex: j,
        durationSeconds: 500, distanceM: 600,
        status: 'ok', sourceKind: 'live-api',
      })))
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          traceId: 'mock', mode: 'live', sourceKind: 'live-api', cacheHit: false,
          cells, warnings: [],
        }),
      })
    }

    if (method === 'POST' && path === '/api/plans') {
      const body = (request.postDataJSON() ?? {}) as {
        tasks?: { id: string; options?: { placeId: string }[] }[]
      }
      const tasks = Array.isArray(body.tasks) ? body.tasks : []
      const stops = tasks.flatMap((task) => (task.options ?? []).slice(0, 1).map((option) => ({
        taskId: task.id, placeId: option.placeId,
        arrivalSeconds: 100, startSeconds: 100, finishSeconds: 200, waitSeconds: 0,
        travelSeconds: 100, travelSourceKind: 'live-api',
        serviceSourceKind: 'user-input', windowSourceKind: 'unknown',
      })))
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ready',
          alternatives: [{
            stops, timeline: [],
            departureSeconds: 0, finishSeconds: 500, deadlineSeconds: 3600,
            slackSeconds: 100,
            totalTravelSeconds: 300, totalWaitSeconds: 0, totalServiceSeconds: 200,
            totalWalkingM: 300, returnTravelSeconds: 100, returnTravelSourceKind: 'live-api',
          }],
          infeasibleReasons: {}, warnings: [], suggestions: [],
        }),
      })
    }

    if (method === 'POST' && path === '/api/pois/corridor/evidence') {
      const body = request.postDataJSON()
      return route.fulfill({ json: { traceId: 'mock-evidence', mode: 'live', sourceKind: 'derived',
        thresholdSeconds: body.thresholdSeconds, pairsUsed: 0, warnings: [], samples: [], bestAccess: null,
        evidence: { thresholdSeconds: body.thresholdSeconds, inboundReachableIndices: [], outboundReachableIndices: [],
          missingInboundIndices: [], missingOutboundIndices: [], symmetricAssumed: false, directionalFeasible: false } } })
    }
    if (method === 'POST' && path === '/api/community/coverage') {
      const body = request.postDataJSON()
      const covered = (times: { fromGrid: string; toFacility: string; status: string; durationSeconds: number | null }[], facilities: string[]) =>
        Object.fromEntries(body.gridIds.map((id: string) => [id, times.some(t => t.fromGrid === id && facilities.includes(t.toFacility)
          && t.status === 'ok' && t.durationSeconds != null && t.durationSeconds <= body.thresholdSeconds)]))
      const coverage = covered(body.times, body.facilityIds)
      const count = Object.values(coverage).filter(Boolean).length
      const after = covered([...body.times, ...(body.newFacilityTimes || [])], [...body.facilityIds, body.newFacilityId])
      return route.fulfill({ json: { coverage, coveredCount: count, totalGrids: body.gridIds.length,
        blindGrids: body.gridIds.filter((id: string) => !coverage[id]),
        ...(body.newFacilityId ? { delta: { before: count, after: Object.values(after).filter(Boolean).length } } : {}) } })
    }
    if (method === 'POST' && path === '/api/isochrones') {
      const body = request.postDataJSON()
      return route.fulfill({ json: { taskId: 'mock-iso', status: 'complete', thresholdSeconds: body.thresholdSeconds,
        origin: { ...body.origin, crs: 'BD09' }, radiiM: Object.fromEntries([0,45,90,135,180,225,270,315].map(b => [b, 500])),
        failedBearings: [], skippedBearings: [], pairsUsed: 0, cacheHit: false, mode: 'live', sourceKind: 'derived',
        algorithmVersion: 'constructed-e2e', warnings: [], report: { effectiveBearings: 8, approxAreaM2: 1000000 } } })
    }
    // 缺 mock 必须显式失败，绝不放行到真实后端或百度服务。
    return route.fulfill({ status: 501, json: { error: { code: 'MOCK_NOT_CONFIGURED', message: `缺少测试响应：${method} ${path}` } } })
  })
}
