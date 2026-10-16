import math
import time
import pytest

from shapely import union_all
from shapely.geometry import Point, Polygon

from core.baidu_client import ApiResult
from core.coord import haversine
from core.route_band import route_centers, union_circles
from api.app.models.api import RouteBandRequest
from api.app.models.common import Coord
from api.app.services.isochrone_service import IsochroneService
from api.app.services.route_band_service import RouteBandService
from api.app.storage.derived_cache import DerivedCache
from api.tests.unit.test_baidu_service import FakeAdapter, make_service


@pytest.fixture(autouse=True)
def no_network_pacing(monkeypatch):
    from api.app.services import grid_frontier_service as gs
    monkeypatch.setattr(gs.PACER, 'acquire', lambda cost: None)


def measure_center(band, request, index):
    result = band.run(RouteBandRequest(**request, cacheOnly=False, centerIndex=index))
    for _ in range(500):
        node = result['nodes'][index]
        if node['backgroundStatus'] != 'running':
            return result
        time.sleep(.01)
        result = band.run(RouteBandRequest(**request, taskIds={index: node['taskId']}))
    raise AssertionError('fake grid worker did not finish')


def geometry():
    return [dict(lng=116.33 + i * .004, lat=40.07, crs='BD09') for i in range(9)]


def shape(result):
    return union_all([Polygon([(p['lng'], p['lat']) for p in ring]) for ring in result['fills']])


def circle(x, y=0, radius=111320, status='complete'):
    return dict(origin=dict(lng=x, lat=y), status=status,
                radiiM={str(b): radius for b in (0, 90, 180, 270)})


def test_centers_use_actual_vertices_and_reverse_without_resampling():
    points = geometry()
    forward = route_centers(points)
    backward = route_centers(list(reversed(points)))
    assert len(forward['centers']) == 5
    assert all(p in points for p in forward['centers'])
    assert backward['centers'] == list(reversed(forward['centers']))
    assert forward['maxGapM'] > 0
    assert len(route_centers([points[0], points[0]])['centers']) == 1


def test_union_excludes_partial_and_does_not_bridge_disconnected_circles():
    overlapping = shape(union_circles([circle(0), circle(1), circle(8, status='partial')]))
    assert math.isclose(overlapping.area, 3.5, rel_tol=.001)
    assert not overlapping.covers(Point(8, 0))
    separate = union_circles([circle(0), circle(4)])
    assert len(separate['fills']) == 2
    assert not shape(separate).covers(Point(2, 0))


def test_union_preserves_holes_for_single_ring_map_polygons():
    circles = [circle(2 * math.cos(i * math.pi / 4), 2 * math.sin(i * math.pi / 4),
                      1.3 * 111320) for i in range(8)]
    result = union_circles(circles)
    assert len(result['boundaries']) == 2
    assert not shape(result).covers(Point(0, 0))
    assert shape(result).covers(Point(2, 0))


def test_frontier_union_uses_analysis_polygon_and_preserves_holes():
    ring = lambda ps: [dict(lng=x, lat=y, crs='BD09') for x,y in ps]
    measured = dict(status='complete', radiiM={}, frontier={'polygons': [
        {'outer':ring([(0,0),(4,0),(4,4),(0,4)]), 'holes':[ring([(1,1),(3,1),(3,3),(1,3)])]}]},
        reconstruction={'contours':[ring([(0,0),(4,4)])]})
    result = shape(union_circles([measured]))
    assert result.area == 12 and not result.covers(Point(2,2))
    assert result.covers(Point(.5,.5))


class MeasuredAdapter(FakeAdapter):
    def routematrix(self, origins, destinations, *, experiment_id='api'):
        self.calls.append(('routematrix', len(origins), len(destinations)))
        items = [{'duration': {'value': haversine(a[1], a[0], b[1], b[0]) * 900 / 800},
                  'distance': {'value': haversine(a[1], a[0], b[1], b[0])}}
                 for a in origins for b in destinations]
        return ApiResult(True, 0, 'ok', {'status': 0, 'result': items}, latency_ms=1)


def service(tmp_path):
    adapter = MeasuredAdapter()
    baidu = make_service(tmp_path, adapter)
    return RouteBandService(IsochroneService(baidu, cache=DerivedCache(str(tmp_path / 'derived.db')))), adapter, baidu


