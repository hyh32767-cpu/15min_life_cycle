"""外沿向内的网格前沿；每层组批，首次可达阻止该分支继续深入。

只通过批量回调读取测值。深内部未测位置只作区域估计，不产生虚构步行秒数。
内部缺口检查单列阶段；它不能证明所有亚网格障碍均不存在。
"""
from __future__ import annotations

import copy
import math

VERSION = 'grid-frontier-barrier-v4'
DEFAULT_RADIUS_M = 1100
DEFAULT_MAX_PAIRS = 376


def fit_measured_preview(state, *, lng, lat):
    """恢复方形版的测点Delaunay等时线，仅作展示，不参与区域判定。"""
    from .time_contour import reconstruct_time_contours
    actual=[p for p in state['samples'] if p['seconds'] is not None]
    if state['done'] or len(actual)<3:return []
    return reconstruct_time_contours([(math.degrees(math.atan2(p['x'],p['y']))%360,
        math.hypot(p['x'],p['y']),p['seconds']) for p in actual],
        {i:state['halfM']*2 for i in range(0,360,30)},threshold_s=state['thresholdSeconds'],lng=lng,lat=lat)['contours']


def fit_preview(state, *, lng, lat):
    """加载时从原圆连续变形的展示线；不参与测量和分析。"""
    from .coord import dest_at
    if state['done']:return []
    sectors=[[] for _ in range(36)]
    radius=state.get('radiusM') or state['halfM']
    threshold=state['thresholdSeconds']
    for p in state['samples']:
        if p['seconds'] is None or p['seconds']<=0:continue
        bearing=math.degrees(math.atan2(p['x'],p['y']))%360
        sectors[int(math.floor(bearing/10+.5))%36].append((math.hypot(p['x'],p['y']),p['seconds']))
    radii=[]
    for probes in sectors:
        inner=max(((r,t) for r,t in probes if t<=threshold),default=(0.,0.))
        outer=min(((r,t) for r,t in probes if t>threshold and r>inner[0]),default=None)
        r=radius if outer is None else inner[0]+(outer[0]-inner[0])*(threshold-inner[1])/(outer[1]-inner[1])
        radii.append(min(radius,max(0.,r)))
    line=[]
    for i in range(73):
        index=(i//2)%36
        r=radii[index] if i%2==0 else (radii[index]+radii[(index+1)%36])/2
        y,x=dest_at(lng,lat,(i*5)%360,r)
        line.append({'lng':x,'lat':y,'crs':'BD09'})
    return [line]


def grid_frontier(measure_batch, *, threshold_s=900, half_m=DEFAULT_RADIUS_M, spacing_m=100,
                  max_pairs=DEFAULT_MAX_PAIRS, audit_points=16, on_progress=None, domain_shape='disk'):
    if half_m <= 0 or spacing_m <= 0 or half_m % spacing_m or threshold_s <= 0 or max_pairs < 1:
        raise ValueError('invalid grid frontier parameters')
    if domain_shape not in ('disk','square'):raise ValueError('invalid domain shape')
    axis = list(range(-half_m, half_m + 1, spacing_m))
    domain={(x,y) for x in axis for y in axis if domain_shape=='square' or x*x+y*y<=half_m*half_m}
    max_pairs=min(max_pairs,len(domain)-1)
    def level(p):
        return math.ceil(math.hypot(*p)/spacing_m-1e-9)*spacing_m if domain_shape=='disk' else max(map(abs,p))
    memo, batches = {}, []
    origin = (0, 0)
    boundary={p for p in domain if any(q not in domain for q in
        ((p[0]+spacing_m,p[1]),(p[0]-spacing_m,p[1]),(p[0],p[1]+spacing_m),(p[0],p[1]-spacing_m)))}
    pending = {p for p in domain if level(p)==half_m}
    phase, exhausted = 'boundary', False

    def normalize(v):
        if isinstance(v,dict):
            if v.get('status')=='no_route':return math.inf
            v=v.get('durationSeconds')
        return float(v) if v is not None and math.isfinite(v) and v>0 else None

    def neighbors(p):
        x,y=p
        return [(a,b) for a,b in ((x-spacing_m,y),(x+spacing_m,y),(x,y-spacing_m),(x,y+spacing_m))
                if (a,b) in domain and (a,b)!=origin]

    def snapshot(done=False):
        samples = [{'x':x,'y':y,'seconds':None if v==math.inf else v,
                    'state':'unknown' if v is None else 'no_route' if v==math.inf else 'reachable' if v<=threshold_s else 'outside'}
                   for (x,y),v in memo.items()]
        return {'version':VERSION,'phase':phase,'done':done,'halfM':half_m,'spacingM':spacing_m,
            'domainShape':domain_shape,'radiusM':half_m if domain_shape=='disk' else None,
            'domainPoints':len(domain),'maxExternalPoints':len(domain)-1,
            'thresholdSeconds':threshold_s,'samples':samples,'pairsUsed':len(memo),
            'batches':copy.deepcopy(batches),'pendingCount':len(pending),
            'unknownCount':sum(v is None for v in memo.values()),'budgetLimited':exhausted,
            'interiorPolicy':'axis-sweep-and-connected-barrier-audit',
            'clipped':any(memo.get(p) is not None and memo[p]<=threshold_s for p in boundary)}

    def publish(done=False):
        result=snapshot(done)
        if on_progress:on_progress(result)
        return result

    def run_front():
        nonlocal exhausted, pending
        while pending:
            pending.difference_update(memo)
            if not pending:break
            remaining=max_pairs-len(memo)
            if remaining<=0:
                exhausted=True
                break
            # 当前外侧一层全部完成，才处理下一层；每次最多50对串行调用。
            shell=max(level(p) for p in pending)
            # 同层补一格横向连接保护，避免边界绕角时出现连续1–3对小尾批。
            current=[p for p in pending if level(p)==shell]
            pending.update(q for p in current for q in neighbors(p)
                           if level(q)==shell and q not in memo)
            points=sorted(p for p in pending if level(p)==shell)[:min(50,remaining)]
            values=measure_batch(points)
            if len(values)!=len(points):raise ValueError('measurement count mismatch')
            pending.difference_update(points)
            for p,v in zip(points,values):
                memo[p]=normalize(v)
            # 外框尚未测完时，也不会穿到内层。新前沿仅由真实超时点产生。
            for p in points:
                if memo[p] is not None and memo[p]>threshold_s:
                    pending.update(q for q in neighbors(p) if q not in memo and
                                   (phase!='boundary' or level(q)<=shell))
            batches.append({'phase':phase,'shellM':shell,'pairs':len(points),'pairsUsed':len(memo)})
            publish()

    run_front()
    boundary_done=not pending and not any(v is None for v in memo.values())
    if boundary_done and audit_points:
        phase='interior-check'
        # 外向内阶段可能在圆带交界跳过横向邻格；内部追踪须从已有
        # 所有超时点重新接出，不能只从本轮新抽检点接出。
        pending.update(q for p,v in memo.items() if v is not None and v>threshold_s
                       for q in neighbors(p) if q not in memo)
        audit_axis=sorted({round(k*half_m/(5*spacing_m))*spacing_m for k in (-3,-1,1,3)})
        # 外侧可达不意味着内侧都可达：两条贯穿轴逐格查复通/断带，
        # 再保留离轴抽检。发现超时点后按邻接关系追踪屏障，不限向内。
        axial={(x,0) for x in axis}|{(0,y) for y in axis}
        off_axis=[(x,y) for x in audit_axis for y in audit_axis if (x,y) in domain and (x,y) not in memo and (x,y)!=origin][:audit_points]
        candidates=axial|set(off_axis)
        probes=sorted((p for p in candidates if p in domain and p not in memo and p!=origin),key=lambda p:(-level(p),p))
        if len(probes)>max_pairs-len(memo):exhausted=True
        probes=probes[:max_pairs-len(memo)]
        for offset in range(0,len(probes),50):
            batch=probes[offset:offset+50]
            values=measure_batch(batch)
            if len(values)!=len(batch):raise ValueError('measurement count mismatch')
            for p,v in zip(batch,values):
                memo[p]=normalize(v)
                if memo[p] is not None and memo[p]>threshold_s:
                    pending.update(q for q in neighbors(p) if q not in memo)
            batches.append({'phase':phase,'shellM':None,'pairs':len(batch),'pairsUsed':len(memo)})
            publish()
        run_front()
    phase='finished'
    result=publish(True)
    result['status']='complete' if not exhausted and not pending and not result['unknownCount'] else 'partial'
    return result


def frontier_geometry(state):
    """网格局部三角形裁剪，保留多分量与洞；无实测秒数的内区不伪填时间。

只有完成外部前沿后才推断内部区域。运行中仅输出真实测值形成的开口线段。
相邻实测异号边按时间插值，未测内区参与的边只能取格内中点，属于近似区域。
"""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union, linemerge
    from shapely.geometry import MultiLineString
    half,spacing,t=state['halfM'],state['spacingM'],state['thresholdSeconds']
    in_domain=lambda p:state.get('domainShape','square')!='disk' or p[0]*p[0]+p[1]*p[1]<=half*half
    memo={(p['x'],p['y']):p['seconds'] for p in state['samples']}
    no_routes={(p['x'],p['y']) for p in state['samples'] if p['state']=='no_route'}
    axis=list(range(-half,half+1,spacing))
    final=state['done'] and not state['budgetLimited'] and not state['pendingCount'] and not state['unknownCount']
    fills,segments=[],[]
    def known(p):return p in memo and memo[p] is not None
    def inside(p):
        if not in_domain(p):return None
        if p==(0,0):return True
        if p in no_routes:return False
        return memo[p]<=t if known(p) else True if p not in memo and final else None
    def crossing(a,b):
        if known(a) and known(b):
            f=(t-memo[a])/(memo[b]-memo[a])
        else:f=.5
        return (round(a[0]+f*(b[0]-a[0]),6),round(a[1]+f*(b[1]-a[1]),6))
    for x in axis[:-1]:
        for y in axis[:-1]:
            a,b,c,d=(x,y),(x+spacing,y),(x+spacing,y+spacing),(x,y+spacing)
            vertices=[p for p in (a,b,c,d) if in_domain(p)]
            triangles=((a,b,c),(a,c,d)) if len(vertices)==4 else (tuple(vertices),) if len(vertices)==3 else ()
            for tri in triangles:
                flags=[inside(p) for p in tri]
                edges=[]
                for i in range(3):
                    u,v=tri[i],tri[(i+1)%3]
                    if known(u) and known(v) and (memo[u]<=t)!=(memo[v]<=t):edges.append(crossing(u,v))
                if len(edges)==2:segments.append(edges)
                if not final or any(v is None for v in flags):continue
                clipped=[]
                for i in range(3):
                    u,v=tri[i],tri[(i+1)%3]
                    if flags[i]:clipped.append(u)
                    if flags[i]!=flags[(i+1)%3]:clipped.append(crossing(u,v))
                if len(clipped)>=3 and Polygon(clipped).area>1e-8:fills.append(clipped)
    shape=unary_union([Polygon(p) for p in fills])
    polygons=[]
    if not shape.is_empty:
        for poly in [shape] if shape.geom_type=='Polygon' else shape.geoms:
            if poly.geom_type=='Polygon':polygons.append({'outer':list(poly.exterior.coords),'holes':[list(r.coords) for r in poly.interiors]})
    lines=[]
    if segments:
        merged=linemerge(MultiLineString(segments))
        lines=[list(g.coords) for g in ([merged] if merged.geom_type=='LineString' else merged.geoms)]
    return {'polygons':polygons,'fills':fills,'contours':lines,'areaM2':shape.area,'perimeterM':shape.length,
            'classificationBoundary':'grid-frontier-approximation','interiorEstimated':True}
