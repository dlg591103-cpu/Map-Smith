"""T17 点图/气泡图的用例：面积映射、缺测点、标注、重投影、图例与出图。"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402
from matplotlib.legend import Legend  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402

from mapsmith.io.models import DataError  # noqa: E402
from mapsmith.render import render  # noqa: E402
from mapsmith.render.choropleth import (  # noqa: E402
    ChoroplethReport,
    _transformed_extent,
)
from mapsmith.render.layout import legend_labels  # noqa: E402
from mapsmith.render.point import (  # noqa: E402
    FALLBACK_SIZE,
    S_MAX,
    S_MIN,
    PointReport,
    assign_sizes,
    render_point,
    size_map,
)
from mapsmith.spec import (  # noqa: E402
    Annotation,
    Classification,
    Extent,
    Layer,
    MapSpec,
    Palette,
)

BREAKS = [40, 50, 60, 70, 90]


def make_point_spec(**overrides) -> MapSpec:
    data = dict(
        title="徐州市 PM2.5 24 小时站点分布图（2026-11-01）",
        map_type="point",
        extent=Extent(adcode="320300", bbox=(116.2, 34.1, 118.6, 34.9)),
        layers=[Layer(id="data", kind="point", field="pm25", source="quotsoft_20261101")],
        classification=Classification(method="quantile", n=5, breaks=list(BREAKS)),
        palette=Palette(scheme="YlOrRd", reverse=False),
        annotation=Annotation(label_field=None, show=False),
        data_source_note="数据来源：全国城市空气质量实时发布平台（quotsoft.net），更新时间 2026-11-01",
        crs="EPSG:4490",
        notes=["2 个站点缺测"],
    )
    data.update(overrides)
    return MapSpec(**data)


def make_point_gdf(values, labels=None, crs="EPSG:4326") -> gpd.GeoDataFrame:
    """构造落在徐州 bbox 内的一排点，便于逐点核对。"""
    n = len(values)
    xs = [116.5 + i * 0.35 for i in range(n)]
    ys = [34.25 + (i % 3) * 0.2 for i in range(n)]
    data = {"pm25": list(values)}
    if labels is not None:
        data["name"] = list(labels)
    return gpd.GeoDataFrame(data, geometry=[Point(x, y) for x, y in zip(xs, ys)], crs=crs)


def _legends(ax) -> list[Legend]:
    return [a for a in ax.get_children() if isinstance(a, Legend)]


# --- 面积映射 ---


def test_size_map_monotonic_and_endpoints() -> None:
    assert size_map(10, 10, 50) == S_MIN
    assert size_map(50, 10, 50) == S_MAX
    assert S_MIN < size_map(30, 10, 50) < S_MAX

    previous: float | None = None
    for value in [10, 20, 30, 40, 50]:
        size = size_map(value, 10, 50)
        if previous is not None:
            assert size > previous
        previous = size


def test_size_map_degenerate_single_value() -> None:
    assert size_map(50, 50, 50) == FALLBACK_SIZE


def test_assign_sizes_missing_count() -> None:
    result = assign_sizes([30, None, 55, float("nan"), 80])
    assert result.missing_count == 2
    assert result.missing_mask == [False, True, False, True, False]
    assert result.sizes[0] == S_MIN  # 30 最小
    assert result.sizes[4] == S_MAX  # 80 最大
    assert result.sizes[1] == FALLBACK_SIZE  # 缺测固定大小


def test_assign_sizes_all_equal_degenerate() -> None:
    result = assign_sizes([50, 50, 50])
    assert result.missing_count == 0
    assert result.vmin == 50 and result.vmax == 50
    assert result.sizes == [FALLBACK_SIZE, FALLBACK_SIZE, FALLBACK_SIZE]


def test_assign_sizes_all_nan_degenerate() -> None:
    result = assign_sizes([float("nan"), float("nan")])
    assert result.missing_count == 2
    assert result.vmin is None and result.vmax is None
    assert result.sizes == [FALLBACK_SIZE, FALLBACK_SIZE]


# --- 出图与契约 ---


def test_render_points_within_extent() -> None:
    spec = make_point_spec()
    render_point(spec, make_point_gdf([30, 45, 55, 65, 80]))
    ax = plt.gcf().axes[0]
    minx, miny, maxx, maxy = _transformed_extent(spec)
    for collection in ax.collections:
        for ox, oy in collection.get_offsets():
            assert minx - 1e-6 <= ox <= maxx + 1e-6
            assert miny - 1e-6 <= oy <= maxy + 1e-6
    plt.close("all")


def test_render_labels_equal_field_values() -> None:
    labels = ["站点A", "站点B", "站点C", "站点D", "站点E"]
    spec = make_point_spec(annotation=Annotation(label_field="name", show=True))
    render_point(spec, make_point_gdf([30, 45, 55, 65, 80], labels=labels))
    ax = plt.gcf().axes[0]
    site_texts = sorted(t.get_text() for t in ax.texts if t.get_text().startswith("站点"))
    assert site_texts == sorted(labels)
    plt.close("all")


def test_render_missing_label_field_raises() -> None:
    spec = make_point_spec(annotation=Annotation(label_field="不存在", show=True))
    with pytest.raises(DataError, match="标注字段"):
        render_point(spec, make_point_gdf([30, 45]))
    plt.close("all")


def test_render_requires_crs() -> None:
    gdf = gpd.GeoDataFrame({"pm25": [30]}, geometry=[Point(116.5, 34.3)])
    with pytest.raises(DataError, match="坐标系"):
        render_point(make_point_spec(), gdf)
    plt.close("all")


def test_render_requires_point_geometry() -> None:
    gdf = gpd.GeoDataFrame(
        {"pm25": [30]},
        geometry=[box(116.2, 34.1, 116.5, 34.5)],
        crs="EPSG:4326",
    )
    with pytest.raises(DataError, match="点几何"):
        render_point(make_point_spec(), gdf)
    plt.close("all")


def test_render_requires_numeric_field() -> None:
    gdf = make_point_gdf([30]).rename(columns={"pm25": "other"})
    with pytest.raises(DataError, match="没有字段"):
        render_point(make_point_spec(), gdf, field="pm25")
    plt.close("all")


def test_render_missing_points_hollow_and_counted() -> None:
    report = render_point(make_point_spec(), make_point_gdf([30, None, 55]))
    assert report.missing_count == 1
    assert "缺测 1 个" in report.summary

    ax = plt.gcf().axes[0]
    missing_col = ax.collections[1]  # 先画有效点，后画缺测点
    assert missing_col.get_offsets().shape[0] == 1
    facecolors = missing_col.get_facecolors()
    assert all(fc[3] == 0.0 for fc in facecolors)  # 空心（alpha=0）
    plt.close("all")


def test_render_reprojects_degrees_to_meters() -> None:
    spec = make_point_spec(crs="EPSG:4548")
    render_point(spec, make_point_gdf([30, 45], crs="EPSG:4326"))
    ax = plt.gcf().axes[0]
    xs = ax.collections[0].get_offsets()[:, 0]
    assert float(xs.min()) > 100_000  # 米级，而非 116 度级
    plt.close("all")


def test_render_break_legend_matches_classification() -> None:
    spec = make_point_spec()
    render_point(spec, make_point_gdf([30, 45, 55, 65, 80]))
    ax = plt.gcf().axes[0]
    break_legends = [lg for lg in _legends(ax) if len(lg.get_texts()) == spec.classification.n]
    assert break_legends
    texts = [t.get_text() for t in break_legends[0].get_texts()]
    assert texts == legend_labels(BREAKS)
    plt.close("all")


def test_render_size_legend_three_levels() -> None:
    render_point(make_point_spec(), make_point_gdf([30, 45, 55, 65, 80]))
    ax = plt.gcf().axes[0]
    size_legends = [lg for lg in _legends(ax) if lg.get_title().get_text().startswith("气泡大小")]
    assert size_legends
    assert len(size_legends[0].get_texts()) == 3
    plt.close("all")


def test_render_class_counts_sum_to_valid_points() -> None:
    """图例与计数口径一致：各级计数之和 + 缺测数 == 总点数。"""
    report = render_point(make_point_spec(), make_point_gdf([30, None, 55, 65, 80]))
    assert report.class_counts == [1, 0, 1, 1, 1]
    assert sum(report.class_counts) + report.missing_count == 5
    plt.close("all")


# --- render(spec) 分派 ---


def test_render_dispatches_by_map_type() -> None:
    point_report = render(make_point_spec(), make_point_gdf([30, 45, 55]))
    assert isinstance(point_report, PointReport)

    choropleth_spec = make_point_spec(
        map_type="choropleth",
        layers=[Layer(id="data", kind="choropleth", field="pm25")],
    )
    gdf = gpd.GeoDataFrame(
        {"pm25": [30, 45]},
        geometry=[box(116.2, 34.1, 116.5, 34.5), box(116.5, 34.1, 116.8, 34.5)],
        crs="EPSG:4326",
    )
    choropleth_report = render(choropleth_spec, gdf)
    assert isinstance(choropleth_report, ChoroplethReport)
    plt.close("all")


def test_render_dispatches_buffer() -> None:
    from mapsmith.render.compose import BufferReport

    spec = make_point_spec(
        map_type="buffer",
        classification=None,
        layers=[Layer(id="data", kind="buffer")],
    )
    report = render(spec, make_point_gdf([30, 45]))
    assert isinstance(report, BufferReport)
    plt.close("all")


def test_render_legends_outside_axes_and_north_arrow_visible() -> None:
    """回归防护：断点图例与气泡大小图例都必须在图框外，且指北针 N 真实可见。"""
    render_point(make_point_spec(), make_point_gdf([30, 45, 55, 65, 80]))
    fig = plt.gcf()
    fig.canvas.draw()
    ax = fig.axes[0]
    renderer = fig.canvas.get_renderer()
    ax_box = ax.get_window_extent(renderer)

    legends = _legends(ax)
    assert len(legends) == 2
    for legend in legends:
        assert not legend.get_window_extent(renderer).overlaps(ax_box)

    n_texts = [t for t in ax.texts if t.get_text() == "N"]
    assert n_texts
    assert n_texts[0].get_window_extent(renderer).overlaps(ax_box)
    plt.close("all")


def test_render_png_nonempty(tmp_path) -> None:
    out = tmp_path / "t17.png"
    render_point(make_point_spec(), make_point_gdf([30, 45, 55, 65, 80]), out_path=out)
    assert out.exists() and out.stat().st_size > 10_000
    plt.close("all")