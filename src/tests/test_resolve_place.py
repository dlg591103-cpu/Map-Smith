"""T05 `resolve_place` 的用例。"""

from __future__ import annotations

import json

import pytest

from mapsmith.io.models import AmbiguousPlace, DataError, PlaceNotFound
from mapsmith.tools.resolve_place import resolve_place


def test_xuzhou_returns_adcode_and_bbox() -> None:
    result = resolve_place("徐州", online=False)

    assert result.adcode == "320300"
    assert result.full_name == "徐州市"
    assert result.bbox == (116.3571, 33.7123, 118.6687, 34.9758)
    assert "实测" in result.summary


def test_full_name_with_suffix_matches() -> None:
    result = resolve_place("徐州市", online=False)

    assert result.adcode == "320300"


def test_district_name_matches_under_city(tmp_path) -> None:
    """「徐州市铜山区」同时包含市名与区名，必须取更具体的区级候选。"""
    index = {
        "version": "test",
        "places": [
            {
                "name": "徐州",
                "full_name": "徐州市",
                "adcode": "320300",
                "level": "city",
                "parent": "江苏省",
                "bbox": [116.2, 34.1, 118.6, 34.9],
            },
            {
                "name": "铜山区",
                "full_name": "铜山区",
                "adcode": "320312",
                "level": "district",
                "parent": "徐州市",
                "bbox": [116.9, 34.2, 117.4, 34.6],
            },
        ],
    }
    path = tmp_path / "places.json"
    path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    result = resolve_place("徐州市铜山区", index_path=path, online=False)

    assert result.adcode == "320312"
    assert result.parent == "徐州市"


def test_unknown_place_raises_instead_of_guessing() -> None:
    with pytest.raises(PlaceNotFound):
        resolve_place("不存在的地名", online=False)


def test_ambiguous_name_raises_with_candidates(tmp_path) -> None:
    index = {
        "version": "test",
        "places": [
            {"name": "同名区", "full_name": "同名区", "adcode": "111111", "level": "district", "parent": "甲市"},
            {"name": "同名区", "full_name": "同名区", "adcode": "222222", "level": "district", "parent": "乙市"},
        ],
    }
    path = tmp_path / "places.json"
    path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(AmbiguousPlace) as excinfo:
        resolve_place("同名区", index_path=path, online=False)

    assert len(excinfo.value.candidates) == 2
    assert {item["adcode"] for item in excinfo.value.candidates} == {"111111", "222222"}


def test_missing_bbox_without_network_reports_clearly(tmp_path) -> None:
    index = {
        "version": "test",
        "places": [
            {"name": "无范围市", "full_name": "无范围市", "adcode": "333333", "level": "city", "parent": "某省"}
        ],
    }
    path = tmp_path / "places.json"
    path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(DataError) as excinfo:
        resolve_place("无范围市", index_path=path, online=False)

    assert "无法取得区域范围" in str(excinfo.value)