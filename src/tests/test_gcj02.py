"""GCJ-02 纠偏的用例。"""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Point, Polygon

from mapsmith.io.gcj02 import gcj02_to_wgs84, out_of_china, transform_geodataframe, wgs84_to_gcj02

# 天安门附近的 WGS84 坐标；GCJ-02 偏移量应在数百米量级。
BEIJING_WGS84 = (116.3912, 39.9073)


def test_offset_direction_and_order_of_magnitude() -> None:
    gcj_lon, gcj_lat = wgs84_to_gcj02(*BEIJING_WGS84)

    # GCJ-02 在北京一带通常向东北偏移约 0.006° 左右。
    assert gcj_lon > BEIJING_WGS84[0]
    assert gcj_lat > BEIJING_WGS84[1]
    assert 0.001 < gcj_lon - BEIJING_WGS84[0] < 0.02
    assert 0.001 < gcj_lat - BEIJING_WGS84[1] < 0.02


def test_round_trip_returns_original_within_centimetres() -> None:
    gcj = wgs84_to_gcj02(*BEIJING_WGS84)
    back = gcj02_to_wgs84(*gcj)

    assert back[0] == pytest.approx(BEIJING_WGS84[0], abs=1e-7)
    assert back[1] == pytest.approx(BEIJING_WGS84[1], abs=1e-7)


def test_outside_china_is_unchanged() -> None:
    assert out_of_china(-73.9, 40.7) is True
    assert gcj02_to_wgs84(-73.9, 40.7) == (-73.9, 40.7)
    assert wgs84_to_gcj02(-73.9, 40.7) == (-73.9, 40.7)


def test_transform_geodataframe_shifts_polygon_vertices() -> None:
    polygon = Polygon([(117.0, 34.2), (117.2, 34.2), (117.2, 34.4), (117.0, 34.4)])
    gdf = gpd.GeoDataFrame(geometry=[polygon], crs="EPSG:4326")

    converted, record = transform_geodataframe(gdf, direction="gcj02_to_wgs84")

    assert record["direction"] == "gcj02_to_wgs84"
    assert record["feature_count"] == 1
    assert converted.crs == "EPSG:4326"
    original_x = gdf.geometry.iloc[0].bounds[0]
    converted_x = converted.geometry.iloc[0].bounds[0]
    assert converted_x != pytest.approx(original_x, abs=1e-9)
    # 原对象不被修改。
    assert gdf.geometry.iloc[0].bounds[0] == pytest.approx(original_x)


def test_point_geometry_is_shifted() -> None:
    gdf = gpd.GeoDataFrame(geometry=[Point(117.1, 34.2)], crs="EPSG:4326")

    converted, _ = transform_geodataframe(gdf)

    point = converted.geometry.iloc[0]
    assert (point.x, point.y) != pytest.approx((117.1, 34.2), abs=1e-9)


def test_missing_crs_is_rejected() -> None:
    gdf = gpd.GeoDataFrame(geometry=[Point(117.1, 34.2)])

    with pytest.raises(ValueError):
        transform_geodataframe(gdf)