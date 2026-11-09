"""T13 analyze：缓冲区的用例（5 km 缓冲在度量投影下成立）。"""

from __future__ import annotations

import math

import geopandas as gpd
import pytest
from shapely.geometry import Point

from mapsmith.io.models import DataError, DataLayer
from mapsmith.tools.analyze import analyze, buffer_layer


def _point_layer(coords: list[tuple[float, float]], values: list[float] | None = None) -> DataLayer:
    gdf = gpd.GeoDataFrame(
        {"v": values if values is not None else [1.0] * len(coords)},
        geometry=[Point(x, y) for x, y in coords],
        crs="EPSG:4326",
    )
    return DataLayer(
        kind="point",
        name="测试点",
        source="测试构造",
        summary="测试构造点图层",
        gdf=gdf,
        crs="EPSG:4326",
    )


def test_buffer_five_km_area_is_circle_of_radius_5km() -> None:
    out = buffer_layer(_point_layer([(117.18, 34.26)]), 5.0)

    assert out.crs == "EPSG:4326"
    assert out.kind == "admin"  # 缓冲面按面处理
    assert out.count == 1
    area_km2 = out.meta["buffered_area_km2"]
    assert area_km2 == pytest.approx(math.pi * 5.0**2, rel=0.05)
    assert out.meta["op"] == "buffer"
    assert out.meta["buffer_km"] == 5.0


def test_buffer_distance_is_meters_not_degrees() -> None:
    """若误在经纬度下缓冲，面积会是度²（天文数字）；这里必须是几十 km²。"""
    out = buffer_layer(_point_layer([(117.18, 34.26)]), 5.0)

    assert 70.0 < out.meta["buffered_area_km2"] < 85.0


def test_buffer_keeps_attributes_and_feature_count() -> None:
    out = buffer_layer(_point_layer([(117.10, 34.20), (117.30, 34.40)], [1.0, 2.0]), 5.0)

    assert out.count == 2
    assert "v" in out.gdf.columns
    assert out.meta["feature_count"] == 2


def test_buffer_nonpositive_distance_rejected() -> None:
    for bad in (0, -1):
        with pytest.raises(DataError, match="缓冲距离"):
            buffer_layer(_point_layer([(117.18, 34.26)]), bad)


def test_buffer_layer_without_geometry_rejected() -> None:
    layer = DataLayer(kind="table", name="统计表", source="测试", summary="无几何", gdf=None)

    with pytest.raises(DataError, match="没有几何"):
        buffer_layer(layer, 5.0)


def test_analyze_dispatches_buffer() -> None:
    out = analyze(_point_layer([(117.18, 34.26)]), "buffer", {"distance_km": 5})

    assert out.meta["op"] == "buffer"


def test_analyze_buffer_requires_distance() -> None:
    with pytest.raises(DataError, match="distance_km"):
        analyze(_point_layer([(117.18, 34.26)]), "buffer", {})


def test_analyze_unknown_op_rejected() -> None:
    with pytest.raises(DataError, match="暂不支持"):
        analyze(_point_layer([(117.18, 34.26)]), "clip", {})