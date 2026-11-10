"""T22 第一段 ui.py 的用例：build_spec / compute_breaks / 空间聚合 / run_render / PDF / 上传 CRS。"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import pytest  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402

from mapsmith.io.models import CrsNotDeclared, DataError  # noqa: E402
from mapsmith.io.uploads import ensure_crs, parse_upload  # noqa: E402
from mapsmith.spec import MapSpec  # noqa: E402
from mapsmith.ui import (  # noqa: E402
    RenderResult,
    aggregate_points_to_admin,
    build_spec,
    compute_breaks,
    run_render,
)

BREAKS = [40.0, 50.0, 60.0, 70.0, 90.0]


def make_fields(map_type: str, *, n: int = 5, breaks=None, **overrides) -> dict:
    data = dict(
        title="徐州市 PM2.5 24 小时均值分布图（2026-11-01）",
        map_type=map_type,
        adcode="320300",
        bbox=(116.2, 34.1, 118.6, 34.9),
        field="pm25",
        method="quantile",
        n=n,
        breaks=list(breaks if breaks is not None else BREAKS),
        palette_scheme="YlOrRd",
        palette_reverse=False,
        data_source_note="数据来源：全国城市空气质量实时发布平台（quotsoft.net），更新时间 2026-11-01",
        crs="EPSG:4490",
        notes=[],
    )
    data.update(overrides)
    return data


def make_polygon_gdf(values, crs="EPSG:4326") -> gpd.GeoDataFrame:
    geoms = [box(116.2 + i * 0.4, 34.1, 116.5 + i * 0.4, 34.5) for i in range(len(values))]
    return gpd.GeoDataFrame({"pm25": list(values)}, geometry=geoms, crs=crs)


def make_point_gdf(values, crs="EPSG:4326") -> gpd.GeoDataFrame:
    n = len(values)
    xs = [116.5 + i * 0.35 for i in range(n)]
    ys = [34.25 + (i % 3) * 0.2 for i in range(n)]
    return gpd.GeoDataFrame(
        {"pm25": list(values)},
        geometry=[Point(x, y) for x, y in zip(xs, ys)],
        crs=crs,
    )


def _assert_chinese_font(report) -> None:
    font = report.layout.font
    assert font, "渲染未加载中文字体"
    assert any(k in font for k in ("Noto", "CJK", "Hei", "YaHei", "Han")), f"字体 {font!r} 非中文字体"


def _assert_pdf(path) -> None:
    assert path.exists()
    assert path.stat().st_size > 1024
    assert path.read_bytes()[:4] == b"%PDF"


# --- build_spec ---


def test_build_spec_valid_produces_mapspec() -> None:
    spec = build_spec(make_fields("choropleth"))
    assert isinstance(spec, MapSpec)
    assert spec.map_type == "choropleth"
    assert spec.classification is not None
    assert spec.classification.n == 5
    assert spec.classification.breaks == BREAKS
    assert spec.layers[0].field == "pm25"


def test_build_spec_breaks_count_mismatch_raises_readable_error() -> None:
    with pytest.raises(DataError, match="断点数量 3 与级数 5 不匹配"):
        build_spec(make_fields("choropleth", n=5, breaks=[40, 50, 60]))


def test_build_spec_unsupported_map_type_raises() -> None:
    with pytest.raises(DataError, match="buffer / overlay 尚未实现"):
        build_spec(make_fields("buffer", breaks=[40, 50], n=2))


def test_build_spec_missing_title_raises() -> None:
    with pytest.raises(DataError, match="图名不能为空"):
        build_spec(make_fields("point", title=""))


def test_build_spec_invalid_method_raises() -> None:
    with pytest.raises(DataError, match="分级方法"):
        build_spec(make_fields("point", method="kmeans"))


# --- compute_breaks ---


def test_compute_breaks_returns_n_breaks() -> None:
    breaks = compute_breaks([30, 45, 55, 65, 80, 90, 100, 110], "quantile", 4)
    assert len(breaks) == 4
    assert all(b is not None for b in breaks)


# --- aggregate_points_to_admin ---


def test_aggregate_points_to_admin_mean_per_polygon() -> None:
    admin = gpd.GeoDataFrame(
        {"name": ["A", "B"]},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
        crs="EPSG:4326",
    )
    points = gpd.GeoDataFrame(
        {"pm25": [30.0, 40.0, 100.0]},
        geometry=[Point(0.5, 0.5), Point(0.5, 0.6), Point(1.5, 0.5)],
        crs="EPSG:4326",
    )
    result = aggregate_points_to_admin(admin, points, "pm25")
    assert result["pm25"].tolist()[0] == pytest.approx(35.0)  # (30+40)/2
    assert result["pm25"].tolist()[1] == pytest.approx(100.0)


def test_aggregate_points_to_admin_polygon_without_points_is_nan() -> None:
    admin = gpd.GeoDataFrame(
        {"name": ["A", "B"]},
        geometry=[box(0, 0, 1, 1), box(5, 5, 6, 6)],
        crs="EPSG:4326",
    )
    points = gpd.GeoDataFrame(
        {"pm25": [30.0]},
        geometry=[Point(0.5, 0.5)],
        crs="EPSG:4326",
    )
    result = aggregate_points_to_admin(admin, points, "pm25")
    import numpy as np

    assert np.isnan(result["pm25"].tolist()[1])


# --- run_render：三种图种各出 PNG + PDF，中文无乱码 ---


def test_run_render_choropleth(tmp_path) -> None:
    spec = build_spec(make_fields("choropleth"))
    result = run_render(spec, make_polygon_gdf([30, 45, 55, 65, 80]), tmp_path, name="choro")
    assert isinstance(result, RenderResult)
    assert result.png_path and result.png_path.exists()
    assert result.png_path.stat().st_size > 10_000
    _assert_chinese_font(result.report)
    _assert_pdf(result.pdf_path)


def test_run_render_point(tmp_path) -> None:
    spec = build_spec(make_fields("point"))
    result = run_render(spec, make_point_gdf([30, 45, 55, 65, 80]), tmp_path, name="point")
    assert result.png_path and result.png_path.exists()
    assert result.png_path.stat().st_size > 10_000
    _assert_chinese_font(result.report)
    _assert_pdf(result.pdf_path)


def test_run_render_idw(tmp_path) -> None:
    spec = build_spec(make_fields("idw"))
    result = run_render(spec, make_point_gdf([30, 45, 55, 65, 80]), tmp_path, name="idw")
    assert result.png_path and result.png_path.exists()
    assert result.png_path.stat().st_size > 10_000
    _assert_chinese_font(result.report)
    _assert_pdf(result.pdf_path)


def test_run_render_requires_geometry(tmp_path) -> None:
    spec = build_spec(make_fields("choropleth"))
    layer = gpd.GeoDataFrame({"pm25": [30]})  # 无几何
    with pytest.raises(DataError):
        run_render(spec, layer, tmp_path)


# --- PDF 文件头（覆盖三个渲染器的 pdf_path 出口） ---


def test_pdf_header_for_all_three_renderers(tmp_path) -> None:
    for map_type, gdf in [
        ("choropleth", make_polygon_gdf([30, 45, 55, 65, 80])),
        ("point", make_point_gdf([30, 45, 55, 65, 80])),
        ("idw", make_point_gdf([30, 45, 55, 65, 80])),
    ]:
        spec = build_spec(make_fields(map_type))
        result = run_render(spec, gdf, tmp_path, name=map_type)
        _assert_pdf(result.pdf_path)


# --- 上传 CRS 拦截 ---


def _write_geojson_without_crs(tmp_path) -> str:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"pm25": 30.0},
                "geometry": {"type": "Point", "coordinates": [116.5, 34.3]},
            }
        ],
    }
    path = tmp_path / "no_crs.geojson"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_upload_missing_crs_blocked_until_confirmed(tmp_path) -> None:
    path = _write_geojson_without_crs(tmp_path)
    layer = parse_upload(path)
    assert layer.meta["crs_status"] == "missing"
    with pytest.raises(CrsNotDeclared):
        ensure_crs(layer)


def test_upload_missing_crs_confirmed_then_continues(tmp_path) -> None:
    path = _write_geojson_without_crs(tmp_path)
    layer = parse_upload(path, crs="EPSG:4326")
    assert layer.meta["crs_status"] == "declared"
    # 确认后 ensure_crs 放行
    assert ensure_crs(layer) is layer
    assert layer.gdf.crs is not None