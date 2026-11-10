"""T22 修复：取景范围 drawing_extent 与点图收窄出图的用例。

可读性判据说明（局限）：用「站点外接框占图幅宽度比例 ≥ 50%」作为可读性的必要前提
判据——比例高意味着气泡有展开空间，是「标注可读、气泡不连片」的必要条件，但不充分：
气泡本身有面积、标注文字有像素宽度，站点密集时即便比例达标，像素级仍可能轻微重叠。
该判据在数据坐标空间（度）计算，未折算 aspect 修正后图内实际像素比例。更强的像素级
「标注 bbox 两两不重叠」判据见 `test_point_labels_do_not_overlap`。
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402
from shapely.geometry import Point  # noqa: E402

from mapsmith.render.extent import drawing_extent  # noqa: E402
from mapsmith.render.point import render_point  # noqa: E402
from mapsmith.spec import (  # noqa: E402
    Annotation,
    Classification,
    Extent,
    Layer,
    MapSpec,
    Palette,
)

BREAKS = [40.0, 50.0, 60.0, 70.0, 90.0]
EXTENT = (116.2, 34.1, 118.6, 34.9)


def make_spec(**overrides) -> MapSpec:
    data = dict(
        title="徐州市 PM2.5 24 小时站点分布图（2026-11-01）",
        map_type="point",
        extent=Extent(adcode="320300", bbox=EXTENT),
        layers=[Layer(id="data", kind="point", field="pm25", source="quotsoft_20261101")],
        classification=Classification(method="quantile", n=5, breaks=list(BREAKS)),
        palette=Palette(scheme="YlOrRd", reverse=False),
        annotation=Annotation(label_field=None, show=False),
        data_source_note="数据来源：全国城市空气质量实时发布平台（quotsoft.net），更新时间 2026-11-01",
        crs="EPSG:4490",
        notes=[],
    )
    data.update(overrides)
    return MapSpec(**data)


# --- drawing_extent 单元测试 ---


def test_drawing_extent_without_content_returns_extent() -> None:
    assert drawing_extent(make_spec()) == EXTENT


def test_drawing_extent_narrows_to_content_with_pad() -> None:
    result = drawing_extent(make_spec(), content_bounds=(117.166, 34.2, 117.475, 34.4), pad=0.10)
    minx, miny, maxx, maxy = result
    cw = 117.475 - 117.166
    assert maxx - minx == pytest.approx(cw * 1.2, abs=1e-9)
    assert minx >= 116.2 and maxx <= 118.6


def test_drawing_extent_single_point_degrades_to_extent() -> None:
    assert drawing_extent(make_spec(), content_bounds=(117.0, 34.3, 117.0, 34.3)) == EXTENT


def test_drawing_extent_zero_area_line_degrades() -> None:
    assert drawing_extent(make_spec(), content_bounds=(117.0, 34.3, 117.1, 34.3)) == EXTENT


def test_drawing_extent_clips_content_larger_than_extent() -> None:
    assert drawing_extent(make_spec(), content_bounds=(110.0, 33.0, 120.0, 35.0)) == EXTENT


def test_drawing_extent_tiny_content_degrades() -> None:
    cx, cy = 117.0, 34.3
    assert drawing_extent(make_spec(), content_bounds=(cx, cy, cx + 0.001, cy + 0.001)) == EXTENT


# --- point 渲染集成测试 ---


def _make_clustered_gdf(labels: list[str] | None = None) -> gpd.GeoDataFrame:
    """模拟徐州真实场景：10 站集中在约 0.3° 宽的东南小块（extent 约 2.4° 宽）。"""
    xs = [117.166 + i * 0.06 for i in range(5)]
    ys = [34.3 + (i % 2) * 0.08 for i in range(5)]
    data = {"pm25": [30, 45, 55, 65, 80]}
    if labels is not None:
        data["name"] = labels
    return gpd.GeoDataFrame(data, geometry=[Point(x, y) for x, y in zip(xs, ys)], crs="EPSG:4326")


def test_point_content_occupies_at_least_half_frame() -> None:
    """验收 1：站点集中时，站点外接框占图幅宽度比例 ≥ 50%（修复前约 10%）。"""
    spec = make_spec()
    gdf = _make_clustered_gdf()
    render_point(spec, gdf)
    ax = plt.gcf().axes[0]
    xmin, xmax = ax.get_xlim()
    frame_w = xmax - xmin
    content_w = float(gdf.total_bounds[2] - gdf.total_bounds[0])
    ratio = content_w / frame_w
    assert ratio >= 0.5, f"站点外接框占图幅宽度比例 {ratio:.2%}，应 ≥ 50%"
    plt.close("all")


def test_point_local_note_added_when_narrow() -> None:
    """验收 D：取景范围 <30% extent 宽度时，注记加「站点仅覆盖图幅局部」。"""
    render_point(make_spec(), _make_clustered_gdf())
    fig = plt.gcf()
    notes_text = "\n".join(t.get_text() for t in fig.texts)
    assert "站点仅覆盖图幅局部" in notes_text
    plt.close("all")


def test_point_labels_do_not_overlap() -> None:
    """验收 4 补充：像素级标注 bbox 两两不重叠（更强的可读性判据）。"""
    labels = ["站点A", "站点B", "站点C", "站点D", "站点E"]
    spec = make_spec(annotation=Annotation(label_field="name", show=True))
    render_point(spec, _make_clustered_gdf(labels=labels))
    fig = plt.gcf()
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    ax = fig.axes[0]
    label_texts = [t for t in ax.texts if t.get_text().startswith("站点")]
    assert len(label_texts) == len(labels)
    boxes = [t.get_window_extent(renderer) for t in label_texts]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert not boxes[i].overlaps(boxes[j]), f"标注 {labels[i]} 与 {labels[j]} 重叠"
    plt.close("all")