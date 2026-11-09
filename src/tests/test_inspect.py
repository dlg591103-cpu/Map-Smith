"""T11 数据体检与两档插值判定的用例。"""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

from mapsmith.io.models import DataLayer, FieldMissing
from mapsmith.tools.inspect import DataProfile, profile_points

FIELD = "PM2_5_24h"
STUDY_BBOX = (116.2, 34.1, 118.6, 34.9)


def _study_area() -> gpd.GeoDataFrame:
    minx, miny, maxx, maxy = STUDY_BBOX
    return gpd.GeoDataFrame(geometry=[box(minx, miny, maxx, maxy)], crs="EPSG:4326")


def _point_layer(coords: list[tuple[float, float]], values: list[float | None]) -> DataLayer:
    gdf = gpd.GeoDataFrame(
        {FIELD: values},
        geometry=[Point(x, y) for x, y in coords],
        crs="EPSG:4326",
    )
    return DataLayer(
        kind="point",
        name="徐州测试站点",
        source="测试构造",
        summary="测试构造点图层",
        gdf=gdf,
        crs="EPSG:4326",
    )


# 9 个站点集中在主城区，覆盖度不足，用于复现「徐州 9 站降级」。
CITY_CENTER_COORDS = [
    (117.10, 34.22),
    (117.15, 34.25),
    (117.20, 34.22),
    (117.12, 34.28),
    (117.18, 34.30),
    (117.22, 34.27),
    (117.08, 34.26),
    (117.24, 34.24),
    (117.14, 34.32),
]
CITY_CENTER_VALUES = [118.0, 96.0, 88.0, 75.0, 66.0, 58.0, 52.0, 45.0, 32.0]


def test_nine_stations_degrade_to_points() -> None:
    profile = profile_points(_point_layer(CITY_CENTER_COORDS, CITY_CENTER_VALUES), study_area=_study_area())

    assert isinstance(profile, DataProfile)
    assert profile.n_valid == 9
    assert profile.total == 9
    assert profile.completeness == 1.0
    assert profile.decision == "degrade"
    assert profile.cover is not None and profile.cover < 0.5
    assert profile.value_max == 118.0
    assert profile.value_min == 32.0


def test_reason_lines_are_exactly_three_and_cover_all_three_items() -> None:
    profile = profile_points(_point_layer(CITY_CENTER_COORDS, CITY_CENTER_VALUES), study_area=_study_area())

    assert len(profile.reason_lines) == 3
    assert "站数" in profile.reason_lines[0]
    assert "覆盖度" in profile.reason_lines[1]
    assert "结论" in profile.reason_lines[2]


def test_twelve_well_spread_stations_use_idw() -> None:
    coords = [
        (116.30, 34.15),
        (117.20, 34.15),
        (118.50, 34.15),
        (116.30, 34.50),
        (117.20, 34.50),
        (118.50, 34.50),
        (116.30, 34.85),
        (117.20, 34.85),
        (118.50, 34.85),
        (116.80, 34.30),
        (117.80, 34.30),
        (117.80, 34.70),
    ]
    profile = profile_points(
        _point_layer(coords, [float(i + 30) for i in range(len(coords))]),
        study_area=_study_area(),
    )

    assert profile.n_valid == 12
    assert profile.decision == "idw"
    assert profile.cover is not None and profile.cover >= 0.5


def test_two_stations_reject_the_field() -> None:
    profile = profile_points(
        _point_layer([(117.10, 34.22), (117.20, 34.30)], [50.0, 60.0]),
        study_area=_study_area(),
    )

    assert profile.n_valid == 2
    assert profile.decision == "reject"
    assert "放弃该指标" in profile.reason_lines[2]


def test_missing_study_area_degrades_instead_of_passing() -> None:
    coords = [
        (116.30, 34.15),
        (118.50, 34.15),
        (116.30, 34.85),
        (118.50, 34.85),
        (117.20, 34.50),
        (116.80, 34.30),
        (117.80, 34.30),
        (117.80, 34.70),
        (117.00, 34.60),
        (117.40, 34.40),
        (117.60, 34.20),
        (116.60, 34.50),
    ]
    profile = profile_points(_point_layer(coords, [55.0] * len(coords)), study_area=None)

    assert profile.decision == "degrade"
    assert profile.cover is None
    assert "无法计算" in profile.reason_lines[1]


def test_null_values_are_excluded_from_valid_count() -> None:
    values = CITY_CENTER_VALUES[:-2] + [None, None]
    profile = profile_points(_point_layer(CITY_CENTER_COORDS, values), study_area=_study_area())

    assert profile.n_valid == 7
    assert profile.total == 9
    assert profile.completeness == pytest.approx(7 / 9)


def test_unknown_field_raises_field_missing() -> None:
    with pytest.raises(FieldMissing) as excinfo:
        profile_points(
            _point_layer(CITY_CENTER_COORDS, CITY_CENTER_VALUES),
            field_name="PM10_24h",
            study_area=_study_area(),
        )

    assert "PM10_24h" in str(excinfo.value)
    assert FIELD in str(excinfo.value)


def test_indicator_field_is_inferred_when_lon_lat_exist() -> None:
    """带经纬度列的点图层，未指定字段时应选指标列，而不是把 lon/lat 当候选。"""
    gdf = gpd.GeoDataFrame(
        {
            "lon": [x for x, _ in CITY_CENTER_COORDS],
            "lat": [y for _, y in CITY_CENTER_COORDS],
            FIELD: CITY_CENTER_VALUES,
        },
        geometry=[Point(x, y) for x, y in CITY_CENTER_COORDS],
        crs="EPSG:4326",
    )
    layer = DataLayer(
        kind="point",
        name="徐州测试站点",
        source="测试构造",
        summary="测试构造点图层",
        gdf=gdf,
        crs="EPSG:4326",
    )

    profile = profile_points(layer, study_area=_study_area())

    assert profile.meta["field"] == FIELD