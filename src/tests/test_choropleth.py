"""T16 choropleth 的用例：分级归并、缺失值、配色与图例断点一致性、重投影与出图。"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402
from shapely.geometry import box  # noqa: E402

from mapsmith.io.models import DataError  # noqa: E402
from mapsmith.render.choropleth import (  # noqa: E402
    MISSING_COLOR,
    assign_colors,
    class_index,
    render_choropleth,
)
from mapsmith.render.layout import legend_labels, palette_colors  # noqa: E402
from mapsmith.spec import Classification, Extent, Layer, MapSpec, Palette  # noqa: E402

BREAKS = [40, 50, 60, 70, 90]


def make_spec(**overrides) -> MapSpec:
    data = dict(
        title="徐州市 PM2.5 24 小时均值分布图（2026-11-01）",
        map_type="choropleth",
        extent=Extent(adcode="320300", bbox=(116.2, 34.1, 118.6, 34.9)),
        layers=[
            Layer(id="data", kind="choropleth", field="pm25", source="quotsoft_20261101")
        ],
        classification=Classification(method="quantile", n=5, breaks=list(BREAKS)),
        palette=Palette(scheme="YlOrRd", reverse=False),
        data_source_note="数据来源：全国城市空气质量实时发布平台（quotsoft.net），更新时间 2026-11-01",
        crs="EPSG:4490",
        notes=["2 个站点缺测，已按空间邻近插补"],
    )
    data.update(overrides)
    return MapSpec(**data)


def make_gdf(values: list[float | None], crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    """按数值个数铺一排等大方形面，便于逐面核对颜色。"""
    geoms = [box(116.2 + i * 0.4, 34.1, 116.5 + i * 0.4, 34.5) for i in range(len(values))]
    return gpd.GeoDataFrame({"pm25": values}, geometry=geoms, crs=crs)


def _polygon_colors(ax) -> list:
    """geopandas 把面画进第一个 PatchCollection，按行序取各面填充色。"""
    return [tuple(round(c, 6) for c in row) for row in ax.collections[0].get_facecolors()]


# --- 分级归并 ---


def test_class_index_uses_inclusive_upper_bound() -> None:
    assert class_index(40, BREAKS) == 0
    assert class_index(40.1, BREAKS) == 1
    assert class_index(50, BREAKS) == 1
    assert class_index(90, BREAKS) == 4


def test_class_index_clamps_values_above_last_break() -> None:
    assert class_index(999, BREAKS) == 4


def test_class_index_missing_values() -> None:
    assert class_index(None, BREAKS) is None
    assert class_index(float("nan"), BREAKS) is None


def test_class_index_rejects_non_numeric() -> None:
    with pytest.raises(DataError, match="不是数字"):
        class_index("abc", BREAKS)  # type: ignore[arg-type]


def test_class_index_open_ended_break() -> None:
    breaks: list[float | None] = [50, 100, None]
    assert class_index(120, breaks) == 2


# --- 设色与配色语义 ---


def test_assign_colors_follows_palette_order() -> None:
    spec = make_spec()
    colors, counts, missing = assign_colors([30, 45, 55, 65, 80], spec)
    assert colors == palette_colors(spec, 5)
    assert counts == [1, 1, 1, 1, 1]
    assert missing == 0


def test_assign_colors_marks_missing_grey() -> None:
    colors, counts, missing = assign_colors([30, None], make_spec())
    assert colors[1] == MISSING_COLOR
    assert colors[1] not in palette_colors(make_spec(), 5)
    assert missing == 1
    assert sum(counts) == 1


def test_assign_colors_requires_classification() -> None:
    with pytest.raises(DataError, match="classification"):
        assign_colors([1.0], make_spec(classification=None))


# --- 出图 ---


def test_render_colors_each_polygon_by_its_class() -> None:
    spec = make_spec()
    report = render_choropleth(spec, make_gdf([30, 45, 55, 65, 80]))
    expected = [to_rgba(c) for c in palette_colors(spec, 5)]
    assert _polygon_colors(plt.gcf().axes[0]) == [
        tuple(round(c, 6) for c in row) for row in expected
    ]
    assert report.class_counts == [1, 1, 1, 1, 1]
    assert report.summary.startswith("5 个面")
    plt.close("all")


def test_render_legend_breaks_match_classification() -> None:
    """验收项「分级设色 + 分级断点图例」：色块顺序、数量都与断点一致。"""
    spec = make_spec()
    report = render_choropleth(spec, make_gdf([30, 45, 55, 65, 80]))
    ax = plt.gcf().axes[0]

    legend = ax.get_legend()
    assert legend is not None
    texts = [t.get_text() for t in legend.get_texts()]
    assert texts == legend_labels(BREAKS)
    assert len(texts) == spec.classification.n

    legend_colors = [to_rgba(handle.get_facecolor()) for handle in legend.legend_handles]
    assert legend_colors == [to_rgba(c) for c in palette_colors(spec, 5)]
    assert report.layout.drawn.count("图例") == 1
    plt.close("all")


def test_render_keeps_legend_outside_map_body() -> None:
    """choropleth 主体占满图幅，图例须落在图框右侧，不遮挡面要素。"""
    render_choropleth(make_spec(), make_gdf([30, 45, 55, 65, 80]))
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


def test_render_marks_missing_polygon_and_counts_it() -> None:
    report = render_choropleth(make_spec(), make_gdf([30, None]))
    assert report.missing_count == 1
    assert "缺失 1 个" in report.summary
    ax = plt.gcf().axes[0]
    assert _polygon_colors(ax)[1] == tuple(round(c, 6) for c in to_rgba(MISSING_COLOR))
    plt.close("all")


def test_render_reprojects_layer_to_spec_crs() -> None:
    spec = make_spec(crs="EPSG:4548")  # CGCS2000 3-degree zone 39，单位米
    gdf = make_gdf([30, 45], crs="EPSG:4326")
    render_choropleth(spec, gdf)
    ax = plt.gcf().axes[0]
    x0, x1 = ax.get_xlim()
    assert x1 - x0 > 100_000  # 经纬度范围是 2 度级，投影后应是数十万米
    plt.close("all")


def test_render_requires_crs_on_layer() -> None:
    gdf = gpd.GeoDataFrame({"pm25": [30]}, geometry=[box(116.2, 34.1, 116.5, 34.5)])
    with pytest.raises(DataError, match="坐标系"):
        render_choropleth(make_spec(), gdf)
    plt.close("all")


def test_render_requires_numeric_field() -> None:
    gdf = make_gdf([30]).rename(columns={"pm25": "other"})
    with pytest.raises(DataError, match="没有字段"):
        render_choropleth(make_spec(), gdf, field="pm25")
    plt.close("all")


def test_render_png_nonempty(tmp_path) -> None:
    out = tmp_path / "t16.png"
    render_choropleth(make_spec(), make_gdf([30, 45, 55, 65, 80]), out_path=out)
    assert out.exists() and out.stat().st_size > 10_000
    plt.close("all")