def test_preview_is_readonly_and_incremental_measurement_reuses_reverse(tmp_path):
    band, adapter, _ = service(tmp_path)
    request = dict(routeGeometry=geometry())
    empty = band.run(RouteBandRequest(**request))
    assert empty['status'] == 'unknown' and not empty['fills'] and not adapter.calls
    assert empty['cost']['livePairs'] == 0
    for index in range(len(empty['nodes'])):
        result = measure_center(band, request, index)
        assert result['completeCount'] == index + 1
        assert result['nodes'][index]['status'] == 'complete'
    calls = list(adapter.calls)
    repeat = band.run(RouteBandRequest(**request))
    reverse = band.run(RouteBandRequest(routeGeometry=list(reversed(geometry()))))
    assert repeat['completeCount'] == reverse['completeCount'] == 5
    assert repeat['cost']['liveRequests'] == reverse['cost']['liveRequests'] == 0
    assert shape(repeat).equals(shape(reverse))
    assert adapter.calls == calls


def test_expired_circle_does_not_leave_stale_band(tmp_path):
    import sqlite3
    band, adapter, baidu = service(tmp_path)
    first = measure_center(band, dict(routeGeometry=geometry()), 0)
    assert first['fills']
    with sqlite3.connect(baidu.settings.cache_db) as db:
        db.execute("UPDATE api_cache SET expires_at='2000-01-01T00:00:00+00:00'")
    with sqlite3.connect(str(tmp_path / 'derived.db')) as db:
        db.execute("UPDATE derived_cache SET result_json=json_set(result_json, '$.expiresAt', '2000-01-01T00:00:00+00:00')")
    calls = list(adapter.calls)
    preview = band.run(RouteBandRequest(routeGeometry=geometry()))
    assert not preview['fills'] and preview['completeCount'] == 0
    assert adapter.calls == calls


def test_small_budget_does_not_paint_incomplete_circle(tmp_path):
    band, _, _ = service(tmp_path)
    result = measure_center(band, dict(routeGeometry=geometry(), maxPairs=40), 0)
    assert result['completeCount'] == 0 and not result['fills']
    assert result['cost']['livePairs'] <= 8
    assert 'frontier_budget_exhausted' in result['nodes'][0]['warnings']


def test_directed_matrix_cells_reuse_subsets_and_order(tmp_path):
    adapter = FakeAdapter()
    baidu = make_service(tmp_path, adapter)
    a, b, c = [Coord(**p) for p in geometry()[:3]]
    original = baidu.travel_matrix([a], [b, c])
    reordered = baidu.travel_matrix([a], [c, b])
    assert [cell['durationSeconds'] for cell in reordered['cells']] == [569, 568]
    assert reordered['responseHashes'] == original['responseHashes']
    assert len(adapter.calls) == 1
    assert baidu.peek_matrix([b], [a]) is None
    baidu.travel_matrix([a], [a, b])
    assert adapter.calls[-1] == ('routematrix', 1, 1)


def test_invalid_whole_batch_cache_cannot_bypass_cell_validation(tmp_path):
    baidu = make_service(tmp_path)
    a, b = [Coord(**p) for p in geometry()[:2]]
    baidu.cache.put(interface='matrix_walking', interface_version='v2', crs='BD09',
        params={'origins': [[a.lat, a.lng]], 'destinations': [[b.lat, b.lng]], 'mode': 'walking'},
        body={'status': 0, 'result': [{'duration': {'value': True}, 'distance': {'value': 1}}]},
        status=0, ttl_s=3600)
    assert baidu.peek_matrix([a], [b])['cells'][0]['durationSeconds'] is None
    assert baidu.peek_matrix([a], [b])['cells'][0]['status'] == 'error'


def test_route_band_http_requires_explicit_single_center_live_request(hermetic_app):
    client, baidu = hermetic_app
    request = dict(routeGeometry=geometry())
    response = client.post('/api/route-bands', json=request)
    assert response.status_code == 200
    assert response.json()['cost']['liveRequests'] == 0
    assert not baidu.adapter.calls
    assert client.post('/api/route-bands', json={**request, 'cacheOnly': False}).status_code == 422
    assert client.post('/api/route-bands', json={**request, 'maxCenters': 2, 'centerIndex': 4}).status_code == 422
    assert client.post('/api/route-bands', json={**request, 'thresholdSeconds': 0}).status_code == 422
