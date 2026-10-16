import math
import threading

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from core.grid_frontier import grid_frontier, frontier_geometry, fit_preview, fit_measured_preview


def test_preview_needs_measured_time_brackets_and_does_not_invent_a_circle():
    state={'done':False,'radiusM':1000,'halfM':1000,'thresholdSeconds':900,'samples':[]}
    assert fit_measured_preview(state,lng=116.4,lat=39.9)==[]
    state['samples']=[{'x':0,'y':1000,'seconds':1800,'state':'outside'}]
    assert fit_measured_preview(state,lng=116.4,lat=39.9)==[]
    state['samples']=[{'x':x,'y':y,'seconds':1200,'state':'outside'} for x,y in [(0,1000),(1000,0),(0,-1000),(-1000,0)]]
    assert fit_measured_preview(state,lng=116.4,lat=39.9)==[]  # 全部超时，不能以虚构中心时长收缩。
    state['samples'][0]['seconds']=600
    assert fit_measured_preview(state,lng=116.4,lat=39.9)
    assert fit_preview({**state,'done':True},lng=116.4,lat=39.9)==[]


def test_loading_outline_is_closed_but_final_fitting_uses_measured_time_field():
    state={'done':False,'radiusM':1000,'halfM':1000,'thresholdSeconds':900,'samples':[]}
    initial=fit_preview(state,lng=116.4,lat=39.9)[0]
    state['samples']=[{'x':0,'y':1000,'seconds':1800}]
    loading=fit_preview(state,lng=116.4,lat=39.9)[0]
    assert len(loading)==73 and loading[0]==loading[-1]
    assert loading[0]!=initial[0] and loading[36]==initial[36]
    assert fit_measured_preview(state,lng=116.4,lat=39.9)==[]
    assert fit_preview({**state,'done':True},lng=116.4,lat=39.9)==[]


def test_complete_outer_layer_before_entering_next_and_publish_every_batch():
    updates=[]
    r=grid_frontier(lambda ps:[math.hypot(x,y)*1.4 for x,y in ps],on_progress=updates.append)
    assert updates[0]['pairsUsed']==50
    assert all(1000<math.hypot(p['x'],p['y'])<=1100 for p in updates[0]['samples'])
    assert updates[1]['pairsUsed']==60
    shells=[b['shellM'] for b in r['batches'] if b['phase']=='boundary']
    assert shells==sorted(shells,reverse=True)
    assert len(updates)==len(r['batches'])+1
    assert all(b['pairs']<=50 for b in r['batches'])
    assert r['status']=='complete'
    assert r['pairsUsed']<440
    assert r['domainPoints']==377 and r['maxExternalPoints']==376
    assert all(p['x']**2+p['y']**2<=1100**2 for p in r['samples'])
    # 中心只作逻辑锚点，不以假0计作实测。内部抽检在主边界之后。
    assert not any(p['x']==p['y']==0 for p in r['samples'])
    assert next(i for i,u in enumerate(updates) if u['phase']=='interior-check')>1
    assert len(updates[0]['samples'])==50


def test_circle_domain_never_infers_or_fills_square_corners():
    r=grid_frontier(lambda ps:[500]*len(ps))
    g=frontier_geometry(r)
    shape=unary_union([Polygon(p['outer'],p['holes']) for p in g['polygons']])
    assert r['clipped']
    assert not shape.covers(Point(900,900))
    assert shape.covers(Point(0,0))
    assert all(x*x+y*y<=1100**2+1e-5 for p in g['fills'] for x,y in p)


def test_internal_river_band_is_not_filled_and_bridge_remains_reachable():
    def measure(points):
        return [1800 if 100<=abs(x)<=550 and abs(y)<80 else math.hypot(x,y)*1.2+1 for x,y in points]
    updates=[]
    result=grid_frontier(measure,on_progress=updates.append)
    geo=frontier_geometry(result)
    shape=unary_union([Polygon(p['outer'],p['holes']) for p in geo['polygons']])
    assert result['status']=='complete'
    assert not shape.covers(Point(300,0)) and not shape.covers(Point(-300,0))
    assert shape.covers(Point(0,0)) and shape.covers(Point(0,100))
    assert any(p['x']==300 and p['y']==0 and p['state']=='outside' for p in result['samples'])
    assert all(b['pairs']<=50 for b in result['batches'])
    assert all(not frontier_geometry(s)['fills'] for s in updates if not s['done'])


def test_budget_and_unknown_never_produce_complete_fill():
    for measure,budget in [(lambda ps:[None]*len(ps),440),(lambda ps:[1200]*len(ps),80)]:
        r=grid_frontier(measure,max_pairs=budget)
        assert r['status']=='partial'
        assert r['pairsUsed']<=budget
        assert frontier_geometry(r)['fills']==[]


def test_explicit_no_route_is_not_unknown_or_a_fabricated_duration():
    r=grid_frontier(lambda ps:[{'status':'no_route'} if x>=400 else math.hypot(x,y)*1.4+1 for x,y in ps])
    assert r['unknownCount']==0
    assert any(p['state']=='no_route' and p['seconds'] is None for p in r['samples'])
    assert not any(p['seconds']==math.inf for p in r['samples'])
    geo=frontier_geometry(r)
    shape=unary_union([Polygon(p['outer'],p['holes']) for p in geo['polygons']])
    assert not shape.covers(Point(800,0))


