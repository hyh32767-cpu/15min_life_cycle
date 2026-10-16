"""测量样本的重建几何验证，无网络、无历史缓存写入。"""
import copy
import math
import json

from core.coord import haversine
from core.time_contour import reconstruct_time_contours
from api.app.models.common import Coord
from api.app.models.api import IsochroneResponse
from api.app.services.isochrone_service import IsochroneService
from api.app.routers.isochrones import _render_report
from api.tests.unit.test_isochrone_service import FakeBaidu


def reconstruct(samples, radii=None):
    return reconstruct_time_contours(samples, radii or {str(b): 800 for b in range(0, 360, 15)},
                                     threshold_s=900, lng=116.4, lat=39.9)


def test_radial_field_produces_closed_threshold_contour_without_mutating_inputs():
    samples = [(b, d, d * 900 / 800) for b in range(0, 360, 15) for d in (200, 600, 800, 1000)]
    before = copy.deepcopy(samples)
    result = reconstruct(samples)
    assert result['sampleCount'] == 96
    assert len(result['contours']) == 1
    line = result['contours'][0]
    assert line[0] == line[-1]
    assert len(line) > 24
    assert all(780 < haversine(116.4, 39.9, c['lng'], c['lat']) < 801 for c in line)
    assert samples == before


def test_measured_time_barrier_changes_contour_without_changing_ray_polygon():
    samples = [(b, d, d * 900 / 800) for b in range(0, 360, 15) for d in (200, 600, 1000)]
    base = reconstruct(samples)
    barrier = reconstruct(samples + [(7.5, 450, 1200)])
    assert base['contours'] != barrier['contours']
    assert min(haversine(116.4, 39.9, c['lng'], c['lat']) for line in barrier['contours'] for c in line) < 450
    assert barrier['classificationBoundary'] == 'ray-polygon'


def test_missing_collinear_and_unbracketed_samples_do_not_invent_boundary():
    for samples in ([], [(0, 200, None)], [(0, 200, 100), (0, 400, 600), (0, 1000, 1200)],
                    [(b, 200, 100) for b in (0, 90, 180, 270)]):
        assert reconstruct(samples)['contours'] == []
    assert reconstruct([(0, 200, math.nan), (90, 200, math.inf)])['sampleCount'] == 0


def test_constraint_clips_open_contours_without_closing_across_missing_evidence():
    samples = [(b, d, d * 900 / 800) for b in range(0, 360, 15) for d in (200, 600, 1000)]
    radii = {str(b): 400 if b < 90 else 800 for b in range(0, 360, 15)}
    lines = reconstruct(samples, radii)['contours']
    assert reconstruct(samples, {**radii, '360': 400})['contours'] == lines
    assert lines and all(line[0] != line[-1] for line in lines)
    for line in lines:
        for c in line:
            lat1, lat2 = math.radians(39.9), math.radians(c['lat'])
            delta = math.radians(c['lng'] - 116.4)
            bearing = math.degrees(math.atan2(math.sin(delta) * math.cos(lat2),
                math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta))) % 360
            lower = int(bearing // 15) * 15
            limit = radii[str(lower)] + (radii[str((lower + 15) % 360)] - radii[str(lower)]) * (bearing - lower) / 15
            assert haversine(116.4, 39.9, c['lng'], c['lat']) <= limit + 80.1


def test_service_reuses_queries_and_publishes_snapshot_reconstruction():
    baidu = FakeBaidu()
    service = IsochroneService(baidu)
    snapshots = []
    response = service.run(Coord(lng=116.4, lat=39.9), threshold_seconds=900,
                           adaptive=True, max_pairs=320, tol_m=25, _on_progress=snapshots.append)
    assert response['status'] == 'complete'
    assert response['reconstruction']['sampleCount'] <= response['pairsUsed']
    assert response['reconstruction']['contours']
    assert all(s['reconstruction']['contours'] for s in snapshots)
    assert snapshots[0]['reconstruction']['sampleCount'] < response['reconstruction']['sampleCount']
    assert IsochroneResponse(**response).model_dump(by_alias=True)['reconstruction'] == response['reconstruction']
    assert json.loads(_render_report(response['taskId'], 'json', response))['reconstruction'] == response['reconstruction']
    assert response['reconstruction']['method'] in _render_report(response['taskId'], 'markdown', response)
    # 不传进度回调也使用同一批探针，不为绘图额外算路。
    other = FakeBaidu()
    IsochroneService(other).run(Coord(lng=116.4, lat=39.9), threshold_seconds=900,
                              adaptive=True, max_pairs=320, tol_m=25)
    assert other.calls == baidu.calls
