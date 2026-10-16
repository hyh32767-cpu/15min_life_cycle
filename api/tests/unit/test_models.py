# -*- coding: utf-8 -*-
import pytest
from pydantic import ValidationError

from api.app.models.common import Coord, Crs, Provenance, SourceKind


def test_coord_accepts_named_bd09():
    c = Coord(lng=116.397, lat=39.916, crs=Crs.BD09)
    assert c.crs == Crs.BD09
    assert c.model_dump()["crs"] == "BD09"


@pytest.mark.parametrize("payload", [
    {"lng": 200.0, "lat": 39.9, "crs": "BD09"},
    {"lng": 116.3, "lat": -91.0, "crs": "BD09"},
    {"lng": 116.3, "lat": 39.9, "crs": "GCJ-02"},
    {"lng": 116.3, "lat": 39.9, "crs": "BD09", "unexpected": 1},
])
def test_coord_rejects_invalid_or_unknown_fields(payload):
    with pytest.raises(ValidationError):
        Coord(**payload)


def test_provenance_requires_source_and_allows_parent_refs():
    p = Provenance(sourceKind="derived", parents=["resp-hash-1"], note="time window")
    assert p.source_kind == SourceKind.DERIVED
    with pytest.raises(ValidationError):
        Provenance(parents=[])