def test_interior_audit_finds_hole_and_shape_preserves_it():
    def measure(ps):
        return [1300 if math.hypot(x-200,y-200)<140 else math.hypot(x,y)*1.25+1 for x,y in ps]
    r=grid_frontier(measure)
    assert r['status']=='complete'
    assert any(p['x']==200 and p['y']==200 and p['state']=='outside' for p in r['samples'])
    geo=frontier_geometry(r)
    shape=unary_union([Polygon(p['outer'],p['holes']) for p in geo['polygons']])
    assert not shape.covers(Point(200,200))
    assert shape.covers(Point(0,0))
    assert any(p['holes'] for p in geo['polygons'])


def test_running_snapshot_only_measured_segments_no_interior_fill():
    updates=[]
    grid_frontier(lambda ps:[math.hypot(x,y)+1 for x,y in ps],on_progress=updates.append)
    assert all(frontier_geometry(u)['fills']==[] for u in updates if not u['done'])
    assert any(frontier_geometry(u)['contours'] for u in updates if not u['done'])


def test_service_background_preview_is_separate_from_analysis_and_cache(monkeypatch,tmp_path):
    from api.app.services.isochrone_service import IsochroneService
    from api.app.services import grid_frontier_service as gs
    from api.app.models.common import Coord
    from api.app.models.api import IsochroneResponse
    from api.app.routers.isochrones import _render_report
    from api.app.storage.derived_cache import DerivedCache
    monkeypatch.setattr(gs.PACER,'acquire',lambda cost:None)
    entered,release=threading.Event(),threading.Event()
    class Fake:
        def __init__(self):self.calls=0
        def travel_matrix(self,origins,destinations,**kwargs):
            self.calls+=1
            assert len(destinations)<=50
            if self.calls==2:
                entered.set();assert release.wait(5)
            o=origins[0]
            return {'cells':[{'toIndex':i,'durationSeconds':math.hypot((p.lat-o.lat)*111320,(p.lng-o.lng)*111320*math.cos(math.radians(p.lat)))*1.4+1,'status':'ok'} for i,p in enumerate(destinations)],
                    'responseHashes':[f'hash-{self.calls}'],'expiresAt':'2099-01-01T00:00:00+00:00'}
    service=IsochroneService(Fake(),cache=DerivedCache(str(tmp_path/'derived.db')))
    start=service.run(Coord(lng=116.4,lat=39.9),threshold_seconds=900,max_pairs=440,frontier=True,l2_first=True)
    try:
        assert start['frontier']['radiusM']==1100
        assert entered.wait(5)
        partial=service.get_task_status(start['taskId'])
        assert partial['pairsUsed']==50 and partial['backgroundStatus']=='running'
        assert partial['frontier']['samples'] and partial['frontier']['previewOnly']
        assert partial['frontier']['polygons']==[]
        assert partial['report']['approxAreaM2'] is None
        IsochroneResponse(**partial)
    finally:
        release.set();service._workers.shutdown(wait=True)
    full=service.get_task_status(start['taskId'])
    assert full['status']=='complete' and full['backgroundStatus']=='completed'
    assert full['frontier']['polygons'] and full['frontier']['previewContours']==[]
    assert full['report']['classificationBoundary']=='grid-frontier-approximation'
    assert 'frontier' in _render_report(start['taskId'],'json',full)
    reused=service.run(Coord(lng=116.4,lat=39.9),threshold_seconds=900,max_pairs=440,frontier=True)
    assert reused['cacheHit'] and reused['pairsUsed']==0


def test_rate_error_stops_new_live_calls_and_retains_unknown_samples(monkeypatch):
    from api.app.services.isochrone_service import IsochroneService
    from api.app.services import grid_frontier_service as gs
    from api.app.services.errors import ServiceError
    from api.app.models.common import Coord
    monkeypatch.setattr(gs.PACER,'acquire',lambda cost:None)
    class Fake:
        calls=0
        def travel_matrix(self,*args,**kwargs):
            self.calls+=1
            raise ServiceError('RATE_LIMITED','limited',retry_after=15)
    fake=Fake();service=IsochroneService(fake)
    full=service.run(Coord(lng=116.4,lat=39.9),threshold_seconds=900,max_pairs=440,frontier=True)
    service._workers.shutdown(wait=True)
    assert fake.calls==1 and full['backgroundStatus']=='degraded'
    assert full['pairsUsed']==50
    assert all(p['state']=='unknown' for p in full['frontier']['samples'])


def test_cache_only_frontier_never_calls_upstream():
    from api.app.services.isochrone_service import IsochroneService
    from api.app.models.common import Coord
    class Fake:
        def travel_matrix(self,*a,**k):raise AssertionError('cache-only cannot query upstream')
    service=IsochroneService(Fake())
    result=service.run(Coord(lng=116.4,lat=39.9),threshold_seconds=900,frontier=True,cache_only=True)
    service._workers.shutdown(wait=True)
    assert result['pairsUsed']==0 and result['warnings']==['upstream:CACHE_MISS']
