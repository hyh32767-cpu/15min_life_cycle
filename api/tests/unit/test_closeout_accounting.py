from core.baidu_client import ApiResult
from api.app.models.common import Coord
from api.tests.unit.test_baidu_service import FakeAdapter, make_service


def test_network_retries_count_in_product_ledger(tmp_path):
    class Retried(FakeAdapter):
        def walking(self, *args, **kwargs):
            result = super().walking(*args, **kwargs)
            result.attempts = 3
            return result
    service = make_service(tmp_path, Retried())
    service.walking_route(Coord(lng=116.33, lat=40.07), Coord(lng=116.34, lat=40.08))
    assert service.ledger.summary().live_requests == 3
    assert service.ledger.summary().pairs == 3


def test_iso_poi_page_budget_marks_incomplete_even_without_unique_limit(tmp_path):
    class FullPage(FakeAdapter):
        def place_search(self, *args, **kwargs):
            return ApiResult(True, 0, 'ok', {'status': 0, 'results': [
                {'uid': str(i), 'name': str(i), 'location': {'lat': 40.07, 'lng': 116.33}} for i in range(20)]})
    service = make_service(tmp_path, FullPage())
    response = service.isochrone_pois(Coord(lng=116.33, lat=40.07), 900, ['药店'], max_pages_per_term=1)
    assert response['retrieval']['truncated']
    assert response['retrieval']['truncationReason'] == 'page_budget'


def test_invalid_poi_coordinates_make_search_incomplete_instead_of_false_empty(tmp_path):
    class InvalidPoi(FakeAdapter):
        def place_search(self, *args, **kwargs):
            return ApiResult(True, 0, 'ok', {'results': [
                {'uid': 'invalid', 'location': {'lat': 'NaN', 'lng': 116.33}},
                {'uid': 'out-of-range', 'location': {'lat': 190, 'lng': 116.33}}, None]})
    service = make_service(tmp_path, InvalidPoi())
    origin = Coord(lng=116.33, lat=40.07)
    for response in [service.corridor_pois([origin, origin], ['小学']),
                     service.isochrone_pois(origin, 900, ['小学'])]:
        assert response['retrieval']['truncated']
        assert response['retrieval']['truncationReason'] == 'invalid_coordinates'


def test_unmeasured_iso_poi_route_is_unknown_not_unreachable(tmp_path):
    service = make_service(tmp_path, FakeAdapter())
    service.travel_matrix = lambda *a, **k: {'cells': []}
    response = service.isochrone_pois(Coord(lng=116.33, lat=40.07), 900, ['药店'])
    assert response['reachable'] == []
    assert response['retrieval']['unknownRoutes'] > 0
    assert all(row['reason'] == 'unknown_route' for row in response['unreachable'])
