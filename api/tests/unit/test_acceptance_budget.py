import pytest

from core import baidu_client
from core.baidu_client import ApiResult
from api.app.services.errors import ServiceError
from tools.preflight.economy_server import AcceptanceBudget


def test_acceptance_budget_counts_each_attempt_and_never_exceeds_pairs(monkeypatch):
    attempts = []
    def fake(path, params, **kwargs):
        attempts.append(kwargs)
        return ApiResult(True, 0, 'ok', {})
    monkeypatch.setattr(baidu_client, 'get', fake)
    budget = AcceptanceBudget(requests=2, pairs=10)
    budget.install()
    baidu_client.get('/matrix', {}, kind='matrix', experiment_id='test', n_pairs=6)
    with pytest.raises(ServiceError, match='限定额度'):
        baidu_client.get('/matrix', {}, kind='matrix', experiment_id='test', n_pairs=5)
    assert len(attempts) == 1 and attempts[0]['retries'] == 0
    assert len(budget.calls) == 1


def test_first_quota_failure_stops_same_interface_without_wasting_requests(monkeypatch):
    monkeypatch.setattr(baidu_client, 'get', lambda *args, **kwargs: ApiResult(False, 302, 'quota', {}))
    budget = AcceptanceBudget()
    budget.install()
    baidu_client.get('/place', {}, kind='place_search', experiment_id='test')
    with pytest.raises(ServiceError):
        baidu_client.get('/place', {}, kind='place_search', experiment_id='test')
    assert len(budget.calls) == 1
