"""缓存优先的沿线采样等时带，单次补测一个中心以便渐进展示。"""
from core.route_band import route_centers, union_circles
from core.grid_frontier import VERSION as ALGORITHM_VERSION
from datetime import datetime, timezone

from ..models.common import Coord
from ..storage.api_cache import canonical_json, sha256_text
from ..storage.derived_cache import derived_key
from ..storage.ledger import new_trace_id
from .baidu_service import to_baidu_bd09
from .errors import ServiceError


class RouteBandService:
    def __init__(self, isochrones):
        self.isochrones = isochrones

    def run(self, request):
        points = [to_baidu_bd09(point)[0].model_dump(by_alias=True) for point in request.route_geometry]
        sampling = route_centers(points, request.max_centers)
        centers = sampling['centers']
        if request.center_index is not None and request.center_index >= len(centers):
            raise ServiceError('VALIDATION_ERROR', '采样位置已改变，请重新加载沿途范围', http_status=422)
        trace = new_trace_id()
        per_center = min(376, request.max_pairs // len(centers))
        nodes, circles, hashes = [], [], set()
        for index, center in enumerate(centers):
            live = not request.cache_only and index == request.center_index
            circle = self.isochrones.get_task_status(request.task_ids[index]) if index in request.task_ids else None
            if circle and (circle.get('origin') != center or circle.get('thresholdSeconds') != request.threshold_seconds
                           or circle.get('algorithmVersion') != ALGORITHM_VERSION):
                raise ServiceError('VALIDATION_ERROR', '位置已改变，请重新加载沿途范围', http_status=422)
            if circle and circle.get('status') == 'complete':
                expiry = circle.get('expiresAt')
                if not expiry or datetime.fromisoformat(expiry.replace('Z', '+00:00')) <= datetime.now(timezone.utc):
                    circle = None
            if circle is None:
                circle = self.isochrones.run(Coord(**center), threshold_seconds=request.threshold_seconds,
                                             frontier=True, l2_first=True,
                                             max_pairs=per_center, cache_only=not live, trace_id=trace)
            status = circle['status']
            nodes.append({'index': index, 'origin': center, 'status': status,
                          'taskId': circle['taskId'] if circle.get('backgroundStatus') != 'degraded' else None,
                          'backgroundStatus': circle.get('backgroundStatus'),
                          'previewContours': circle.get('frontier', {}).get('previewContours', []),
                          'cached': status == 'complete' and (not live or circle['cacheHit'] or circle['sourceKind'] == 'api-cache'),
                          'failedBearings': circle['failedBearings'],
                          'skippedBearings': circle['skippedBearings'],
                          'warnings': circle.get('warnings', [])})
            if status == 'complete':
                circles.append(circle)
                hashes.update(circle.get('upstreamResponseHashes', []))
        route_hash = sha256_text(canonical_json(points))
        key = derived_key(algorithm='route-band', algorithm_version='route-band-v1:' + ALGORITHM_VERSION,
                          input_hashes={'route': route_hash},
                          params={'thresholdSeconds': request.threshold_seconds, 'maxCenters': request.max_centers,
                                  'maxPairs': request.max_pairs, 'centers': centers,
                                  'completeIndices': [n['index'] for n in nodes if n['status'] == 'complete'],
                                  'upstreamResponseHashes': sorted(hashes)})
        cache = self.isochrones.cache
        stored = cache.get(key) if cache else None
        fresh = stored is not None and not stored.is_expired(ttl_s=86400)
        shape = stored.result if fresh else union_circles(circles)
        if cache and not fresh and circles:
            cache.put(key=key, algorithm='route-band', algorithm_version='route-band-v1:' + ALGORITHM_VERSION,
                      dependencies={'routeHash': route_hash, 'upstreamResponseHashes': sorted(hashes)}, result=shape)
        cost = self.isochrones.baidu.ledger.summary(trace_id=trace)
        return {'routeHash': route_hash, 'thresholdSeconds': request.threshold_seconds,
                'displayContours': [line for circle in circles for line in circle.get('reconstruction', {}).get('contours', [])],
                'nodes': nodes, **sampling, **shape, 'completeCount': len(circles),
                'status': 'complete' if len(circles) == len(nodes) else 'partial' if circles else 'unknown',
                'sourceKind': 'derived', 'upstreamResponseHashes': sorted(hashes),
                'algorithmVersion': 'route-band-v1:' + ALGORITHM_VERSION,
                'cost': {'liveRequests': cost.live_requests, 'cacheHits': cost.cache_hits, 'pairs': cost.pairs,
                         'livePairs': self.isochrones.baidu.ledger.live_pairs(trace)},
                'cacheHit': fresh, 'traceId': trace}
