<script setup lang="ts">
import { computed, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import { useAppStore } from '@/stores/app'
import { useCommuteStore } from '@/stores/commute'
import { usePlanStore } from '@/stores/plan'
import { useExecutionStore } from '@/stores/execution'
import { useMapInteractionStore } from '@/stores/mapInteraction'
import { commuteCategoryQueries, commuteCategoryLabel } from '@/domain/commuteCategories'
import { parseClockToSeconds, formatClockSeconds } from '@/domain/time'
import type { PlaceRef } from '@/domain/types'
import { resolveOpeningWindows } from '@/domain/openingHours'
const app=useAppStore(), commute=useCommuteStore(), plan=usePlanStore(), execution=useExecutionStore(), map=useMapInteractionStore()
const text=ref(''), busy=ref(false), message=ref(''), error=ref('')
let controller: InstanceType<typeof window.AbortController> | null=null
const scope=computed(()=>JSON.stringify([commute.company?.coord,commute.home?.coord,commute.route?.route.geometry,commute.departureClock,commute.deadlineClock]))
function cancel(): void { controller?.abort();controller=null;busy.value=false;message.value='';error.value='' }
watch(scope,cancel,{flush:'sync'})
onBeforeUnmount(cancel);onDeactivated(cancel)
const copy=<T,>(value:T):T=>JSON.parse(JSON.stringify(value)) as T
async function arrange(): Promise<void> {
  if (busy.value || plan.loading || commute.loading || !commute.route || !text.value.trim()) return
  const current=new window.AbortController();controller=current;busy.value=true;error.value='';message.value=''
  const route=commute.route, originalScope=scope.value, originalTasks=JSON.stringify(plan.tasks)
  const unchanged=()=>controller===current && originalScope===scope.value
  const capture=()=>copy({tasks:plan.tasks,visitOrder:plan.visitOrder,timeLimitSeconds:plan.timeLimitSeconds,result:plan.result,
    planRouteGeometry:plan.planRouteGeometry,legGeometries:plan.legGeometries,travelTimes:plan.travelTimes,
    nodeCoords:plan.nodeCoords,nodePlaceNames:plan.nodePlaceNames,error:plan.error,notice:plan.notice})
  let snapshot: ReturnType<typeof capture> | null=null
  let appliedTasks=''
  try {
    if (!app.provider.parseRouteIntent) throw new Error('智能安排暂不可用')
    const intent=await app.provider.parseRouteIntent(text.value.trim(),current.signal)
    if (!unchanged()) return
    const matching=(category:string)=>plan.tasks.find(task=>task.category===category || task.category===commuteCategoryLabel(category))
    if (plan.tasks.length+intent.tasks.filter(task=>!matching(task.categoryId)).length>5) throw new Error('已有途经点会保留，总共最多安排5处，请先删减一些')
    const choices: {category: string;places: PlaceRef[];minutes: number;reuseId?:string}[]=[]
    for (const task of intent.tasks) {
      if (!unchanged()) return
      const priorTask=matching(task.categoryId)
      if (priorTask) {
        choices.push({category:task.categoryId,places:[],minutes:task.serviceMinutes??((priorTask.options[0]?.serviceSeconds??0)/60),reuseId:priorTask.id})
        continue
      }
      let candidates: PlaceRef[]
      if (task.categoryId===commute.category) candidates=commute.rankedPois.map(item=>item.place)
      else {
        const result=await app.provider.getCorridorPois({routeGeometry:route.route.geometry,
          queryTerms:commuteCategoryQueries(task.categoryId),category:task.categoryId,
          corridorBufferM:1200,windowRadiusM:800,maxPagesPerWindow:1,maxUnique:12,detailLimit:2})
        candidates=result.pois.map(item=>item.place)
      }
      if (!unchanged()) return
      const existing=new Set(plan.tasks.flatMap(task=>task.options.map(option=>option.placeId)))
      const unique=new Map(candidates.filter(p=>!p.uid || !existing.has(p.uid)).map(p=>[p.uid??`${p.coord.lng},${p.coord.lat}`,p]))
      candidates=[...unique.values()].slice(0,2)
      if (!candidates.length) throw new Error(`沿途暂未找到可安排的${commuteCategoryLabel(task.categoryId)}地点，请换个需求试试`)
      choices.push({category:task.categoryId,places:candidates,minutes:task.serviceMinutes??commute.stayMinutes})
    }
    if (!unchanged() || JSON.stringify(plan.tasks)!==originalTasks) throw new Error('途经点已变化，请按当前地点重新安排')
    snapshot=capture()
    execution.resetExecution()
    const prior=plan.tasks.map(task=>task.id)
    const added=choices.map(choice=>{
      if (choice.reuseId) { plan.setTaskServiceMinutes(choice.reuseId,choice.minutes);return choice.reuseId }
      return plan.addFlexibleTask(commuteCategoryLabel(choice.category),choice.places.map(place=>({
        ...place,windows:resolveOpeningWindows(place.structuredHours,place.shopHours).windows,
      })),choice.minutes)
    })
    // Existing waypoints stay in order. Only explicit "先…再…" fixes new task order.
    plan.visitOrder=intent.keepOrder?[...prior.filter(id=>!added.includes(id)),...added]:[]
    for (let i=1;!intent.keepOrder && i<prior.length;i++) {
      const task=plan.tasks.find(task=>task.id===prior[i])!
      task.precedenceIds=[...new Set([...task.precedenceIds,prior[i-1]!])]
    }
    const departure=parseClockToSeconds(commute.departureClock)
    if (departure==null) throw new Error('请先设置出发时间')
    const minutes=intent.totalMinutes??(intent.extraMinutes==null?null:route.route.durationSeconds/60+intent.extraMinutes)
    plan.timeLimitSeconds=minutes==null?null:Math.floor(departure+minutes*60)
    appliedTasks=JSON.stringify(plan.tasks)
    message.value='正在核对沿途地点和步行路线…'
    await plan.runPlan()
    if (!unchanged() || JSON.stringify(plan.tasks)!==appliedTasks) return
    const best=plan.result?.status==='ready'?plan.result.alternatives[0]:null
    if (!best) throw new Error(plan.error || '这些事情暂时无法在限定时间内办完，请增加时间或减少任务')
    const byId=new Map(plan.tasks.map(task=>[task.id,task]))
    plan.tasks=best.stops.map(stop=>{
      const task=byId.get(stop.taskId)!, chosen=task.options.find(option=>option.placeId===stop.placeId)!
      return {...task,precedenceIds:snapshot!.tasks.find(original=>original.id===task.id)?.precedenceIds??[],label:chosen.placeName??task.label,options:[chosen]}
    })
    plan.visitOrder=plan.tasks.map(task=>task.id)
    plan.result!.alternatives.splice(1)
    map.editingWaypoints=false
    message.value=`已安排，预计${formatClockSeconds(best.finishSeconds)}到终点。途经点已同步，可继续调整。`
  } catch (err) {
    if (unchanged()) {
      if (snapshot && (!appliedTasks || JSON.stringify(plan.tasks)===appliedTasks)) {
        plan.invalidatePlan('');Object.assign(plan,snapshot)
      }
      error.value=err instanceof Error?err.message:'这次未能安排，请稍后再试';message.value=''
    }
  } finally { if (controller===current) busy.value=false }
}
</script>

<template>
  <section
    v-if="commute.route"
    class="route-assistant"
    aria-label="智能安排路线"
    :aria-busy="busy"
  >
    <strong>想顺路办点什么？ <small>AI</small></strong>
    <form @submit.prevent="arrange">
      <input
        v-model="text"
        aria-label="办事需求与时间"
        maxlength="240"
        placeholder="买药再取快递，30分钟内到终点"
        :disabled="busy"
      >
      <button
        type="submit"
        :disabled="busy || plan.loading || commute.loading || !text.trim()"
      >
        {{ busy?'安排中…':'帮我安排' }}
      </button>
    </form>
    <p
      v-if="error"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-else-if="message"
      role="status"
    >
      {{ message }}
    </p>
    <small v-else>保留已有途经点；未说停留多久时，按当前设置每处{{ commute.stayMinutes }}分钟。</small>
  </section>
</template>

<style scoped>
.route-assistant{padding:14px;margin:14px 0;border:1px solid #dce7fb;border-radius:16px;background:#f5f8ff;color:#24364b}
.route-assistant>strong{font-size:15px}.route-assistant strong small{color:#4778dc;font-size:10px;margin-left:4px}
.route-assistant form{display:flex;gap:8px;margin:12px 0 8px}.route-assistant input{min-width:0;flex:1;border:1px solid #dae4f6;border-radius:12px;padding:11px;font:inherit;font-size:13px;background:white}
.route-assistant button{flex-shrink:0;border:0;border-radius:12px;background:#2864ed;color:#fff;padding:10px 12px;font:inherit;font-size:13px}.route-assistant button:disabled{opacity:.5}
.route-assistant p{font-size:13px;line-height:1.7;margin:8px 0 0;overflow-wrap:anywhere}.route-assistant p[role=alert]{color:#b45309}.route-assistant>small{font-size:11px;line-height:1.6;color:#74839a}
</style>
