"""复用本轮已测九格→单设施基线，只新增三对候选验证，不能冒充全类别验收。"""
import json
import sqlite3
from pathlib import Path

import httpx


def main():
    with sqlite3.connect('file:api/var/cache.db?mode=ro', uri=True) as db:
        candidates = db.execute("SELECT params_json,body_json,response_hash FROM api_cache WHERE interface='matrix_walking' AND fetched_at LIKE '2026-10-12%' ORDER BY fetched_at DESC").fetchall()
    params, body, source_hash = next((json.loads(p), json.loads(b), h) for p, b, h in candidates
                                    if len(json.loads(p)['origins']) == 9 and len(json.loads(p)['destinations']) == 1)
    ids = [f'grid-{index}' for index in range(9)]
    times = [{'fromGrid': ids[index], 'toFacility': 'observed-facility', 'durationSeconds': item['duration']['value'], 'status': 'ok'}
             for index, item in enumerate(body['result'])]
    blind = [index for index, item in enumerate(times) if item['durationSeconds'] > 900]
    assert len(blind) == 1
    lat, lng = params['origins'][blind[0]]
    origin = {'lat': lat, 'lng': lng, 'crs': 'BD09'}
    new_points = [origin, {**origin, 'lat': lat + .0005}, {**origin, 'lng': lng + .0005}]
    with httpx.Client(base_url='http://127.0.0.1:18080', timeout=30) as client:
        response = client.post('/api/travel-matrix', json={'origins': [origin], 'destinations': new_points})
        output = {'scope': 'nine sampled grids / one actual observed existing facility / three hypothetical candidates',
                  'sourceKind': 'live-api+api-cache+user-input', 'baselineHash': source_hash, 'matrixHttp': response.status_code,
                  'notFullFiveCategoryAcceptance': True}
        if response.status_code == 200:
            matrix = response.json()
            before_body = {'thresholdSeconds': 900, 'gridIds': ids, 'facilityIds': ['observed-facility'], 'times': times}
            before = client.post('/api/community/coverage', json=before_body).json()
            candidate_times = [{'fromGrid': ids[blind[0]], 'toFacility': f'candidate-{cell["toIndex"]}',
                                'durationSeconds': cell['durationSeconds'], 'status': cell['status']} for cell in matrix['cells']]
            output.update({'before': before, 'candidates': candidate_times, 'matrixTraceId': matrix['traceId'],
                           'matrixResponseHashes': matrix.get('responseHashes', [])})
            for k in (1, 2, 3):
                verified = [time for time in candidate_times[:k] if time['status'] == 'ok' and time['durationSeconds'] is not None and time['durationSeconds'] <= 900]
                output[f'greedy{k}'] = {'knownCovered': before['coveredCount'] + int(bool(verified)),
                                        'gain': int(bool(verified)), 'note': 'only one uncovered sampled grid; extra candidates cannot add another grid'}
            first = candidate_times[0]
            after = client.post('/api/community/coverage', json={**before_body,
                'newFacilityId': first['toFacility'], 'newFacilityTimes': [first]}).json()
            output['after'] = after
            assert after['delta']['before'] == before['coveredCount']
            output['positiveImprovement'] = after['delta']['after'] > after['delta']['before']
            repeated = client.post('/api/travel-matrix', json={'origins': [origin], 'destinations': new_points}).json()
            output['repeatCacheHit'] = repeated['cacheHit']
        else:
            output['error'] = response.json()
    Path('docs/acceptance-economy-improvement.json').write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
