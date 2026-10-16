"""五地历史实测受限查询实验；零网络、不改历史数据库，生成可复核对比图。"""
from __future__ import annotations

import hashlib
import argparse
import json
import math
from pathlib import Path
import sqlite3
import time

import contourpy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
import numpy as np
from shapely.geometry import Polygon, Point, box, mapping
from shapely.ops import unary_union

from core.coord import dest_at
from experiments.e4_sampling.outside_in_grid import outside_in

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/benchmarks/outside-in-five-20261016'
CASES = [('shanghai', '上海·陆家嘴', '内洞与江岸'), ('yiwu', '义乌·稠城', '窄深凹槽'),
         ('harbin', '哈尔滨·道外', '铁路切割与碎片'), ('zunyi', '遵义·老城', '桥廊与复通'),
         ('chongqing', '重庆·解放碑', '山城与复通带')]
SECOND_CASES = [('guilin', '桂林·东西巷', '江岸与窄凹'), ('chengdu', '成都·九眼桥', '规则路网与桥廊'),
                ('guangzhou', '广州·上下九', '老城密路网'), ('wuhan', '武汉·江汉路', '滨江商圈'),
                ('shenzhen', '深圳·华强北', '规则街区与大路切割')]
AXIS = list(range(-500, 501, 50))


def coordinate(center, x, y):
    # 精确复用历史grid_points逐行生成方式；不能用另一种投影的6位坐标强行匹配。
    lat, lng = dest_at(center[1], center[0], 0, y)
    return tuple(round(v, 6) for v in dest_at(lng, lat, 90, x))


def array(field):
    return np.ma.masked_invalid(np.array([[field.get((x, y), np.nan)
                                           for x in AXIS] for y in AXIS]))


def contours(field, level):
    return contourpy.contour_generator(x=AXIS, y=AXIS, z=array(field),
        name='serial', corner_mask=False).lines(level)


def geometry(field, level=900):
    cg = contourpy.contour_generator(x=AXIS, y=AXIS, z=array(field),
        name='serial', corner_mask=False, fill_type='OuterOffset')
    points, offsets = cg.filled(-0.01, level)
    polygons = []
    for pts, off in zip(points, offsets):
        rings = [pts[a:b] for a, b in zip(off, off[1:])]
        if rings:
            polygons.append(Polygon(rings[0], rings[1:]).buffer(0))
    return unary_union(polygons)


def legacy_geometry(data, half=500):
    radii = sorted((float(b), r) for b, r in data['radii'].items())
    polar = lambda b, r: (r*math.sin(math.radians(b)), r*math.cos(math.radians(b)))
    shape = Polygon([polar(b, r) for b, r in radii]).buffer(0)

    def wedge(b, width, inner, outer):
        angles = np.linspace(b-width, b+width, 17)
        return Polygon([polar(a, outer) for a in angles] + [polar(a, inner) for a in angles[::-1]]).buffer(0)

    for p in data.get('pockets') or []:
        if p.get('gap') and p.get('outer'):
            shape = shape.union(wedge(p['bearing'], p.get('wedge_deg') or 5, p['gap'][1], p['outer']))
    for p in data.get('interior_gaps') or []:
        gap = p.get('gap', [])
        if len(gap) == 2 and gap[1]-gap[0] >= 20:
            shape = shape.difference(wedge(p['bearing'], p.get('wedge_deg') or 1.2, *gap))
    return shape.intersection(box(-half, -half, half, half))


def score(pred, truth, keys):
    tp = fp = fn = tn = unknown = 0
    for p in keys:
        value = pred(p)
        if value is None:
            unknown += 1
            continue
        actual = truth[p] <= 900
        tp += bool(value and actual)
        fp += bool(value and not actual)
        fn += bool(not value and actual)
        tn += bool(not value and not actual)
    return dict(points=len(keys), evaluated=tp+fp+fn+tn, unknown=unknown, fp=fp, fn=fn,
                iou=round(tp/max(1, tp+fp+fn), 4), f1=round(2*tp/max(1, 2*tp+fp+fn), 4))


