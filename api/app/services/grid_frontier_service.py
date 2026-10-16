"""串行网格前沿任务；逐批发布拟合预览，预览不参与最终几何或派生缓存。"""
from __future__ import annotations

import math
import time
import uuid
import threading
from datetime import datetime, timezone

from core.coord import dest_at
from core.grid_frontier import VERSION, DEFAULT_RADIUS_M, DEFAULT_MAX_PAIRS, grid_frontier, frontier_geometry, fit_preview, fit_measured_preview
from ..models.common import Coord
from ..storage.derived_cache import derived_key
from .baidu_service import to_baidu_bd09
from .errors import ServiceError


class SerialPacer:
    """任务间共用串行发送节奏，仍叠加正式接口限流；缓存命中不占发送窗口。"""
    def __init__(self):
        self.lock=threading.Lock();self.last=0.;self.cost=0

    def acquire(self,cost):
        profile=((0,0),(10,1.8),(20,4.1),(30,6),(40,7.2),(50,9))
        with self.lock:
            interval=0.
            for (a,ta),(b,tb) in zip(profile,profile[1:]):
                if a<=self.cost<=b:
                    interval=max(1.8,ta+(tb-ta)*(self.cost-a)/(b-a));break
            if self.last:time.sleep(max(0,self.last+interval-time.monotonic()))
            self.last,self.cost=time.monotonic(),cost


PACER=SerialPacer()


