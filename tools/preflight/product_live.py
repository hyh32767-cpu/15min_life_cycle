"""受控的真实链路验收：独立临时缓存/账本，只输出脱敏指标。"""
import json
import os
from pathlib import Path
import tempfile
import time


def main():
    from api.app.config import Settings
    from api.app.models.api import PlanRequest
    from api.app.services.baidu_service import BaiduService
    from api.app.services.planning_service import PlanningService
    from api.app.services.isochrone_service import IsochroneService
    from api.app.storage.derived_cache import DerivedCache
    from api.app.routers.replan import create_replan
    from api.app.models.api import ReplanRequest
    from api.app.models.domain import PlaceRef
    from api.app.models.common import Coord
    with tempfile.TemporaryDirectory(prefix='shunshou-live-') as temp:
        os.environ['LEDGER_DB'] = str(Path(temp) / 'ledger.db')
        os.environ['CACHE_DB'] = str(Path(temp) / 'cache.db')
        os.environ['DERIVED_DB'] = str(Path(temp) / 'derived.db')
        service = BaiduService(Settings.from_env())
        initial = service.ledger.summary()
        start = service.search_locations('回龙观小区', '北京')[0][0]
        home = service.search_locations('龙泽苑', '北京')[0][0]
        walk = service.walking_route(start.navi_coord or start.coord, home.navi_coord or home.coord)
        corridor = service.corridor_pois([Coord.model_validate(point) for point in walk['route']['geometry']], ['药店'],
            corridor_buffer_m=600, window_radius_m=800, window_spacing_m=1800,
            max_pages_per_window=1, max_unique=6, detail_limit=1)
        places = [PlaceRef.model_validate(item['place']) for item in corridor['pois'][:2]]
        if len(places) < 2:
            raise RuntimeError('沿途检索不足两处，不用替代地点伪造验收')
        coords = [start.navi_coord or start.coord, home.navi_coord or home.coord,
                  *[p.navi_coord or p.coord for p in places]]
        ids = ['S', 'H', 'P1', 'P2']
        matrix = service.travel_matrix(coords, coords)
        cells = [{"from": ids[c['fromIndex']], "to": ids[c['toIndex']],
                  "durationSeconds": c['durationSeconds'], "distanceM": c['distanceM'],
                  "status": c['status'], "sourceKind": c['sourceKind']}
                 for c in matrix['cells'] if c['fromIndex'] != c['toIndex']]
        tasks = [{"id": f"T{i+1}", "options": [{"placeId": f"P{i+1}", "serviceSeconds": 60}]} for i in range(2)]
        request = PlanRequest.model_validate({"startId": 'S', "endId": 'H',
            "departureSeconds": 64800, "deadlineSeconds": 72000,
            "tasks": tasks, "travelTimes": cells})
        plan = PlanningService().plan(request)
        assert plan['status'] == 'ready'
        best = plan['alternatives'][0]
        first = best['stops'][0]
        remaining_place = best['stops'][1]['placeId']
        replan_payload = {"tasks": tasks, "completedTaskIds": [first['taskId']],
            "currentNodeId": first['placeId'], "endId": 'H', "currentTimeSeconds": first['finishSeconds'],
            "deadlineSeconds": 72000, "travelTimes": cells}
        closed = create_replan(ReplanRequest.model_validate({**replan_payload,
            "events": [{"id": 'acceptance-close', "type": 'close_place', "targetId": remaining_place}]}))
        recovered = create_replan(ReplanRequest.model_validate(replan_payload))
        assert closed['status'] == 'infeasible' and recovered['status'] == 'ready'
        iso_service = IsochroneService(service, cache=DerivedCache(service.settings.derived_db))
        before_iso = service.ledger.summary()
        t0 = time.perf_counter()
        iso = iso_service.run(coords[2], threshold_seconds=900, max_pairs=64)
        iso_elapsed = time.perf_counter() - t0
        after_first = service.ledger.summary()
        repeat = iso_service.run(coords[2], threshold_seconds=900, max_pairs=64)
        after_repeat = service.ledger.summary()
        assert repeat['radiiM'] == iso['radiiM']
        assert after_repeat.live_requests == after_first.live_requests
        if iso['status'] in {'complete', 'partial'}:
            assert repeat['cacheHit'] and repeat['pairsUsed'] == 0
        output = {
            "sample": "北京回龙观小区→龙泽苑", "routeSeconds": walk['route']['durationSeconds'],
            "routeDistanceM": walk['route']['distanceM'], "geometryPoints": len(walk['route']['geometry']),
            "retrievedPoiCount": len(corridor['pois']), "retrieval": corridor['retrieval'],
            "planStatus": plan['status'], "planFinishSeconds": best['finishSeconds'],
            "replanClosed": closed['status'], "replanRecovered": recovered['status'],
            "isoStatus": iso['status'], "isoRays": len(iso['radiiM']),
            "isoFailedBearings": iso['failedBearings'], "isoSkippedBearings": iso['skippedBearings'],
            "isoPairs": iso['pairsUsed'], "isoSeconds": round(iso_elapsed, 2),
            "isoLiveRequests": after_first.live_requests - before_iso.live_requests,
            "repeatLiveRequests": after_repeat.live_requests - after_first.live_requests,
            "repeatCacheHit": repeat['cacheHit'], "repeatPairs": repeat['pairsUsed'],
            "totalLiveRequests": after_repeat.live_requests - initial.live_requests,
            "totalCacheHits": after_repeat.cache_hits - initial.cache_hits,
            "totalPairs": after_repeat.pairs - initial.pairs,
        }
        path = Path('docs/acceptance-live.json')
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
