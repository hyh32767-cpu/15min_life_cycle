from api.app.services.baidu_service import BaiduService


def test_real_category_tags_preserved_without_fabricating_missing_tags():
    item = {"uid": "brand", "name": "同仁堂", "location": {"lat": 40.09, "lng": 116.36},
            "tag": "医疗", "detail_info": {"tag": "医疗;药店"}}
    place = BaiduService._place_from_item(item, "live-api")
    assert place.tags == ["医疗", "医疗;药店"]
    assert place.model_dump(by_alias=True)["tags"] == ["医疗", "医疗;药店"]
    assert BaiduService._place_from_detail(item, "live-api").tags == place.tags
    item.pop("tag")
    item["detail_info"] = {"tag": None}
    assert BaiduService._place_from_item(item, "api-cache").tags == []
