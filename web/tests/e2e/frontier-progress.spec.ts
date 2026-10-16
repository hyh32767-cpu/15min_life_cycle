import { expect, test } from '@playwright/test'
import { mockApi } from './mocks'

test('mobile frontier shows each batch and separate fitted lines before the full result', async ({ page }, testInfo) => {
  await page.setViewportSize({width:390,height:844})
  await mockApi(page)
  let phase=0
  let center={lng:116.4,lat:39.9,crs:'BD09'}
  let prematureFacilities=false
  const line=()=>[center,{...center,lng:center.lng+.005},{...center,lat:center.lat+.005}]
  const response=(seconds=900)=>({taskId:'grid-progress',thresholdSeconds:seconds,origin:center,
    algorithmVersion:'grid-frontier-disk-v2',status:phase===2?'complete':'partial',
    backgroundStatus:phase===2?'completed':'running',radiiM:{},failedBearings:[],skippedBearings:[],warnings:[],cacheHit:false,
    pairsUsed:phase===0?50:100,expiresAt:new Date(Date.now()+300000).toISOString(),
    reconstruction:{method:'grid-frontier-disk-v2',sampleCount:100,contours:phase?[line()]:[],classificationBoundary:'grid-frontier-approximation',clipMarginM:0,note:''},
    frontier:{phase:phase===2?'finished':'boundary',halfM:1000,radiusM:1000,domainShape:'disk',spacingM:100,batchCount:phase+1,previewOnly:true,
      previewContours:phase===2?[]:[line()],samples:Array.from({length:phase===0?50:100},(_,i)=>({x:i,y:1000,seconds:1000,state:'outside',coord:{...center,lng:center.lng+i*.0001}})),
      polygons:phase===2?[{outer:line(),holes:[]}]:[],fills:phase===2?[line()]:[]},report:{approxAreaM2:phase===2?100000:null}})
  await page.route('**/api/isochrones',route=>{
    const req=route.request().postDataJSON()
    expect(req.frontier).toBe(true)
    center=req.origin
    return route.fulfill({json:response(req.thresholdSeconds)})
  })
  await page.route('**/api/isochrones/grid-progress/status',route=>route.fulfill({json:response()}))
  page.on('request',req=>{if(req.url().includes('/api/pois/corridor')&&phase<2)prematureFacilities=true})
  await page.goto('/community')
  await expect(page.locator('.shell__search')).toBeVisible()
  await page.evaluate(()=>{
    const w=window as unknown as {BMap:{Polyline:unknown};frontierLines:Record<string,unknown>[]}
    w.frontierLines=[]
    w.BMap.Polyline=class {constructor(_p:unknown,options:Record<string,unknown>){w.frontierLines.push(options)}}
  })
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill('回龙观')
  await page.getByRole('button',{name:'搜索',exact:true}).click()
  await page.getByRole('button',{name:'选择 回龙观小区',exact:true}).click()
  const loading=page.locator('.map-circle-loading')
  await expect(loading).toContainText('已测 50 个位置')
  await expect.poll(()=>page.evaluate(()=>(window as unknown as {frontierLines:Record<string,unknown>[]}).frontierLines.some(s=>s.strokeColor==='#3975ed'&&s.strokeOpacity===.8))).toBe(true)
  expect(await page.evaluate(()=>(window as unknown as {frontierLines:Record<string,unknown>[]}).frontierLines.some(s=>s.strokeColor==='#8a9ebf'&&s.strokeStyle==='solid'))).toBe(true)
  await page.screenshot({path:testInfo.outputPath('frontier-first-batch.png')})
  phase=1
  await expect(loading).toContainText('已测 100 个位置')
  expect(prematureFacilities).toBe(false)
  await page.screenshot({path:testInfo.outputPath('frontier-second-batch.png')})
  phase=2
  await expect(loading).toHaveCount(0)
  await expect(page.locator('.status-line')).toContainText('已完成')
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
