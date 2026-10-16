import pytest
from fastapi.testclient import TestClient
from api.app.main import app
from api.app.routers import insights
from api.app.services.errors import ServiceError


@pytest.fixture(autouse=True)
def reset_insights():
    insights.CACHE.clear();insights.CALLS.clear()
    yield
    insights.CACHE.clear();insights.CALLS.clear()


def test_insight_recomputes_score_and_reuses_order_independent_cache(monkeypatch):
    calls=[]
    def fake(prompt,facts,max_tokens=350):
        calls.append(facts);return {'summary':'本次养老覆盖偏弱，可优先关注养老服务。'}
    monkeypatch.setattr(insights,'model_json',fake)
    client=TestClient(app)
    services=[dict(id='pharmacy',covered=9,total=9,facilities=5),dict(id='elderly',covered=0,total=9,facilities=0)]
    first=client.post('/api/community/insight',json={'services':services})
    assert first.status_code==200 and first.json()['score']==50
    assert '采样点' in first.json()['scope']
    second=client.post('/api/community/insight',json={'services':list(reversed(services))})
    assert second.json()['cacheHit'] and len(calls)==1
    assert set(calls[0][0])=={'id','label','covered','total','facilities'}


def test_unknown_and_invalid_statistics_cannot_be_scored():
    client=TestClient(app)
    for item in [dict(id='pharmacy',covered=None,total=9,facilities=0),dict(id='injected',covered=0,total=9,facilities=0),dict(id='pharmacy',covered=9,total=9,facilities=0)]:
        assert client.post('/api/community/insight',json={'services':[item]}).status_code==422


def test_failed_model_does_not_cache_and_safe_error_does_not_echo_secret(monkeypatch):
    def fake(*args):
        raise ServiceError('INSIGHT_TIMEOUT','解读用时较长，请稍后再试',http_status=504)
    monkeypatch.setattr(insights,'complete',fake)
    response=TestClient(app).post('/api/community/insight',json={'services':[dict(id='pharmacy',covered=1,total=9,facilities=1)]})
    assert response.status_code==504 and response.json()['error']['code']=='INSIGHT_TIMEOUT'
    assert not insights.CACHE


def test_route_only_returns_validated_categories_and_times(monkeypatch):
    calls=[]
    def fake(prompt,facts,max_tokens):
        calls.append(facts)
        return dict(tasks=[dict(categoryId='药店',serviceMinutes=3),dict(categoryId='快递',serviceMinutes=None)],totalMinutes=30,extraMinutes=None,keepOrder=True)
    monkeypatch.setattr(insights,'model_json',fake)
    client=TestClient(app)
    request={'text':'买药再取快递，三十分钟内到终点'}
    result=client.post('/api/route/intent',json=request)
    assert result.status_code==200 and result.json()['totalMinutes']==30
    assert result.json()['tasks'][0]['categoryId']=='药店'
    assert client.post('/api/route/intent',json=request).json()['cacheHit']
    assert calls==[request]


def test_invented_route_categories_and_conflicting_budget_are_rejected(monkeypatch):
    client=TestClient(app)
    for response in [dict(tasks=[dict(categoryId='不存在的地方')]),dict(tasks=[dict(categoryId='药店')],totalMinutes=20,extraMinutes=5)]:
        monkeypatch.setattr(insights,'model_json',lambda *args,r=response:r)
        assert client.post('/api/route/intent',json={'text':'测试需求'}).status_code==422
