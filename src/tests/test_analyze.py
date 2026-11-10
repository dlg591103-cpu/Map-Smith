"""T13–T14 analyze 的用例：缓冲、裁剪、叠加、属性关联。"""

from __future__ import annotations

import math

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from mapsmith.io.models import DataError, DataLayer
from mapsmith.tools.analyze import analyze, buffer_layer, clip_layer, join_table, overlay_layer


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


def _admin_layer(adcodes: list[str], polygons) -> DataLayer:
    gdf = gpd.GeoDataFrame(
        {"adcode": adcodes},
        geometry=list(polygons),
        crs="EPSG:4326",
    )
    return DataLayer(
        kind="admin",
        name="测试边界",
        source="测试构造",
        summary="测试构造边界面图层",
        gdf=gdf,
        crs="EPSG:4326",
    )


def _table_layer_with_rows(rows: list[dict[str, object]]) -> DataLayer:
    """带数据行的假统计表：数据行放在 gdf 字段（join 的正确契约前提）。"""
    df = pd.DataFrame(rows)
    return DataLayer(
        kind="table",
        name="统计表",
        source="测试构造",
        summary="测试构造统计表",
        gdf=df,
        crs=None,
    )


# ---- T13 buffer ----


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
        analyze(_point_layer([(117.18, 34.26)]), "bogus", {})


# ---- T14 clip ----


def test_clip_keeps_points_inside_boundary() -> None:
    points = _point_layer([(116.5, 34.2), (117.5, 34.2), (120.0, 34.2)])
    boundary = _admin_layer(["320300"], [box(116.0, 34.0, 118.0, 35.0)])

    out = clip_layer(points, boundary)

    assert out.meta["op"] == "clip"
    assert out.count == 2  # 边界外 (120, 34.2) 被裁掉
    assert out.kind == "point"
    assert out.crs == "EPSG:4326"


def test_clip_no_intersection_rejected() -> None:
    points = _point_layer([(120.0, 34.2)])
    boundary = _admin_layer(["320300"], [box(116.0, 34.0, 118.0, 35.0)])

    with pytest.raises(DataError, match="无交集"):
        clip_layer(points, boundary)


def test_analyze_clip_requires_by() -> None:
    with pytest.raises(DataError, match="by"):
        analyze(_point_layer([(116.5, 34.2)]), "clip", {})


def test_analyze_clip_rejects_non_layer_by() -> None:
    with pytest.raises(DataError, match="by 必须是 DataLayer"):
        analyze(_point_layer([(116.5, 34.2)]), "clip", {"by": "不是图层"})


# ---- T14 overlay ----


def test_overlay_intersection_produces_overlap() -> None:
    left = _admin_layer(["A"], [box(0.0, 0.0, 1.0, 1.0)])
    right = _admin_layer(["B"], [box(0.5, 0.5, 1.5, 1.5)])

    out = overlay_layer(left, right, how="intersection")

    assert out.meta["op"] == "overlay"
    assert out.meta["how"] == "intersection"
    assert out.count == 1
    assert out.crs == "EPSG:4326"


def test_overlay_invalid_how_rejected() -> None:
    left = _admin_layer(["A"], [box(0.0, 0.0, 1.0, 1.0)])
    right = _admin_layer(["B"], [box(0.5, 0.5, 1.5, 1.5)])

    with pytest.raises(DataError, match="不支持的叠加方式"):
        overlay_layer(left, right, how="bogus")


def test_analyze_overlay_requires_other() -> None:
    with pytest.raises(DataError, match="other"):
        analyze(_admin_layer(["A"], [box(0.0, 0.0, 1.0, 1.0)]), "overlay", {})


# ---- T14 join ----


def test_join_attaches_stats_to_boundary() -> None:
    table = _table_layer_with_rows(
        [{"adcode": "320301", "PM2_5_24h": 88.0}, {"adcode": "320302", "PM2_5_24h": 60.0}]
    )
    boundary = _admin_layer(
        ["320301", "320302"],
        [box(116.0, 34.0, 117.0, 34.5), box(117.0, 34.0, 118.0, 34.5)],
    )

    out = join_table(table, boundary, "adcode")

    assert out.meta["op"] == "join"
    assert out.kind == "admin"
    assert out.count == 2
    assert out.meta["matched_count"] == 2
    assert out.meta["unmatched_count"] == 0
    assert out.meta["value_fields"] == ["PM2_5_24h"]
    assert "PM2_5_24h" in out.gdf.columns
    assert set(out.gdf["PM2_5_24h"]) == {88.0, 60.0}


def test_join_marks_unmatched_boundary() -> None:
    table = _table_layer_with_rows([{"adcode": "320301", "PM2_5_24h": 88.0}])
    boundary = _admin_layer(
        ["320301", "320302"],
        [box(116.0, 34.0, 117.0, 34.5), box(117.0, 34.0, 118.0, 34.5)],
    )

    out = join_table(table, boundary, "adcode")

    assert out.count == 2
    assert out.meta["matched_count"] == 1
    assert out.meta["unmatched_count"] == 1
    assert out.gdf["PM2_5_24h"].isna().sum() == 1


def test_join_with_two_part_key() -> None:
    table = _table_layer_with_rows([{"code": "320301", "PM2_5_24h": 88.0}])
    boundary = _admin_layer(["320301"], [box(116.0, 34.0, 117.0, 34.5)])

    out = join_table(table, boundary, ("code", "adcode"))

    assert out.meta["matched_count"] == 1
    assert out.meta["table_key"] == "code"
    assert out.meta["boundary_key"] == "adcode"


def test_join_table_without_rows_rejected() -> None:
    table = DataLayer(kind="table", name="空统计表", source="测试", summary="无数据", gdf=None)
    boundary = _admin_layer(["320301"], [box(116.0, 34.0, 117.0, 34.5)])

    with pytest.raises(DataError, match="没有携带数据行"):
        join_table(table, boundary, "adcode")


def test_join_missing_key_column_rejected() -> None:
    table = _table_layer_with_rows([{"adcode": "320301", "PM2_5_24h": 88.0}])
    boundary = _admin_layer(["320301"], [box(116.0, 34.0, 117.0, 34.5)])

    with pytest.raises(DataError, match="缺少关联键列"):
        join_table(table, boundary, "不存在的键")


def test_analyze_join_requires_to_and_key() -> None:
    table = _table_layer_with_rows([{"adcode": "320301", "PM2_5_24h": 88.0}])

    with pytest.raises(DataError, match="to"):
        analyze(table, "join", {})
    with pytest.raises(DataError, match="key"):
        analyze(table, "join", {"to": _admin_layer(["320301"], [box(116.0, 34.0, 117.0, 34.5)])})