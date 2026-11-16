"""T18 IDW 渲染的用例：凸包内插值、缺测点、图例示意、重投影、出图与分派。"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402

from mapsmith.io.models import DataError  # noqa: E402
from mapsmith.render import render  # noqa: E402
from mapsmith.render.idw import (  # noqa: E402
    GRID_N,
    IDWReport,
    _hull_mask,
    _idw,
    _point_in_polygon,
    render_idw,
)
from mapsmith.render.choropleth import _transformed_extent  # noqa: E402
from mapsmith.render.layout import legend_labels  # noqa: E402
from mapsmith.spec import (  # noqa: E402
    Annotation,
    Classification,
    Extent,
    Layer,
    MapSpec,
    Palette,
)

BREAKS = [40, 50, 60, 70, 90]


def make_idw_spec(**overrides) -> MapSpec:
    data = dict(
        title="徐州市 PM2.5 24 小时均值空间插值图（2026-11-01）",
        map_type="idw",
        extent=Extent(adcode="320300", bbox=(116.2, 34.1, 118.6, 34.9)),
        layers=[Layer(id="data", kind="idw", field="pm25", source="quotsoft_20261101")],
        classification=Classification(method="quantile", n=5, breaks=list(BREAKS)),
        palette=Palette(scheme="YlOrRd", reverse=False),
        annotation=Annotation(label_field=None, show=False),
        data_source_note="数据来源：全国城市空气质量实时发布平台（quotsoft.net），更新时间 2026-11-01",
        crs="EPSG:4490",
        notes=["IDW 插值仅在站点凸包内，凸包外不着色"],
    )
    data.update(overrides)
    return MapSpec(**data)


def make_point_gdf(values, labels=None, crs="EPSG:4326") -> gpd.GeoDataFrame:
    """构造落在徐州 bbox 内的一组点，便于核对。"""
    n = len(values)
    xs = [116.5 + i * 0.35 for i in range(n)]
    ys = [34.25 + (i % 3) * 0.2 for i in range(n)]
    data = {"pm25": list(values)}
    if labels is not None:
        data["name"] = list(labels)
    return gpd.GeoDataFrame(data, geometry=[Point(x, y) for x, y in zip(xs, ys)], crs=crs)


# --- _idw 基本行为 ---


def test_idw_returns_grid_shape() -> None:
    points = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    values = np.array([10.0, 20.0, 30.0])
    gx, gy = np.meshgrid(np.linspace(0, 1, 10), np.linspace(0, 1, 10))
    result = _idw(points, values, gx, gy)
    assert result.shape == (10, 10)


def test_idw_at_station_location_returns_station_value() -> None:
    """像元恰好落在站点上时，插值结果应等于该站值。"""
    points = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
    values = np.array([10.0, 20.0, 30.0])
    gx = np.array([[0.0]])
    gy = np.array([[0.0]])
    result = _idw(points, values, gx, gy)
    assert result[0, 0] == pytest.approx(10.0)


def test_idw_midpoint_between_two_stations() -> None:
    """两个站点正中间的插值应接近二者均值。"""
    points = np.array([[0.0, 0.0], [10.0, 0.0]])
    values = np.array([10.0, 30.0])
    gx = np.array([[5.0]])
    gy = np.array([[0.0]])
    result = _idw(points, values, gx, gy)
    assert result[0, 0] == pytest.approx(20.0, abs=0.5)


# --- 凸包掩码 ---


def test_point_in_polygon_inside() -> None:
    square = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    assert _point_in_polygon(5.0, 5.0, square) is True


def test_point_in_polygon_outside() -> None:
    square = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]])
    assert _point_in_polygon(15.0, 5.0, square) is False


def test_hull_mask_covers_interior_not_exterior() -> None:
    """凸包内的像元为 True，凸包外为 False。"""
    points = np.array([[0.0, 0.0], [10.0, 0.0], [5.0, 10.0]])
    gx, gy = np.meshgrid(np.linspace(-2, 12, 15), np.linspace(-2, 12, 15))
    mask = _hull_mask(points, gx, gy)
    # 三角形中心点应在凸包内
    center_idx = 7
    assert bool(mask[center_idx, center_idx]) is True
    # 远离三角形的角点应在凸包外
    assert bool(mask[0, 0]) is False


def test_hull_mask_few_points_returns_all_false() -> None:
    """少于 3 个点无法构成凸包，掩码全 False。"""
    points = np.array([[0.0, 0.0], [1.0, 1.0]])
    gx, gy = np.meshgrid(np.linspace(0, 1, 5), np.linspace(0, 1, 5))
    mask = _hull_mask(points, gx, gy)
    assert not mask.any()


# --- 出图与契约 ---


def test_render_idw_returns_report() -> None:
    report = render_idw(make_idw_spec(), make_point_gdf([30, 45, 55, 65, 80]))
    assert isinstance(report, IDWReport)
    assert report.valid_points == 5
    assert report.missing_points == 0
    assert report.grid_shape == (GRID_N, GRID_N)
    assert report.hull_area_km2 > 0
    assert "IDW" in report.summary
    plt.close("all")


def test_render_idw_requires_crs() -> None:
    gdf = gpd.GeoDataFrame({"pm25": [30, 45, 55]}, geometry=[Point(116.5, 34.3), Point(116.8, 34.4), Point(117.0, 34.5)])
    with pytest.raises(DataError, match="坐标系"):
        render_idw(make_idw_spec(), gdf)
    plt.close("all")


def test_render_idw_requires_point_geometry() -> None:
    gdf = gpd.GeoDataFrame(
        {"pm25": [30, 45, 55]},
        geometry=[box(116.2, 34.1, 116.5, 34.5), box(116.5, 34.1, 116.8, 34.5), box(116.8, 34.1, 117.1, 34.5)],
        crs="EPSG:4326",
    )
    with pytest.raises(DataError, match="点几何"):
        render_idw(make_idw_spec(), gdf)
    plt.close("all")


def test_render_idw_requires_numeric_field() -> None:
    gdf = make_point_gdf([30, 45, 55]).rename(columns={"pm25": "other"})
    with pytest.raises(DataError, match="没有字段"):
        render_idw(make_idw_spec(), gdf, field="pm25")
    plt.close("all")


def test_render_idw_requires_at_least_3_valid_points() -> None:
    with pytest.raises(DataError, match="至少需要 3 个有效站点"):
        render_idw(make_idw_spec(), make_point_gdf([30, 45]))
    plt.close("all")


def test_render_idw_missing_points_excluded_and_counted() -> None:
    report = render_idw(make_idw_spec(), make_point_gdf([30, None, 55, 65, 80]))
    assert report.valid_points == 4
    assert report.missing_points == 1
    assert "缺测 1 个" in report.summary
    plt.close("all")


def test_render_idw_nan_excluded() -> None:
    report = render_idw(make_idw_spec(), make_point_gdf([30, float("nan"), 55, 65, 80]))
    assert report.valid_points == 4
    assert report.missing_points == 1
    plt.close("all")


def test_render_idw_legend_has_break_labels() -> None:
    """验收项「图例标注示意」：图例标签与分级断点一致。"""
    render_idw(make_idw_spec(), make_point_gdf([30, 45, 55, 65, 80]))
    ax = plt.gcf().axes[0]
    legend = ax.get_legend()
    assert legend is not None
    texts = [t.get_text() for t in legend.get_texts()]
    assert texts == legend_labels(BREAKS)
    assert len(texts) == 5

    plt.close("all")


def test_render_idw_legend_outside_axes() -> None:
    """图例放在图框右侧，不遮挡插值面。"""
    render_idw(make_idw_spec(), make_point_gdf([30, 45, 55, 65, 80]))
    fig = plt.gcf()
    fig.canvas.draw()
    ax = fig.axes[0]
    legend = ax.get_legend()
    assert legend is not None
    renderer = fig.canvas.get_renderer()
    legend_box = legend.get_window_extent(renderer)
    ax_box = ax.get_window_extent(renderer)
    assert legend_box.x0 >= ax_box.x1
    plt.close("all")


def test_render_idw_reprojects_to_spec_crs() -> None:
    spec = make_idw_spec(crs="EPSG:4548")
    render_idw(spec, make_point_gdf([30, 45, 55, 65, 80], crs="EPSG:4326"))
    ax = plt.gcf().axes[0]
    x0, x1 = ax.get_xlim()
    assert x1 - x0 > 100_000  # 米级坐标，不是度
    plt.close("all")


def test_render_idw_labels_shown() -> None:
    labels = ["站点A", "站点B", "站点C", "站点D", "站点E"]
    spec = make_idw_spec(annotation=Annotation(label_field="name", show=True))
    render_idw(spec, make_point_gdf([30, 45, 55, 65, 80], labels=labels))
    ax = plt.gcf().axes[0]
    site_texts = sorted(t.get_text() for t in ax.texts if t.get_text().startswith("站点"))
    assert site_texts == sorted(labels)
    plt.close("all")


def test_render_idw_missing_label_field_raises() -> None:
    spec = make_idw_spec(annotation=Annotation(label_field="不存在", show=True))
    with pytest.raises(DataError, match="标注字段"):
        render_idw(spec, make_point_gdf([30, 45, 55]))
    plt.close("all")


def test_render_idw_no_classification_uses_continuous_colormap() -> None:
    """无分级时用连续色阶，不报错。"""
    spec = make_idw_spec(classification=None)
    report = render_idw(spec, make_point_gdf([30, 45, 55, 65, 80]))
    assert report.valid_points == 5
    plt.close("all")


def test_render_idw_png_nonempty(tmp_path) -> None:
    out = tmp_path / "t18.png"
    render_idw(make_idw_spec(), make_point_gdf([30, 45, 55, 65, 80]), out_path=out)
    assert out.exists() and out.stat().st_size > 10_000
    plt.close("all")


# --- render(spec) 分派 ---


def test_render_dispatches_idw() -> None:
    report = render(make_idw_spec(), make_point_gdf([30, 45, 55, 65, 80]))
    assert isinstance(report, IDWReport)
    plt.close("all")


def test_render_dispatches_overlay() -> None:
    from mapsmith.render.compose import OverlayReport

    base = gpd.GeoDataFrame(
        geometry=[box(116.0, 34.0, 117.5, 34.8)], crs="EPSG:4326"
    )
    other = gpd.GeoDataFrame(
        geometry=[box(117.0, 34.3, 118.5, 35.0)], crs="EPSG:4326"
    )
    spec = make_idw_spec(
        map_type="overlay",
        classification=None,
        layers=[Layer(id="base", kind="admin"), Layer(id="data", kind="overlay")],
    )
    report = render(spec, base, other_gdf=other)
    assert isinstance(report, OverlayReport)
    plt.close("all")