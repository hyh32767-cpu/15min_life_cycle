"""社区专项 live 验收：临时账本/缓存、脱敏统计，不覆盖先前成功证据。"""
import hashlib
import json
import os
from pathlib import Path
import tempfile


def main():
    from api.app.config import Settings
    from api.app.models.common import Coord
    from api.app.services.baidu_service import BaiduService
    from api.app.services.isochrone_service import IsochroneService
    from api.app.storage.derived_cache import DerivedCache
    from api.app.services.errors import ServiceError
    research = Path('experiments/logs/calls.db')
    before = hashlib.sha256(research.read_bytes()).hexdigest() if research.exists() else None
    output = {'sample': '北京回龙观小区', 'origin': {'lng': 116.362946, 'lat': 40.090935, 'crs': 'BD09'},
              'categories': {}, 'heatLayers': {}, 'historicalLedgerUnchanged': None}
    with tempfile.TemporaryDirectory(prefix='shunshou-community-') as temp:
        for variable, filename in [('LEDGER_DB', 'ledger.db'), ('CACHE_DB', 'cache.db'), ('DERIVED_DB', 'derived.db')]:
            os.environ[variable] = str(Path(temp) / filename)
        service = BaiduService(Settings.from_env())
        origin = Coord(**output['origin'])
        for category in ['菜市场', '药店', '小学']:
            try:
                result = service.corridor_pois([origin, origin], [category], window_radius_m=1800,
                    corridor_buffer_m=1800, max_pages_per_window=5, max_unique=100)
                output['categories'][category] = {'status': 'unknown' if result['retrieval']['truncated'] else 'ready',
                    'facilities': len(result['pois']), 'retrieval': result['retrieval']}
            except ServiceError as error:
                output['categories'][category] = {'status': 'unknown', 'errorCode': error.code}
        iso = IsochroneService(service, cache=DerivedCache(service.settings.derived_db))
        for threshold in [300, 600, 900]:
            first = iso.run(origin, threshold_seconds=threshold, max_pairs=64)
            summary = service.ledger.summary()
            repeat = iso.run(origin, threshold_seconds=threshold, max_pairs=64)
            after = service.ledger.summary()
            output['heatLayers'][str(threshold)] = {'status': first['status'], 'pairs': first['pairsUsed'],
                'failedBearings': first['failedBearings'], 'skippedBearings': first['skippedBearings'],
                'repeatCacheHit': repeat['cacheHit'], 'repeatLiveRequests': after.live_requests - summary.live_requests,
                'sameRadii': first['radiiM'] == repeat['radiiM']}
        summary = service.ledger.summary()
        output['accounting'] = {'liveRequests': summary.live_requests, 'cacheHits': summary.cache_hits, 'pairs': summary.pairs, 'errors': summary.errors}
    output['historicalLedgerUnchanged'] = before == (hashlib.sha256(research.read_bytes()).hexdigest() if research.exists() else None)
    path = Path('docs/acceptance-community-live.json')
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
