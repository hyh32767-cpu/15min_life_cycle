"""显式 live 验收：调用本地 API，不读取密钥；重复/反向预览必须零外呼。"""
import argparse
import json
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:18080')
    parser.add_argument('--output', required=True)
    parser.add_argument('--measure', action='store_true', help='显式允许对缺测中心补算')
    args = parser.parse_args()
    # 固定的北京地图验收点，与手机端验收路径一致，不取用户实时定位。
    origin = dict(lng=116.3470131802863, lat=40.08201572910743, crs='BD09')
    destination = dict(lng=116.35633169800562, lat=40.085682252116605, crs='BD09')
    with httpx.Client(base_url=args.base_url, timeout=120) as client:
        def post(path, body):
            response = client.post(path, json=body)
            response.raise_for_status()
            return response.json()
        route = post('/api/routes/walking', dict(origin=origin, destination=destination))
        geometry = route['route']['geometry']
        body = dict(routeGeometry=geometry, thresholdSeconds=900, maxCenters=5, maxPairs=320, cacheOnly=True)
        stages = [('preview', post('/api/route-bands', body))]
        if args.measure:
            for node in stages[0][1]['nodes']:
                if node['status'] != 'complete':
                    measured = post('/api/route-bands', {**body, 'cacheOnly': False, 'centerIndex': node['index']})
                    stages.append((f"measure-{node['index']}", measured))
                    if any('QUOTA_EXCEEDED' in warning or 'RATE_LIMITED' in warning
                           for center in measured['nodes'] for warning in center['warnings']):
                        break
        stages.append(('repeat', post('/api/route-bands', body)))
        stages.append(('reverse', post('/api/route-bands', {**body, 'routeGeometry': list(reversed(geometry))})))
        for name, result in stages:
            if name in {'preview', 'repeat', 'reverse'}:
                assert result['cost']['liveRequests'] == result['cost']['livePairs'] == 0
        assert stages[-1][1]['fills'] == stages[-2][1]['fills']
        payload = {'definition': 'complete sampled outgoing walking circles union; approximate, not detour feasibility',
                   'route': {'durationSeconds': route['route']['durationSeconds'], 'distanceM': route['route']['distanceM']},
                   'stages': [{'name': name, 'result': result} for name, result in stages]}
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(json.dumps([{'stage': name, 'complete': result['completeCount'], 'nodes': len(result['nodes']),
                           'cost': result['cost']} for name, result in stages], ensure_ascii=False))


if __name__ == '__main__':
    main()
