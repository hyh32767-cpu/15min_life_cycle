"""单一新中心的新网格/原16向自适应扇形冷启动实测，独立缓存、相同发送节奏。"""
from pathlib import Path
from dataclasses import replace
import argparse
import json
import math
import os
import time

from api.app.config import Settings
from api.app.models.common import Coord
from api.app.services.baidu_service import BaiduService
from api.app.services.grid_frontier_service import SerialPacer
from core.coord import dest_at
from core.grid_frontier import grid_frontier, frontier_geometry, fit_preview, VERSION
from core.isochrone import compute_isochrone_adaptive, ADAPTIVE_ALGORITHM_VERSION
from core.ratelimit import WindowRateLimiter

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lat',type=float,required=True);parser.add_argument('--lng',type=float,required=True)
    parser.add_argument('--name',required=True)
    parser.add_argument('--order',choices=('fan-first','grid-first'),default='fan-first')
    parser.add_argument('--matrix-window-seconds',type=float)
    parser.add_argument('--cooldown-before',type=float,default=0)
    parser.add_argument('--only',choices=('fan','grid'))
    args=parser.parse_args()
    if args.matrix_window_seconds is not None:
        if not 0<args.matrix_window_seconds<=60:parser.error('matrix window must be within (0,60]')
        os.environ['BAIDU_MATRIX_ROUTES_PER_WINDOW']='50'
        os.environ['BAIDU_MATRIX_WINDOW_SECONDS']=str(args.matrix_window_seconds)
    if args.cooldown_before:time.sleep(min(60,max(0,args.cooldown_before)))
    stamp=time.strftime('%Y%m%d-%H%M%S')
    out=ROOT/'output/benchmarks'/f'fresh-frontier-vs-fan-{stamp}'
    out.mkdir(parents=True,exist_ok=False)
    private=ROOT/'api/var'/f'benchmark-{stamp}';private.mkdir(parents=True,exist_ok=False)
    settings=Settings.from_env()
    origin=Coord(lng=args.lng,lat=args.lat,crs='BD09')
    report={'name':args.name,'centerBD09':origin.model_dump(),'thresholdSeconds':900,
            'maxPairsEach':376,'sameSerialPacing':True,'isolatedEmptyCaches':True,
            'gridRadiusM':1100,'fanBracketHiM':1800,'fanToleranceM':50,
            'scopeNote':'相同中心/阈值/预算/发送节奏；网格裁剪于1.1公里，原扇形保留原1.8公里括界，不宣称范围与精度完全等同。',
            'runOrder':args.order,'matrixCapacity':int(os.environ.get('BAIDU_MATRIX_ROUTES_PER_WINDOW','50')),
            'matrixWindowSeconds':float(os.environ.get('BAIDU_MATRIX_WINDOW_SECONDS','4.2')),'runs':[]}
    order=(args.only,) if args.only else ('grid','fan') if args.order=='grid-first' else ('fan','grid')
    for index,kind in enumerate(order):
        if index:time.sleep(10)  # 算法间冷却不计入任一计时，避免上一批窗口遗留。
        service=BaiduService(replace(settings,cache_db=str(private/f'{kind}-cache.db'),ledger_db=str(private/f'{kind}-ledger.db')))
        pacer=SerialPacer();trace=f'fresh-{stamp}-{kind}'
        gate=WindowRateLimiter(report['matrixCapacity'],window_s=report['matrixWindowSeconds'])
        start=time.monotonic();rows=[];samples=[];snapshots=[];first=None;failure=None
        def measure(points):
            values=[]
            for offset in range(0,len(points),50):
                chunk=points[offset:offset+50]
                destinations=[]
                for a,b in chunk:
                    if kind=='fan':lat,lng=dest_at(origin.lng,origin.lat,a,b)
                    else:
                        lat,lng=dest_at(origin.lng,origin.lat,0,b)
                        lat,lng=dest_at(lng,lat,90,a)
                    destinations.append(Coord(lng=lng,lat=lat,crs='BD09'))
                before=time.monotonic();pacer.acquire(len(chunk));gate.acquire(len(chunk),max_wait_s=60);sent=time.monotonic()
                result=service.travel_matrix([origin],destinations,trace_id=trace,stage='isochrone')
                finished=time.monotonic()
                cells={c['toIndex']:c for c in result['cells']}
                batch=[]
                for i,p in enumerate(chunk):
                    cell=cells.get(i,{})
                    if cell.get('status') not in ('ok','no_route'):raise RuntimeError('matrix-cell-unavailable')
                    value=cell.get('durationSeconds') if cell.get('status')=='ok' else None
                    if value is None and kind=='grid':value={'status':'no_route'}
                    batch.append(value)
                    samples.append({'probe':list(p),'coord':destinations[i].model_dump(),'value':value})
                values.extend(batch)
                rows.append({'pairs':len(chunk),'queueSeconds':round(sent-before,4),
                             'apiSeconds':round(finished-sent,4),'elapsedSeconds':round(finished-start,4)})
                (out/f'{kind}-progress.json').write_text(json.dumps({'batches':rows,'samples':samples},ensure_ascii=False))
                print(json.dumps({'algorithm':kind,'batch':len(rows),'pairs':len(samples),'elapsedSeconds':round(finished-start,2)},ensure_ascii=False),flush=True)
            return values
        def progress(snapshot):
            nonlocal first
            if first is None:first=time.monotonic()-start
            if kind=='grid':
                frontier_geometry(snapshot);fit_preview(snapshot,lng=origin.lng,lat=origin.lat)
                snapshots.append(snapshot)
        try:
            if kind=='fan':
                result=compute_isochrone_adaptive(measure,threshold_s=900,lo_m=200,hi_m=1400,
                    initial_m=800,tol_m=50,max_pairs=376,on_progress=progress)
                payload=result.as_dict();geometry=None
            else:
                result=grid_frontier(measure,half_m=1100,max_pairs=376,on_progress=progress)
                payload=result;geometry=frontier_geometry(result)
        except Exception as exc:
            failure=getattr(exc,'code',type(exc).__name__);payload={'status':'failed'};geometry=None
        elapsed=time.monotonic()-start
        summary={'kind':kind,'version':ADAPTIVE_ALGORITHM_VERSION if kind=='fan' else VERSION,
                 'status':payload.get('status'),'elapsedSeconds':round(elapsed,3),
                 'firstMeasuredUpdateSeconds':round(first,3) if first is not None else None,
                 'pairs':len(samples),'batches':len(rows),'apiSeconds':round(sum(b['apiSeconds'] for b in rows),3),
                 'queueSeconds':round(sum(b['queueSeconds'] for b in rows),3),
                 'errorCode':failure,'accounting':service.ledger.summary(trace_id=trace).as_dict()}
        summary['upstreamSeconds']=round(summary['accounting']['latencyMs']/1000,3)
        summary['serviceTimeIncludesInternalQuota']=True
        summary['warnings']=payload.get('warnings',[])
        summary['windowClipped']=payload.get('clipped')
        report['runs'].append(summary)
        (out/f'{kind}.json').write_text(json.dumps({'summary':summary,'result':payload,'geometryLocalMeters':geometry,
            'samples':samples,'batches':rows,'snapshots':snapshots},ensure_ascii=False,indent=2))
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(summary,ensure_ascii=False),flush=True)
        if failure:break
    print(str(out),flush=True)


if __name__=='__main__':main()
