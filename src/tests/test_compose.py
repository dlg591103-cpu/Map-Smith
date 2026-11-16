"""buffer / overlay 渲染的用例：图层顺序、颜色/透明度、图例、分派与出图。

验收重点（见任务第 4 节）：
- 断言落在几何位置、填充色、alpha、zorder 上，不只看报告对象。
- buffer：缓冲面半透明填充 + 描边，原始要素只描边，站点最上层。
- overlay：两个面图层可分辨，交叠区不糊成一片。
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402

from mapsmith.io.models import DataError  # noqa: E402
from mapsmith.render import render  # noqa: E402
from mapsmith.render.compose import (  # noqa: E402
    BUFFER_ALPHA,
    OVERLAY_ALPHA,
    BufferReport,
    OverlayReport,
    render_buffer,
    render_overlay,
)
from mapsmith.render.layout import palette_colors  # noqa: E402
from mapsmith.spec import Extent, Layer, MapSpec, Palette  # noqa: E402

BBOX = (116.2, 34.1, 118.6, 34.9)


def make_buffer_spec(**overrides) -> MapSpec:
    data = dict(
        title="徐州市 PM2.5 站点 5 km 缓冲区图（2026-11-01）",
        map_type="buffer",
        extent=Extent(adcode="320300", bbox=BBOX),
        layers=[Layer(id="data", kind="buffer")],
        classification=None,
        palette=Palette(scheme="YlOrRd", reverse=False),
        data_source_note="数据来源：全国城市空气质量实时发布平台（quotsoft.net），更新时间 2026-11-01",
        crs="EPSG:4490",
        notes=[],
    )
    data.update(overrides)
    return MapSpec(**data)


def make_overlay_spec(**overrides) -> MapSpec:
    data = dict(
        title="徐州市空间叠加图（2026-11-01）",
        map_type="overlay",
        extent=Extent(adcode="320300", bbox=BBOX),
        layers=[Layer(id="base", kind="admin"), Layer(id="data", kind="overlay")],
        classification=None,
        palette=Palette(scheme="YlOrRd", reverse=False),
        data_source_note="数据来源：全国城市空气质量实时发布平台（quotsoft.net），更新时间 2026-11-01",
        crs="EPSG:4490",
        notes=[],
    )
    data.update(overrides)
    return MapSpec(**data)


def make_buffer_gdf(crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    """一个落在徐州 bbox 内的缓冲面（Polygon）。"""
    return gpd.GeoDataFrame(
        {"name": ["站点A"]},
        geometry=[box(116.8, 34.3, 117.3, 34.8)],
        crs=crs,
    )


def make_points_gdf(crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    """缓冲面中心附近的站点点。"""
    return gpd.GeoDataFrame(
        {"name": ["站点A", "站点B"]},
        geometry=[Point(117.0, 34.5), Point(117.1, 34.55)],
        crs=crs,
    )


def make_overlay_gdfs() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """两个有交叠的面：底层 A、上层 B，交叠区约 (117.0,34.3)-(117.5,34.8)。"""
    base = gpd.GeoDataFrame(
        {"name": ["底层A"]},
        geometry=[box(116.0, 34.0, 117.5, 34.8)],
        crs="EPSG:4326",
    )
    other = gpd.GeoDataFrame(
        {"name": ["上层B"]},
        geometry=[box(117.0, 34.3, 118.5, 35.0)],
        crs="EPSG:4326",
    )
    return base, other


def _collection_rgb(coll) -> tuple:
    return tuple(round(float(c), 6) for c in coll.get_facecolors()[0][:3])


def _collection_alpha(coll) -> float:
    if coll.get_alpha() is not None:
        return float(coll.get_alpha())
    return float(coll.get_facecolors()[0][3])


# --- 分派 ---


def test_render_dispatches_buffer() -> None:
    report = render(make_buffer_spec(), make_buffer_gdf())
    assert isinstance(report, BufferReport)
    plt.close("all")


def test_render_dispatches_overlay() -> None:
    base, other = make_overlay_gdfs()
    report = render(make_overlay_spec(), base, other_gdf=other)
    assert isinstance(report, OverlayReport)
    plt.close("all")


# --- buffer：颜色 / 图层顺序 / 图例 ---


def test_buffer_fill_uses_palette_first_color_and_alpha() -> None:
    spec = make_buffer_spec()
    render_buffer(spec, make_buffer_gdf())
    ax = plt.gcf().axes[0]
    coll = ax.collections[0]
    expected = tuple(round(float(c), 6) for c in to_rgba(palette_colors(spec, 2)[0])[:3])
    assert _collection_rgb(coll) == expected
    assert _collection_alpha(coll) == pytest.approx(BUFFER_ALPHA, abs=1e-6)
    plt.close("all")


def test_buffer_points_on_top_of_polygon() -> None:
    """站点（zorder=3）必须画在缓冲面（zorder=1）之上。"""
    render_buffer(make_buffer_spec(), make_buffer_gdf(), points_gdf=make_points_gdf())
    ax = plt.gcf().axes[0]
    zorders = [coll.get_zorder() for coll in ax.collections]
    assert zorders[-1] > zorders[0]
    plt.close("all")


def test_buffer_original_boundary_drawn_without_fill() -> None:
    """原始要素只描边不填充。"""
    render_buffer(
        make_buffer_spec(),
        make_buffer_gdf(),
        original_gdf=make_buffer_gdf(),
    )
    ax = plt.gcf().axes[0]
    # 缓冲面 collection 之后是原始要素 collection；原始要素 facecolor 应为 none（透明）。
    original = ax.collections[1]
    assert original.get_edgecolors()[0][3] != 0, "原始要素应有描边"
    faces = original.get_facecolors()
    has_fill = len(faces) > 0 and any(float(f[3]) != 0.0 for f in faces)
    assert not has_fill, "原始要素只描边，不应有填充"
    plt.close("all")


def test_buffer_legend_shows_radius() -> None:
    report = render_buffer(make_buffer_spec(), make_buffer_gdf(), buffer_km=5.0)
    ax = plt.gcf().axes[0]
    legend = ax.get_legend()
    assert legend is not None
    texts = [t.get_text() for t in legend.get_texts()]
    assert any("5 km 缓冲区" in t for t in texts)
    assert report.legend_label == "5 km 缓冲区"
    plt.close("all")


def test_buffer_radius_from_gdf_attrs() -> None:
    gdf = make_buffer_gdf()
    gdf.attrs["buffer_km"] = 7.5
    report = render_buffer(make_buffer_spec(), gdf)
    assert report.buffer_km == 7.5
    assert report.legend_label == "7.5 km 缓冲区"
    plt.close("all")


def test_buffer_radius_changes_legend() -> None:
    """改半径后图例跟着变（半径不写死）。"""
    spec = make_buffer_spec()
    render_buffer(spec, make_buffer_gdf(), buffer_km=5.0)
    label_5 = [t.get_text() for t in plt.gcf().axes[0].get_legend().get_texts()]
    plt.close("all")

    render_buffer(spec, make_buffer_gdf(), buffer_km=10.0)
    label_10 = [t.get_text() for t in plt.gcf().axes[0].get_legend().get_texts()]
    plt.close("all")

    assert label_5 != label_10
    assert any("5 km" in t for t in label_5)
    assert any("10 km" in t for t in label_10)


# --- overlay：颜色 / 图例 ---


def test_overlay_two_layers_distinct_and_semtransparent() -> None:
    base, other = make_overlay_gdfs()
    spec = make_overlay_spec()
    render_overlay(spec, base, other_gdf=other)
    ax = plt.gcf().axes[0]

    assert len(ax.collections) >= 2
    bottom = ax.collections[0]
    top = ax.collections[1]

    palette = palette_colors(spec, 2)
    assert _collection_rgb(bottom) == tuple(round(float(c), 6) for c in to_rgba(palette[0])[:3])
    assert _collection_rgb(top) == tuple(round(float(c), 6) for c in to_rgba(palette[1])[:3])
    assert _collection_alpha(bottom) == pytest.approx(OVERLAY_ALPHA, abs=1e-6)
    assert _collection_alpha(top) == pytest.approx(OVERLAY_ALPHA, abs=1e-6)
    # 上层有描边，底层无描边（或用透明描边）。
    assert top.get_edgecolors()[0][3] != 0
    plt.close("all")


def test_overlay_legend_has_two_items_labeled() -> None:
    base, other = make_overlay_gdfs()
    report = render_overlay(make_overlay_spec(), base, other_gdf=other)
    ax = plt.gcf().axes[0]
    legend = ax.get_legend()
    assert legend is not None
    texts = [t.get_text() for t in legend.get_texts()]
    assert texts == [report.base_label, report.other_label]
    assert len(texts) == 2
    assert "底层A" in texts
    assert "上层B" in texts
    plt.close("all")


def test_overlay_multi_feature_base_uses_generic_label() -> None:
    """多要素底层不得取单行 name（「鼓楼区」以偏概全），应回退通用名「行政边界」。"""
    base = gpd.GeoDataFrame(
        {"name": ["鼓楼区", "云龙区"]},
        geometry=[box(116.0, 34.0, 117.0, 34.5), box(117.0, 34.0, 118.0, 34.5)],
        crs="EPSG:4326",
    )
    other = make_overlay_gdfs()[1]
    report = render_overlay(make_overlay_spec(), base, other_gdf=other)
    assert report.base_label == "行政边界"
    assert "鼓楼区" not in report.base_label
    assert "云龙区" not in report.base_label
    plt.close("all")


def test_overlay_single_feature_base_uses_name() -> None:
    """单要素底层可用其 name。"""
    base = gpd.GeoDataFrame(
        {"name": ["鼓楼区"]},
        geometry=[box(116.0, 34.0, 117.0, 34.5)],
        crs="EPSG:4326",
    )
    other = make_overlay_gdfs()[1]
    report = render_overlay(make_overlay_spec(), base, other_gdf=other)
    assert report.base_label == "鼓楼区"
    plt.close("all")


def test_overlay_other_uses_attrs_semantic_name() -> None:
    """上层带 attrs["name"] 时应显示语义名（站点缓冲区）而非图层 id（data）。"""
    base, other = make_overlay_gdfs()
    other.attrs["name"] = "站点缓冲区"
    report = render_overlay(make_overlay_spec(), base, other_gdf=other)
    assert report.other_label == "站点缓冲区"
    assert report.other_label != "data"
    plt.close("all")


def test_overlay_explicit_labels_override() -> None:
    """labels 参数显式指定时优先于自动推断。"""
    base, other = make_overlay_gdfs()
    report = render_overlay(
        make_overlay_spec(), base, other_gdf=other, labels=("行政边界", "站点缓冲区")
    )
    assert report.base_label == "行政边界"
    assert report.other_label == "站点缓冲区"
    plt.close("all")


def test_overlay_requires_other_gdf() -> None:
    with pytest.raises(DataError, match="other_gdf"):
        render_overlay(make_overlay_spec(), make_buffer_gdf())
    plt.close("all")


# --- 出图与 CRS ---


def test_buffer_png_pdf(tmp_path) -> None:
    out = tmp_path / "buffer.png"
    pdf = tmp_path / "buffer.pdf"
    render_buffer(make_buffer_spec(), make_buffer_gdf(), out_path=out, pdf_path=pdf)
    assert out.exists() and out.stat().st_size > 10_000
    assert pdf.exists() and pdf.read_bytes()[:4] == b"%PDF"
    plt.close("all")


def test_overlay_png_pdf(tmp_path) -> None:
    base, other = make_overlay_gdfs()
    out = tmp_path / "overlay.png"
    pdf = tmp_path / "overlay.pdf"
    render_overlay(make_overlay_spec(), base, other_gdf=other, out_path=out, pdf_path=pdf)
    assert out.exists() and out.stat().st_size > 10_000
    assert pdf.exists() and pdf.read_bytes()[:4] == b"%PDF"
    plt.close("all")


def test_buffer_requires_crs() -> None:
    gdf = gpd.GeoDataFrame(
        {"name": ["A"]},
        geometry=[box(116.8, 34.3, 117.3, 34.8)],
    )
    with pytest.raises(DataError, match="坐标系"):
        render_buffer(make_buffer_spec(), gdf)
    plt.close("all")