class GridFrontierService:
    def __init__(self, owner):
        self.owner=owner

    def run(self, origin, *, threshold_seconds, max_pairs=DEFAULT_MAX_PAIRS, l2_first=False, trace_id=None, cache_only=False, **_):
        owner=self.owner
        origin,_converted=to_baidu_bd09(origin)
        trace=trace_id or uuid.uuid4().hex
        half=min(DEFAULT_RADIUS_M,max(300,math.ceil(threshold_seconds*1.5/100)*100))
        key=derived_key(algorithm='grid-frontier',algorithm_version=VERSION,
            input_hashes={'origin':str(origin.model_dump())},params={'seconds':threshold_seconds,'radius':half,'domain':'disk','spacing':100,'budget':max_pairs,'audit':16,'drawing':'measured-delaunay-v1'})
        if owner.cache:
            record=owner.cache.get(key)
            if record:
                expiry=record.result.get('expiresAt')
                try:
                    parsed=datetime.fromisoformat(expiry.replace('Z','+00:00')) if expiry else None
                    valid=parsed is not None and parsed.tzinfo is not None and parsed>datetime.now(timezone.utc)
                except (ValueError,TypeError,AttributeError):valid=False
                if valid:
                    task=uuid.uuid4().hex[:12]
                    owner.cache.register_task(task,key)
                    return {**record.result,'taskId':task,'cacheHit':True,'pairsUsed':0,'traceId':trace,'backgroundStatus':'completed'}
        task=uuid.uuid4().hex[:12]
        base={'taskId':task,'status':'partial','thresholdSeconds':threshold_seconds,'origin':origin.model_dump(),
            'radiiM':{},'failedBearings':[],'skippedBearings':[],'algorithmVersion':VERSION,'warnings':[],
            'cacheHit':False,'pairsUsed':0,'traceId':trace,'mode':'live','sourceKind':'derived','expiresAt':None,
            'upstreamResponseHashes':[],'backgroundStatus':'running','report':{},
            'frontier':{'phase':'boundary','spacingM':100,'halfM':half,'radiusM':half,'domainShape':'disk','samples':[],'previewContours':fit_preview({'done':False,'samples':[],'halfM':half,'thresholdSeconds':threshold_seconds},lng=origin.lng,lat=origin.lat),
                        'previewOnly':True,'polygons':[],'fills':[],'batchCount':0}}
        if cache_only:
            return {**base,'backgroundStatus':'degraded','warnings':['upstream:CACHE_MISS']}
        def publish(payload):
            with owner._bg_lock:
                owner._bg_tasks[task]=payload
        def work():
            hashes,expiries,errors=[],[],[]
            start=time.monotonic()
            def coord(x,y):
                lat,lng=dest_at(origin.lng,origin.lat,0,y)
                lat,lng=dest_at(lng,lat,90,x)
                return Coord(lng=lng,lat=lat,crs='BD09')
            def measure(points):
                if errors:
                    raise ServiceError(errors[0],'步行查询暂停，请稍后重试')
                if time.monotonic()-start>240:
                    errors.append('UPSTREAM_TIMEOUT')
                    return [None]*len(points)
                destinations=[coord(*p) for p in points]
                try:
                    peek=getattr(owner.baidu,'peek_matrix',None)
                    if peek is None or peek([origin],destinations) is None:PACER.acquire(len(points))
                    # 一个任务在任何时刻只有一个≤50对的调用；限流仍走公共百度出口。
                    result=owner.baidu.travel_matrix([origin],destinations,trace_id=trace,stage='isochrone-frontier')
                    hashes.extend(result.get('responseHashes',[]));expiries.append(result.get('expiresAt'))
                    errors.extend(e['code'] for e in result.get('errors',[]))
                    cells={c['toIndex']:c for c in result['cells']}
                    return [({'status':'no_route'} if cells.get(i,{}).get('status')=='no_route'
                        else cells.get(i,{}).get('durationSeconds') if cells.get(i,{}).get('status')=='ok' else None) for i in range(len(points))]
                except ServiceError as exc:
                    errors.append(exc.code)
                    return [None]*len(points)
            def payload(state):
                geo=frontier_geometry(state)
                radii=sorted(math.hypot(x,y) for p in geo['polygons'] for x,y in p['outer'])
                actual=[p for p in state['samples'] if p['seconds'] is not None]
                preview=fit_preview(state,lng=origin.lng,lat=origin.lat)
                convert=lambda line:[coord(x,y).model_dump() for x,y in line]
                complete=state['done'] and not state['budgetLimited'] and not state['pendingCount'] and not state['unknownCount'] and not errors
                warnings=[f'upstream:{e}' for e in sorted(set(errors))]
                if state['budgetLimited']:warnings.append('frontier_budget_exhausted')
                if state['clipped']:warnings.append('frontier_window_clipped')
                if complete:warnings.append('interior_estimated:limited-audit')
                return {**base,'status':'complete' if complete else 'partial',
                    'backgroundStatus':'running' if not state['done'] else 'completed' if complete else 'degraded',
                    'pairsUsed':state['pairsUsed'],'warnings':warnings,
                    'expiresAt':min(expiries) if expiries and all(expiries) else None,
                    'upstreamResponseHashes':sorted(set(hashes)),
                    'reconstruction':{'method':VERSION,'sampleCount':len(actual),'contours':fit_measured_preview({**state, 'done': False}, lng=origin.lng, lat=origin.lat) if complete else [convert(l) for l in geo['contours']],
                                      'classificationBoundary':'grid-frontier-approximation','clipMarginM':0,'note':'显示线为实测点时间场拟合；区域判定使用frontier.polygons，圆角仅在前端绘制'},
                    'frontier':{'phase':state['phase'],'spacingM':100,'halfM':half,'radiusM':half,'domainShape':'disk',
                        'domainPoints':state['domainPoints'],'maxExternalPoints':state['maxExternalPoints'],'samples':[
                        {**p,'coord':coord(p['x'],p['y']).model_dump()} for p in state['samples']],
                        'previewContours':preview,'previewOnly':True,'batchCount':len(state['batches']),
                        'currentShellM':state['batches'][-1]['shellM'] if state['batches'] else half,
                        'pendingCount':state['pendingCount'],'budgetLimited':state['budgetLimited'],
                        'interiorEstimated':True,'interiorPolicy':state['interiorPolicy'],'clipped':state['clipped'],
                        'polygons':[{'outer':convert(p['outer']),'holes':[convert(h) for h in p['holes']]} for p in geo['polygons']],
                        'fills':[convert(p) for p in geo['fills']]},
                    'report':{'thresholdSeconds':threshold_seconds,'algorithmVersion':VERSION,'pairsUsed':state['pairsUsed'],
                        'medianRadiusM':radii[len(radii)//2] if radii and complete else None,
                        'maxRadiusM':max(radii) if radii and complete else None,
                        'minRadiusM':min(radii) if radii and complete else None,
                        'approxAreaM2':geo['areaM2'] if complete else None,'approxPerimeterM':geo['perimeterM'] if complete else None,
                        'approxNote':'100米网格前沿近似；轴线检查与屏障追踪，未测内区仍为估计，非完整路网证明',
                        'classificationBoundary':'grid-frontier-approximation','clipped':state['clipped']}}
            try:
                # Final progress is emitted by the core before durable cache writes.
                # Keep the public task running until both result and task alias commit.
                state=grid_frontier(measure,threshold_s=threshold_seconds,half_m=half,max_pairs=max_pairs,
                    on_progress=lambda s:publish(payload(s)) if not s['done'] else None)
                full=payload(state)
                if owner.cache and full['status']=='complete' and full['expiresAt']:
                    owner.cache.put(key=key,algorithm='grid-frontier',algorithm_version=VERSION,
                        dependencies={'upstreamResponseHashes':full['upstreamResponseHashes']},result=full)
                    owner.cache.register_task(task,key)
                publish(full)
                return full
            except Exception as exc:
                with owner._bg_lock:current=dict(owner._bg_tasks.get(task) or base)
                current={**current,'status':'partial','backgroundStatus':'degraded',
                    'warnings':[*current['warnings'],f'background-error:{getattr(exc,"code",type(exc).__name__)}']}
                publish(current)
                return current
        with owner._bg_lock:
            existing=owner._bg_keys.get(key)
            if existing and owner._bg_tasks.get(existing,{}).get('backgroundStatus')=='running':return owner._bg_tasks[existing]
            if sum(p.get('backgroundStatus')=='running' for p in owner._bg_tasks.values())>=2:
                raise ServiceError('SERVICE_BUSY','正在测量其他步行范围，请稍后重试',http_status=503,retryable=True,retry_after=3)
            # 与原任务共用有界任务池及状态接口。
            for old in list(owner._bg_tasks):
                if len(owner._bg_tasks)<128:break
                if owner._bg_tasks[old].get('backgroundStatus')!='running':
                    owner._bg_tasks.pop(old);owner._bg_times.pop(old,None)
                    owner._bg_keys={k:v for k,v in owner._bg_keys.items() if v!=old}
            owner._bg_tasks[task]=base;owner._bg_keys[key]=task;owner._bg_times[task]=time.monotonic()
        if l2_first:
            owner._workers.submit(work)
            return base
        return work()
