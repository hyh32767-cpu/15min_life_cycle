import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.app.models.api import ReportExportRequest
from api.app.routers.isochrones import _render_report, isochrone_report, export_report


def test_json_export_retains_version_boundary_and_provenance_without_private_request():
    payload = {
        'status': 'partial', 'sourceKind': 'api-cache', 'thresholdSeconds': 900,
        'radiiM': {'0': 600}, 'failedBearings': [90],
        'report': {'algorithmVersion': 'm2-ray-bisect-v3', 'approxAreaM2': None},
        'upstreamResponseHashes': ['response-hash'],
        'privateRequest': {'credential': 'must-not-export'},
    }
    text = _render_report('test-report', 'json', payload)
    report = json.loads(text)
    assert report['algorithmVersion'] == 'm2-ray-bisect-v3'
    assert report['radiiM'] == {'0': 600}
    assert report['upstreamResponseHashes'] == ['response-hash']
    assert report['approxAreaM2'] is None
    assert 'must-not-export' not in text


def _completed_task():
    return {
        'status': 'complete', 'backgroundStatus': 'completed',
        'expiresAt': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        'radiiM': {'0': 500, '90': 700}, 'report': {'effectiveBearings': 2},
        'warnings': ['adaptive_resolution_limited', 'upstream:SERVICE_BUSY'],
        'pairsUsed': 294, 'cacheHit': False,
    }


def test_uncached_completed_task_report_and_export_keep_measured_boundary():
    payload = _completed_task()
    service = SimpleNamespace(cache=None, get_task_status=lambda _: payload)
    report = isochrone_report('task', service)
    exported = export_report(ReportExportRequest(reportId='task', format='json'), service)
    assert report['radiiM'] == json.loads(exported.content)['radiiM'] == payload['radiiM']
    assert report['warnings'] == payload['warnings']
    assert report['cacheHit'] is False
    assert report['pairsUsed'] == 0  # 读取不新增探针
    assert payload['pairsUsed'] == 294


@pytest.mark.parametrize('change', [
    {'backgroundStatus': 'running'}, {'status': 'degraded'},
    {'report': None}, {'expiresAt': '2000-01-01T00:00:00+00:00'},
    {'expiresAt': None}, {'expiresAt': 'invalid'},
])
def test_report_does_not_promote_unfinished_estimated_or_expired_task(change):
    payload = {**_completed_task(), **change}
    service = SimpleNamespace(cache=None, get_task_status=lambda _: payload)
    with pytest.raises(HTTPException) as exc:
        isochrone_report('task', service)
    assert exc.value.status_code == 404


def test_persistent_report_keeps_cache_provenance():
    record = SimpleNamespace(result=_completed_task(), dependencies={'upstreamResponseHashes': ['hash']})
    service = SimpleNamespace(cache=SimpleNamespace(get_by_task=lambda _: record))
    report = isochrone_report('task', service)
    assert report['cacheHit'] is True
    assert 'derived-cache-hit:ledger-cost-0' in report['warnings']
    exported = export_report(ReportExportRequest(reportId='task', format='json'), service)
    assert json.loads(exported.content)['upstreamResponseHashes'] == ['hash']
