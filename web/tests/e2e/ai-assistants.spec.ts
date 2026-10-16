import { expect, test } from '@playwright/test'
import { mockApi, setupRoute } from './mocks'

test('route assistant applies real planner selections to editable waypoints and keeps time limit',async({page},testInfo)=>{
  await page.setViewportSize({width:390,height:844})
  await mockApi(page)
  await page.route('**/api/route/intent',route=>route.fulfill({json:{tasks:[{categoryId:'药店',serviceMinutes:3},{categoryId:'快递',serviceMinutes:2}],totalMinutes:30,extraMinutes:null,keepOrder:true}}))
  const plans: {deadlineSeconds:number;departureSeconds:number;tasks:{id:string;options:{placeId:string;serviceSeconds:number}[]}[]}[]=[]
  let failNext=false
  await page.route('**/api/plans',async route=>{
    const body=route.request().postDataJSON();plans.push(body)
    if(failNext) return route.fulfill({json:{status:'infeasible',alternatives:[],infeasibleReasons:{TIME_LIMIT:1},warnings:[],suggestions:[]}})
    const stops=body.tasks.map((task:{id:string;options:{placeId:string;serviceSeconds:number}[]},i:number)=>({
      taskId:task.id,placeId:task.options[0]!.placeId,arrivalSeconds:body.departureSeconds+60+i*300,
      startSeconds:body.departureSeconds+60+i*300,finishSeconds:body.departureSeconds+60+i*300+task.options[0]!.serviceSeconds,
      waitSeconds:0,travelSeconds:60,travelSourceKind:'live-api',serviceSourceKind:'user-input',windowSourceKind:'unknown'}))
    await route.fulfill({json:{status:'ready',alternatives:[{stops,timeline:[],departureSeconds:body.departureSeconds,
      finishSeconds:body.departureSeconds+900,deadlineSeconds:body.deadlineSeconds,slackSeconds:900,totalTravelSeconds:180,
      totalWaitSeconds:0,totalServiceSeconds:300,totalWalkingM:200,returnTravelSeconds:60,returnTravelSourceKind:'live-api'}],
      infeasibleReasons:{},warnings:[],suggestions:[]}})
  })
  await setupRoute(page)
  const assistant=page.getByRole('region',{name:'智能安排路线'})
  await assistant.getByRole('textbox',{name:'办事需求与时间'}).fill('先买药再取快递，三十分钟内到终点')
  await assistant.getByRole('button',{name:'帮我安排'}).click()
  await expect(assistant.getByRole('status')).toContainText('途经点已同步')
  await expect(page.locator('[data-waypoint-id]')).toHaveCount(2)
  expect(plans[0]!.deadlineSeconds-plans[0]!.departureSeconds).toBeLessThanOrEqual(1800)
  expect(plans[0]!.tasks.map(task=>task.options[0]!.serviceSeconds)).toEqual([180,120])
  await assistant.getByRole('button',{name:'帮我安排'}).click()
  await expect.poll(()=>plans.length).toBe(2)
  await expect(assistant.getByRole('status')).toContainText('途经点已同步')
  await expect(page.locator('[data-waypoint-id]')).toHaveCount(2)
  await page.getByRole('button',{name:'调整顺序',exact:true}).click()
  await page.getByRole('button',{name:/下移途经点/}).first().click()
  await page.getByRole('button',{name:'安排路线',exact:true}).click()
  await expect.poll(()=>plans.length).toBe(3)
  expect(plans[2]!.deadlineSeconds).toBe(plans[0]!.deadlineSeconds)
  expect(plans[2]!.tasks[0]!.options[0]!.serviceSeconds).toBe(120)
  failNext=true
  await assistant.getByRole('button',{name:'帮我安排'}).click()
  await expect(assistant.getByRole('alert')).toBeVisible()
  await expect(page.locator('[data-waypoint-id]')).toHaveCount(2)
  await page.getByRole('button',{name:'调整顺序',exact:true}).click()
  await page.getByRole('button',{name:/删除途经点/}).first().click()
  await expect(page.locator('[data-waypoint-id]')).toHaveCount(1)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({path:testInfo.outputPath('editable-ai-route.png')})
})

test('community insight is explicit, separate from score, and clears on category changes',async({page})=>{
  await mockApi(page)
  let calls=0
  await page.route('**/api/community/insight',route=>{calls++;return route.fulfill({json:{summary:'本次养老服务覆盖偏弱，可优先关注。',scope:'仅针对本次检索到的设施和采样点。',score:0,cacheHit:false}})})
  await page.goto('/community')
  await page.locator('.shell__search').click()
  await page.getByRole('searchbox').fill('回龙观')
  await page.getByRole('button',{name:'搜索',exact:true}).click()
  await page.getByRole('button',{name:'选择 回龙观小区',exact:true}).click()
  await expect(page.getByText('7/7 已完成',{exact:true})).toBeVisible()
  const before=await page.locator('.scorecard__ring strong').innerText()
  expect(calls).toBe(0)
  const insight=page.getByRole('region',{name:'社区解读'})
  await insight.getByRole('button',{name:'看看建议'}).click()
  await expect(insight).toContainText('养老服务覆盖偏弱')
  await expect(page.locator('.scorecard__ring strong')).toHaveText(before)
  await expect(insight).toContainText('仅针对本次')
  await page.getByText('选择服务 · 已选 7 项',{exact:true}).click()
  await page.getByRole('checkbox',{name:'综合超市',exact:true}).check()
  await expect(page.getByText('本次养老服务覆盖偏弱，可优先关注。',{exact:true})).toHaveCount(0)
})
