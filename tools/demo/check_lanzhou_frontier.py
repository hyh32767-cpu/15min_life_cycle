"""兰州中山桥100m圆盘前沿，历史数据优先，只补实际前沿缺点。"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sqlite3
import time

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from core.grid_frontier import grid_frontier, frontier_geometry, fit_preview, fit_measured_preview
from tools.demo.compare_outside_in_grid import coordinate, legacy_geometry, score

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/benchmarks/lanzhou-disk-frontier-20261016'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    source=json.loads((ROOT/'experiments/results/e10_boundary/e10x_lanzhou.json').read_text())
    center=source['center'];lat,lng=center
    db=ROOT/'experiments/logs/cache.db'
    before=hashlib.sha256(db.read_bytes()).hexdigest()
    conn=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    raw={(a,b):v for a,b,v in conn.execute("SELECT d_lat,d_lng,duration_s FROM walk_times WHERE o_lat=? AND o_lng=? AND mode='walking'",tuple(round(x,6) for x in center))}
    conn.close()
    recent_path=OUT/'new-measurements.json'
    recent=json.loads(recent_path.read_text()) if recent_path.exists() else []
    measured={(p['x'],p['y']):p['durationSeconds'] for p in recent}
    fresh=[];frames=[];batches=[];error=None
    service=None
    if args.live:
        from api.app.dependencies import get_baidu_service
        service=get_baidu_service()
    def measure(points):
        nonlocal error
        values={p:measured[p] if p in measured else raw.get(coordinate(center,*p)) for p in points}
        missing=[p for p,v in values.items() if v is None]
        started=time.monotonic()
        if missing and service:
            from api.app.models.common import Coord
            from api.app.services.grid_frontier_service import PACER
            destinations=[Coord(lat=coordinate(center,*p)[0],lng=coordinate(center,*p)[1],crs='BD09') for p in missing]
            origin=Coord(lat=lat,lng=lng,crs='BD09')
            try:
                if not service.peek_matrix([origin],destinations):PACER.acquire(len(missing))
                response=service.travel_matrix([origin],destinations,trace_id='lanzhou-frontier-20261016',stage='isochrone')
                cells={c['toIndex']:c for c in response['cells']}
                for i,p in enumerate(missing):
                    cell=cells.get(i,{})
                    value=cell.get('durationSeconds') if cell.get('status')=='ok' else None
                    if cell.get('status')=='no_route':value={'status':'no_route'}
                    values[p]=value
                    row={'x':p[0],'y':p[1],'coordBD09':destinations[i].model_dump(),
                         'durationSeconds':value,'sourceKind':cell.get('sourceKind'),
                         'upstreamResponseHashes':response.get('upstreamResponseHashes',[])}
                    recent.append(row);fresh.append(row)
                recent_path.write_text(json.dumps(recent,ensure_ascii=False,indent=2))
            except Exception as exc:
                error=getattr(exc,'code',type(exc).__name__)
                raise
        batches.append({'positions':len(points),'historicalHits':sum(p not in missing for p in points),
                        'missingRequested':len(missing) if service else 0,'elapsedSeconds':round(time.monotonic()-started,3)})
        print(json.dumps({'batch':len(batches),'positions':len(points),'newPositions':len(missing) if service else 0},ensure_ascii=False),flush=True)
        return [values[p] for p in points]
    began=time.monotonic()
    try:state=grid_frontier(measure,half_m=1000,max_pairs=316,on_progress=frames.append)
    except Exception:
        state=frames[-1] if frames else {'done':False,'status':'failed'}
    elapsed=time.monotonic()-began
    if len(frames)>1 and frames[-1]['pairsUsed']==frames[-2]['pairsUsed']:frames[-2:]=[frames[-1]]
    geo=frontier_geometry(state) if frames else {'polygons':[],'contours':[],'fills':[]}
    shape=unary_union([Polygon(p['outer'],p['holes']) for p in geo['polygons']])
    sampled={coordinate(center,p['x'],p['y']) for p in state.get('samples',[])}
    held={}
    for (a,b),v in raw.items():
        if v is None or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 or (a,b) in sampled:continue
        x=(b-lng)*111320*math.cos(math.radians(a));y=(a-lat)*111320
        if math.hypot(x,y)<=1000:held[x,y]=v
    old=legacy_geometry(source,half=1000)
    mistakes=[{'x':p[0],'y':p[1],'seconds':v,'type':'false-reachable' if shape.covers(Point(*p)) else 'missed-reachable'}
              for p,v in held.items() if shape.covers(Point(*p))!=(v<=900)]
    summary={'city':source['city'],'status':state.get('status','partial'),'radiusM':1000,'spacingM':100,
             'diskMeasured':state.get('pairsUsed',0),'diskBatches':len(state.get('batches',[])),
             'newPositionsThisRun':len(fresh),'elapsedSeconds':round(elapsed,3),'mixedHistoricalAndLive':True,
             'notColdStartTiming':True,'errorCode':error,'heldOutChecks':score(lambda p:shape.covers(Point(*p)),held,list(held)),
             'oldRayHeldOutChecks':score(lambda p:old.covers(Point(*p)),held,list(held)),
             'clipped':state.get('clipped'),'interiorEstimated':True,
             'historicalDbUnchanged':before==hashlib.sha256(db.read_bytes()).hexdigest()}
    if service:summary['liveAccounting']=service.ledger.summary(trace_id='lanzhou-frontier-20261016').as_dict()
    baseline_path=OUT/'report-before-barrier.json'
    if baseline_path.exists():
        baseline=json.loads(baseline_path.read_text())
        before_shape=unary_union([Polygon(p['outer'],p['holes']) for p in baseline['geometryLocalMeters']['polygons']])
        summary['baselineOnSameChecks']=score(lambda p:before_shape.covers(Point(*p)),held,list(held))
        if service:summary['newPositionsSinceBaseline']=summary['liveAccounting']['pairs']-baseline['summary']['liveAccounting']['pairs']
    for frame in frames:
        fitter=fit_measured_preview if frame['done'] else fit_preview
        frame['previewContours']=[[[round((p['lng']-lng)*111320*math.cos(math.radians(lat)),4),round((p['lat']-lat)*111320,4)] for p in line]
                                  for line in fitter({**frame,'done':False},lng=lng,lat=lat)]
    report={'summary':summary,'centerBD09':{'lat':lat,'lng':lng},'result':state,'frames':frames,
            'geometryLocalMeters':geo,'heldOut':[{'x':p[0],'y':p[1],'seconds':v} for p,v in held.items()],
            'mistakes':mistakes,'requestBatches':batches,'historicalSource':str(db.relative_to(ROOT))}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
