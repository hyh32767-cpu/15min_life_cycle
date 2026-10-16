"""圆盘前沿历史回算与百度底图回放；不发算路请求。"""
from pathlib import Path
import json
import math

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from core.grid_frontier import grid_frontier, frontier_geometry, fit_preview, fit_measured_preview


def main():
    root = Path(__file__).resolve().parents[2]
    out = root / 'output/benchmarks/grid-frontier-disk-20261016'
    out.mkdir(parents=True, exist_ok=True)
    source = json.loads((root / 'output/benchmarks/outside-in-2km-grid100-20261016/e4.json').read_text())
    truth = {(p['eastM'], p['northM']): p['durationSeconds'] for p in source['truthGrid']}
    frames = []
    disk = grid_frontier(lambda ps: [truth[p] for p in ps], half_m=1000,max_pairs=316,on_progress=frames.append)
    # 核心额外发布终态，但它没有新增调用：回放每次调用严格对应一帧。
    if len(frames)>1 and frames[-1]['pairsUsed']==frames[-2]['pairsUsed']:
        frames[-2:]=[frames[-1]]
    square = grid_frontier(lambda ps: [truth[p] for p in ps], half_m=1000,domain_shape='square', max_pairs=440)
    geo = frontier_geometry(disk)
    shape = unary_union([Polygon(p['outer'], p['holes']) for p in geo['polygons']])
    lat, lng = source['summary']['centerLatLngBD09']
    for frame in frames:
        frame['actualContours'] = frontier_geometry(frame)['contours']
        fitter = fit_measured_preview if frame['done'] else fit_preview
        frame['previewContours'] = [[[round((p['lng']-lng)*111320*math.cos(math.radians(lat)), 4),
                                     round((p['lat']-lat)*111320, 4)] for p in line]
                                    for line in fitter({**frame, 'done': False}, lng=lng, lat=lat)]
        frame['displayMethod'] = 'delaunay' if frame['done'] else 'closed-loading-outline'
    summary = {
        'liveRouteApiCalls': 0, 'realApiDurationMeasured': False,
        'domainShape': 'disk', 'radiusM': 1000, 'spacingM': 100,
        'diskMeasured': disk['pairsUsed'], 'diskBatches': len(disk['batches']),
        'squareMeasured': square['pairsUsed'], 'squareBatches': len(square['batches']),
        'diskDomainPoints': disk['domainPoints'], 'squareDomainPoints': square['domainPoints'],
        'gridMistakesWithinDisk': sum(shape.covers(Point(*p)) != (v <= 900)
                                     for p, v in truth.items() if p != (0, 0) and math.hypot(*p) <= 1000),
        'clipped': disk['clipped'], 'interiorEstimated': True, 'previewUsedForAnalysis': False,
        'note': '历史王府井数据回算；圆盘范围小于原正方形，不能将少测位置等同于相同全域精度或实测提速。',
    }
    report = {'summary': summary, 'centerBD09': {'lat': lat, 'lng': lng},
              'result': disk, 'geometryLocalMeters': geo, 'frames': frames}
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    # 底图仅在浏览器通过公开配置取得浏览器AK，不嵌入服务端凭据。
    payload = {'center': {'lat': lat, 'lng': lng}, 'summary': summary, 'frames': frames,
               'finalPolygons': geo['polygons']}
    template = (Path(__file__).with_name('templates') / 'disk-frontier.html').read_text()
    page = template.replace('__FRONTIER_DATA__', json.dumps(payload, ensure_ascii=False))
    (out / 'index.html').write_text(page)
    public = root / 'web/public'
    public.mkdir(exist_ok=True)
    (public / 'frontier-demo.html').write_text(page)
    # 原入口继续可用，原SVG回放和原report.json均保留。
    old = root / 'output/benchmarks/grid-frontier-progress-20261016'
    saved = old / 'index-svg.html'
    if not saved.exists():
        saved.write_text((old / 'index.html').read_text())
    (old / 'index.html').write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="0;url=http://127.0.0.1:5173/frontier-demo.html">
<title>圆盘前沿 · 地图回放</title><p><a href="http://127.0.0.1:5173/frontier-demo.html">打开地图回放</a></p>
<p><a href="index-svg.html">上一版方形范围回放</a></p></html>''')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