def plot_lines(ax, field, color, lw=1.8, level=900, style='-'):
    for line in contours(field, level):
        ax.plot(line[:, 0], line[:, 1], color=color, lw=lw, ls=style)


def plot_shape(ax, shape, color, lw=2, half=500):
    if shape.is_empty:
        return
    for poly in [shape] if shape.geom_type == 'Polygon' else shape.geoms:
        if poly.geom_type != 'Polygon':
            continue
        for ring in [poly.exterior, *poly.interiors]:
            a = np.array(ring.coords)
            # clipped polygon内的外框线不是等时线，绘图时去掉贴框段。
            for p, q in zip(a, a[1:]):
                if any(abs(p[i]) >= half-.01 and abs(q[i]) >= half-.01 for i in (0, 1)):
                    continue
                ax.plot([p[0], q[0]], [p[1], q[1]], color=color, lw=lw)


def backdrop(ax, field):
    ax.contourf(AXIS, AXIS, array(field), levels=[-.01, 900, 100000],
                colors=['#dce8fc', '#f4f5f8'], alpha=.8)
    ax.set(xlim=(-550, 550), ylim=(-550, 550), aspect='equal',
           xlabel='东西偏移 / 米', ylabel='南北偏移 / 米')
    ax.set_facecolor('#e8ebef')
    ax.add_patch(plt.Rectangle((-500, -500), 1000, 1000, fill=False, ec='#a5afbc', ls=':', lw=1))
    ax.scatter([0], [0], marker='*', s=90, c='#162238', edgecolors='white', zorder=9)
    ax.set_xticks([-500, -250, 0, 250, 500])
    ax.set_yticks([-500, -250, 0, 250, 500])
    ax.grid(alpha=.18)
    ax.spines[['top', 'right']].set_visible(False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', choices=['first', 'second'], default='first')
    args = parser.parse_args()
    global OUT
    selected_cases = CASES if args.group == 'first' else SECOND_CASES
    if args.group == 'second':
        OUT = ROOT / 'output/benchmarks/outside-in-five-second-20261016'
    OUT.mkdir(parents=True, exist_ok=True)
    font_manager.fontManager.addfont('/System/Library/Fonts/Hiragino Sans GB.ttc')
    plt.rcParams.update({'font.family': 'Hiragino Sans GB', 'axes.unicode_minus': False,
                         'font.size': 10, 'figure.facecolor': 'white', 'savefig.facecolor': 'white'})
    db = ROOT / 'experiments/logs/cache.db'
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    connection = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    cases = []
    overview, overview_axes = plt.subplots(3, 2, figsize=(13, 17))
    for index, (slug, name, terrain) in enumerate(selected_cases):
        path = ROOT / f'experiments/results/e10_boundary/e10x_{slug}.json'
        data = json.loads(path.read_text())
        center = data['center']
        raw = {(lat, lng): t for lat, lng, t in connection.execute(
            "SELECT d_lat,d_lng,duration_s FROM walk_times WHERE o_lat=? AND o_lng=? AND mode='walking'",
            (round(center[0], 6), round(center[1], 6)))}
        truth = {(x, y): raw.get(coordinate(center, x, y)) for x in AXIS for y in AXIS}
        assert all(v is not None and math.isfinite(v) and v >= 0 for v in truth.values())
        start = time.perf_counter()
        # oracle只对算法主动请求的格点开放，完整truth从不传入引擎。
        result = outside_in(lambda x, y: truth.get((x, y)), budget=300, thresholds=(900,))
        runtime = time.perf_counter() - start
        joint = outside_in(lambda x, y: truth.get((x, y)), budget=300)
        predicted = result['prediction']
        reference = geometry(truth)
        new_shape = geometry(predicted)
        old_shape = legacy_geometry(data)
        all_keys = [p for p in truth if p != (0, 0)]
        heldout = [p for p in all_keys if p not in result['observed']]
        new_class = lambda p: predicted[p] <= 900 if p in predicted else None
        old_class = lambda p: old_shape.covers(Point(*p))
        boundary_new = [Point(*p) for line in contours(predicted, 900) for p in line]
        ref_lines = contours(truth, 900)
        from shapely.geometry import MultiLineString
        ref_line = MultiLineString(ref_lines) if ref_lines else None
        distances = [p.distance(ref_line) for p in boundary_new] if ref_line else []
        symmetric_distances = list(distances)
        new_lines = contours(predicted, 900)
        if new_lines and ref_lines:
            new_line = MultiLineString(new_lines)
            symmetric_distances.extend(Point(*p).distance(new_line) for line in ref_lines for p in line)
        summary = {'slug': slug, 'name': name, 'terrain': terrain, 'centerLatLngBD09': center,
            'uniqueQueries': result['queryCount'], 'validQueries': sum(v is not None for v in result['observed'].values()),
            'fullGridQueriesExcludingAnchor': 440,
            'querySavingVsFullGrid': round(1-result['queryCount']/440, 4),
            'offlineComputeSeconds': round(runtime, 4), 'liveApiCalls': 0,
            'budgetLimited': result['budgetExhausted'], 'unresolvedGridPositions': len(result['unresolved']),
            'threeThresholdQueries': joint['queryCount'], 'threeThresholdBudgetLimited': joint['budgetExhausted'],
            'knownWindowSideM': 1000, 'requestedWindowSideM': 1100, 'unknownOuterGridPositions': 88,
            'newGridAllPoints': score(new_class, truth, all_keys), 'oldRayAllPoints': score(old_class, truth, all_keys),
            'newGridHeldout': score(new_class, truth, heldout), 'oldRayOnSameHeldout': score(old_class, truth, heldout),
            'newAreaIoU': round(new_shape.intersection(reference).area/max(1, new_shape.union(reference).area), 4),
            'oldAreaIoU': round(old_shape.intersection(reference).area/max(1, old_shape.union(reference).area), 4),
            'boundarySymmetricVertexDistanceP90M': round(float(np.percentile(symmetric_distances, 90)), 2) if symmetric_distances else None,
            'clipped15min': any(truth[x, y] <= 900 for x in AXIS for y in AXIS if abs(x) == 500 or abs(y) == 500),
            'legacyStoredDirections': len(data['radii']), 'legacyRecordedPairsNotFinalCost': data.get('pairs_used'),
            'legacyScope': 'stored ray main polygon plus recorded pockets minus interior gaps; excludes R2 Delaunay union',
            'sourceFile': str(path.relative_to(ROOT)),
            'evaluationCaution': 'all-point score includes sampled points; heldout excludes new queries only, not guaranteed independent of historical ray construction'}
        summary['jointThresholdScores'] = {}
        for threshold in (300,600,900):
            missing = [p for p in all_keys if p not in joint['observed']]
            summary['jointThresholdScores'][str(threshold)] = {
                'allPointsMistakes': sum((truth[p] <= threshold) != (joint['prediction'][p] <= threshold) for p in all_keys),
                'newUnqueriedPoints': len(missing),
                'unqueriedMistakes': sum((truth[p] <= threshold) != (joint['prediction'][p] <= threshold) for p in missing)}
        # 原历史非格点OD给新方法额外检查，避免在同一50米参考场上的满分被误解为绝对精度。
        # 这些点可能用于过旧射线构建，所以只保证没有参与新方法采样。
        grid_coordinate_keys = {coordinate(center,x,y) for x,y in truth}
        off_grid = {}
        for (lat,lng), duration in raw.items():
            if (lat,lng) in grid_coordinate_keys or duration is None or duration <= 0:
                continue
            x = (lng-center[1])*111320*math.cos(math.radians(lat))
            y = (lat-center[0])*111320
            if -500 < x < 500 and -500 < y < 500:
                off_grid[x,y] = duration
        def off_grid_new(p):
            x,y = p
            x0,y0 = math.floor(x/50)*50, math.floor(y/50)*50
            s,t = (x-x0)/50,(y-y0)/50
            knots = [(x0,y0),(x0+50,y0),(x0+50,y0+50),(x0,y0+50)]
            if any(k not in predicted for k in knots):
                return None
            a,b,c,d = (predicted[k] for k in knots)
            return a*(1-s)*(1-t)+b*s*(1-t)+c*s*t+d*(1-s)*t <= 900
        summary['newOffGridHistoricalChecks'] = score(off_grid_new,off_grid,list(off_grid))
        summary['oldOnSameOffGridChecks'] = score(old_class,off_grid,list(off_grid))
        summary['offGridCaution'] = 'not used by new grid; may have been used by stored old rays; spatially clustered, not random independent validation'
        fig, axs = plt.subplots(1, 3, figsize=(16.5, 6.1))
        for ax in axs:
            backdrop(ax, truth)
        plot_lines(axs[0], truth, '#26374c', 2)
        axs[0].scatter(*np.array(list(truth)).T, s=5, color='#64748b', alpha=.55)
        axs[0].set_title('历史50米完整网格参考\n441个位置；中心为逻辑锚点', fontweight='bold')
        if not ref_lines:
            for ax in axs:
                ax.text(.5,.48,'窗口内未观察到15分钟边界\n不能视为完整等时圈',
                        transform=ax.transAxes,ha='center',va='center',fontsize=11,color='#526783')
        plot_lines(axs[1], truth, '#26374c', 1.4, style='--')
        plot_shape(axs[1], old_shape, '#e67c24', 2.3)
        axs[1].set_title(f'原射线主边界＋已记录复通/间隔带\n面积IoU {summary["oldAreaIoU"]:.3f} · {len(data["radii"])}向', fontweight='bold')
        axs[2].clear()
        backdrop(axs[2], predicted)
        if not ref_lines:
            axs[2].text(.5,.48,'窗口内未观察到15分钟边界\n不能视为完整等时圈',
                        transform=axs[2].transAxes,ha='center',va='center',fontsize=11,color='#526783')
        plot_lines(axs[2], predicted, '#2462f2', 2.2)
        plot_lines(axs[2], truth, '#26374c', 1.2, style='--')
        samples = np.array(list(result['observed']))
        axs[2].scatter(samples[:, 0], samples[:, 1], s=9, c='#245ad1', alpha=.55, zorder=5)
        if result['unresolved']:
            uv = np.array([[1 if (x, y) in result['unresolved'] else 0 for x in AXIS] for y in AXIS])
            axs[2].contourf(AXIS, AXIS, uv, levels=[.5, 1.5], colors=['#f4b458'],alpha=.2)
        mistakes = np.array([p for p,t in off_grid.items() if off_grid_new(p) != (t<=900)])
        if len(mistakes):
            axs[2].scatter(mistakes[:,0],mistakes[:,1],s=23,marker='x',c='#d63642',lw=.9,zorder=8)
        axs[2].set_title(f'外向内自适应网格 · {result["queryCount"]}次受限查询\n非格点检查F1 {summary["newOffGridHistoricalChecks"]["f1"]:.3f} · {len(mistakes)}个错点', fontweight='bold')
        fig.suptitle(f'{name}｜{terrain}｜15分钟等时圈对照', fontsize=17, fontweight='bold', y=.98)
        fig.legend(handles=[Line2D([0],[0],color='#26374c',ls='--',label='完整网格15分钟参考'),
            Line2D([0],[0],color='#e67c24',label='历史射线结果'), Line2D([0],[0],color='#2462f2',label='新网格15分钟线'),
            Line2D([0],[0],marker='o',ls='',color='#245ad1',label='新方案查询位置'),
            Line2D([0],[0],marker='x',ls='',color='#d63642',label='未参与新采样的历史错点')], loc='lower center', ncol=5, bbox_to_anchor=(.5,.065))
        fig.text(.5,.033,'历史实测离线重跑，零新增API；灰色外围50米缺数据。边框不是等时线；淡橙色为尚未解决的风险区域。',ha='center',fontsize=9,color='#596579')
        fig.text(.5,.008,'非格点检查没有用于新方案采样，但部分点曾用于原射线构建；原射线对照不含R2场融合，不能视为完整算法公平排名。',ha='center',fontsize=8.5,color='#596579')
        fig.tight_layout(rect=(0,.16,1,.92))
        fig.savefig(OUT / f'{slug}.png', dpi=180)
        fig.savefig(OUT / f'{slug}.svg')
        plt.close(fig)
        ax = overview_axes.flat[index]
        backdrop(ax, truth)
        plot_lines(ax, truth, '#26374c', 1.2, style='--')
        plot_shape(ax, old_shape, '#e67c24', 1.8)
        plot_lines(ax, predicted, '#2462f2', 2)
        if len(mistakes):
            ax.scatter(mistakes[:,0],mistakes[:,1],s=12,marker='x',c='#d63642',alpha=.75,zorder=8)
        ax.set_title(f'{name} · {result["queryCount"]} / 440次查询\n新方案非格点检查F1 {summary["newOffGridHistoricalChecks"]["f1"]:.3f} · {len(mistakes)}个错点',fontweight='bold')
        if not ref_lines:
            ax.text(.5,.48,'窗口内未观察到15分钟边界\n不能视为完整等时圈',
                    transform=ax.transAxes,ha='center',va='center',fontsize=11,color='#526783')
        record = {'summary': summary, 'phases': result['phases'],
            'jointThreeThresholdRun': {'phases':joint['phases'],'samples':[{'eastM':x,'northM':y,'durationSeconds':v} for (x,y),v in sorted(joint['observed'].items())],
                'contours':{str(t):[line.tolist() for line in contours(joint['prediction'],t)] for t in (300,600,900)}},
            'samples': [{'eastM':x,'northM':y,'durationSeconds':v,'coordLatLngBD09':coordinate(center,x,y)} for (x,y),v in sorted(result['observed'].items())],
            'leaves': result['leaves'], 'unresolvedPositions': sorted(result['unresolved']),
            'truthGrid': [{'eastM':x,'northM':y,'durationSeconds':v} for (x,y),v in sorted(truth.items())],
            'offGridHistoricalChecks':[{'eastM':x,'northM':y,'durationSeconds':v} for (x,y),v in sorted(off_grid.items())],
            'predictedGrid': [{'eastM':x,'northM':y,'durationSeconds':v,'kind':'measured' if (x,y) in result['observed'] else 'origin-anchor' if (x,y)==(0,0) else 'interpolated'} for (x,y),v in sorted(predicted.items())],
            'newContoursLocalMeters': {'900': [line.tolist() for line in contours(predicted,900)]},
            'referenceContoursLocalMeters': [line.tolist() for line in contours(truth,900)],
            'oldClippedGeometryLocalMeters': mapping(old_shape)}
        (OUT / f'{slug}.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
        cases.append(summary)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    connection.close()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == digest, '历史数据库发生变更'
    overview_axes.flat[5].axis('off')
    overview_axes.flat[5].text(.03,.95,'实测历史数据，离线受限查询\n\n黑虚线：完整50米网格参考\n橙线：历史射线主边界＋复通/间隔带\n蓝线：新外向内网格15分钟线\n红叉：未参与新采样的历史检查错点\n\n比较限于共同1×1公里区域。\n外围缺测，不伪造完整闭合。\n\n非格点检查可能参与过旧射线构建；\n旧对照不含R2场融合，不能作公平排名。\n\n查询数是离线探针需求，\n不是本次真实API调用数或耗时。',va='top',fontsize=12,linespacing=1.5,color='#35445a')
    overview.suptitle('五地等时圈｜外向内网格与历史射线对照',fontsize=20,fontweight='bold',y=.995)
    overview.tight_layout(rect=(0,0,1,.975),h_pad=3)
    overview.savefig(OUT/'overview.png',dpi=170)
    plt.close(overview)
    report = {'experiment':'outside-in-grid-five-v1','group':args.group,'liveApiCalls':0,'sourceDbSha256':digest,
              'fixedParameters':{'budget':300,'nearSeconds':120,'spacingM':50,'evaluationHalfM':500,'primaryThresholds':[900],'secondaryThresholds':[900,600,300]},
              'cases':cases,'sourceDatabaseReadOnly':True}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    import html
    table_rows = ''.join(f'<tr><td>{html.escape(c["name"])}</td><td>{c["uniqueQueries"]}</td>'
        f'<td>{c["querySavingVsFullGrid"]:.1%}</td><td>{c["newOffGridHistoricalChecks"]["f1"]:.3f}</td>'
        f'<td>{c["newOffGridHistoricalChecks"]["fp"]+c["newOffGridHistoricalChecks"]["fn"]} / {c["newOffGridHistoricalChecks"]["points"]}</td>'
        f'<td>{c["threeThresholdQueries"]}</td></tr>' for c in cases)
    sections = ''.join(f'<section id="{c["slug"]}"><h2>{html.escape(c["name"])}</h2>'
        f'<a href="{c["slug"]}.png"><img src="{c["slug"]}.png" alt="{html.escape(c["name"])}算法对比图"></a>'
        f'<p><a href="{c["slug"]}.svg">矢量图</a> · <a href="{c["slug"]}.json">逐点记录</a></p></section>' for c in cases)
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>五地外向内网格实验</title>'
    page += '<style>body{font:16px/1.7 system-ui,sans-serif;color:#26344a;background:#f5f7fb;margin:0}main{max-width:1400px;margin:auto;padding:28px}section,header{background:white;border-radius:16px;padding:24px;margin-bottom:24px}h1{font-size:28px}h2{font-size:22px}img{width:100%;height:auto}a{color:#245ad1}table{border-collapse:collapse;width:100%}th,td{text-align:left;border-bottom:1px solid #e4e9f1;padding:10px}aside{background:#fff3dc;padding:16px;border-radius:10px}nav a{margin-right:20px}small{color:#5a687d}@media(max-width:600px){main{padding:10px}section,header{padding:16px}table{font-size:12px}th,td{padding:5px}}</style><main><header><h1>五地等时圈：外向内网格与历史射线对照</h1>'
    page += '<p>历史真实百度测值，离线受限查询；本次没有新增API调用。主对照为15分钟，50米基础网格，300点预算。</p>'
    page += '<aside>共同数据范围只有1×1公里，外围50米未知，五地均有可达范围触边。参考格网上吻合不等于真实边界精确：下表单列历史非格点检查。部分检查点曾用于旧射线构建，且旧图不含R2场融合，不可当作完整算法公平排名。</aside>'
    page += '<table><thead><tr><th>地点</th><th>主圈查询位置</th><th>相对440点节省</th><th>新方案非格点F1</th><th>非格点错点/检查数</th><th>三层查询位置</th></tr></thead><tbody>'+table_rows+'</tbody></table>'
    page += '<p>黑虚线为完整网格参考，橙线为旧射线，蓝线为新网格，红叉为新方法在未采样历史非格点上的错点。查询位置数是离线需求，不能换称真实请求次数或耗时。</p><nav>'
    page += ''.join(f'<a href="#{c["slug"]}">{html.escape(c["name"])}</a>' for c in cases)
    page += '</nav></header>'+sections+'<p><a href="report.json">汇总数据</a> · <a href="overview.png">总览图</a></p></main></html>'
    (OUT/'index.html').write_text(page)


if __name__ == '__main__':
    main()
