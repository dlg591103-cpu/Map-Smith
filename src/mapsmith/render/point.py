"""T17 点图/气泡图渲染：按字段值映射气泡面积，点位与标注正确。

规则来源：
- docs/facts/07 第 2 条（图例有分级断点与单位）、第 6 条（分级方法 + 级数）、
  第 8 条（连续量用单色渐变、禁止彩虹）、第 10 条（缺失值处理说明）。
- docs/facts/05 工具 5：`render(spec) -> {png, pdf}`。

数据契约：只接收已带坐标的点 GeoDataFrame（geometry 为 Point）；渲染层不读 CSV、
不做空间聚合与插值（属于 T07 / T14）。气泡大小用 scatter 的 ``s``（面积）按字段值
线性映射到 ``[S_MIN, S_MAX]``，不用半径线性映射（会视觉夸张）。缺测点（NaN）画
灰色空心点并计数。标注文本只取 ``label_field`` 的原值。

渲染层不得代填：分级方法、配色语义、缺失值说明只从 MapSpec 读取（facts/07 失败路径）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

from ..io.models import DataError
from ..spec import MapSpec
from .choropleth import _aspect_for, _transformed_extent, class_index
from .extent import drawing_extent
from .layout import (
    LayoutReport,
    apply_layout,
    legend_labels,
    metric_extent,
    palette_colors,
)

# 气泡面积映射范围（scatter 的 s 单位是点²）。
S_MIN = 20.0
S_MAX = 800.0
# 值域退化（全相同 / 全缺测）时的固定气泡大小。
FALLBACK_SIZE = 200.0

MISSING_EDGE = "#999999"  # 缺测点空心边色
EDGE_COLOR = "#666666"
DEFAULT_POINT_COLOR = "#1f77b4"  # 无分级时的单色


def _fmt(value: float) -> str:
    if float(value) == int(value):
        return str(int(value))
    return f"{value:g}"


def size_map(value: float, vmin: float, vmax: float) -> float:
    """字段值线性映射到气泡面积 ``[S_MIN, S_MAX]``；值域退化返回固定大小。"""
    if vmin == vmax:
        return FALLBACK_SIZE
    ratio = (value - vmin) / (vmax - vmin)
    return S_MIN + ratio * (S_MAX - S_MIN)


@dataclass(frozen=True)
class SizeResult:
    """一次气泡面积映射的结果。"""

    sizes: list[float]
    missing_mask: list[bool]
    missing_count: int
    vmin: float | None
    vmax: float | None


def assign_sizes(values: list[Any]) -> SizeResult:
    """按字段值映射气泡面积，缺测（None / NaN）标记并给固定大小。

    面积线性映射（验收 2）；值域为空或单一值时退化到 `FALLBACK_SIZE`（验收 3）。
    """
    parsed: list[float | None] = []
    missing_mask: list[bool] = []
    for value in values:
        if value is None:
            parsed.append(None)
            missing_mask.append(True)
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise DataError(f"气泡数值不是数字：{value!r}") from exc
        if math.isnan(number):
            parsed.append(None)
            missing_mask.append(True)
        else:
            parsed.append(number)
            missing_mask.append(False)

    valid = [v for v in parsed if v is not None]
    vmin = min(valid) if valid else None
    vmax = max(valid) if valid else None

    sizes: list[float] = []
    for value in parsed:
        if value is None or vmin is None or vmax is None or vmin == vmax:
            sizes.append(FALLBACK_SIZE)
        else:
            sizes.append(size_map(value, vmin, vmax))

    return SizeResult(
        sizes=sizes,
        missing_mask=missing_mask,
        missing_count=sum(missing_mask),
        vmin=vmin,
        vmax=vmax,
    )


def _point_colors(
    values: list[Any],
    missing_mask: list[bool],
    spec: MapSpec,
) -> tuple[list[str], list[int] | None]:
    """给每个点分配填充色；无分级时用单色，有分级时按断点取 palette 颜色。

    返回 ``(颜色列表, 各级计数或 None)``。缺测点用占位色（实际画空心，颜色不生效）。"""
    classification = spec.classification
    if classification is None:
        return [DEFAULT_POINT_COLOR] * len(values), None

    if not classification.breaks:
        raise DataError("spec.classification.breaks 为空，无法分级设色")

    colors = palette_colors(spec, classification.n)
    counts = [0] * classification.n
    out: list[str] = []
    for value, missing in zip(values, missing_mask):
        if missing:
            out.append(MISSING_EDGE)
        else:
            index = class_index(value, classification.breaks)
            counts[index] += 1
            out.append(colors[index])
    return out, counts


@dataclass
class PointReport:
    """一次点图/气泡图出图的结果，供回显与测试核对。"""

    layout: LayoutReport
    sizes: list[float] = field(default_factory=list)
    class_counts: list[int] | None = None
    missing_count: int = 0
    crs: str = ""
    summary: str = ""


def _size_handle(area: float) -> Line2D:
    """气泡大小图例的圆点句柄；`markersize=sqrt(面积)` 保持面积线性关系。"""
    return Line2D(
        [0],
        [0],
        linestyle="none",
        marker="o",
        markersize=math.sqrt(area),
        markerfacecolor=DEFAULT_POINT_COLOR,
        markeredgecolor=EDGE_COLOR,
    )


def render_point(
    spec: MapSpec,
    gdf: Any,
    *,
    field: str | None = None,
    label_field: str | None = None,
    unit: str | None = None,
    out_path: str | Path | None = None,
    pdf_path: str | Path | None = None,
) -> PointReport:
    """渲染一张点图 / 气泡图（不画坐标轴，版式要素由 `apply_layout` 补齐）。

    - ``gdf`` 需带坐标系，几何为 Point。
    - ``field`` 缺省取 spec 里 kind=point 图层的 field；气泡面积按该字段线性映射。
    - ``label_field`` 缺省取 `spec.annotation.label_field`；标注文本取该列原值。
    - 缺测点画灰色空心点并计入 `missing_count`。
    """
    # --- 契约校验 ---
    if getattr(gdf, "crs", None) is None:
        raise DataError("图层缺少坐标系（crs 为空），无法按 spec.crs 重投影")
    geom_types = {str(t) for t in getattr(gdf, "geom_type", [])}
    if not geom_types or not geom_types.issubset({"Point", "MultiPoint"}):
        raise DataError(f"点图只接收点几何，实际为：{'、'.join(sorted(geom_types))}")

    field = field or next(
        (layer.field for layer in spec.layers if layer.kind == "point" and layer.field),
        None,
    )
    if not field:
        raise DataError("点图渲染缺少数值字段：请传 field 或让图层提供 field")
    if field not in getattr(gdf, "columns", []):
        raise DataError(f"图层中没有字段 {field!r}，现有字段：{list(getattr(gdf, 'columns', []))}")

    label_field = label_field or spec.annotation.label_field
    if label_field is not None and label_field not in getattr(gdf, "columns", []):
        raise DataError(
            f"图层中没有标注字段 {label_field!r}，现有字段：{list(getattr(gdf, 'columns', []))}"
        )

    # --- 重投影 + 数值 ---
    frame = gdf.to_crs(spec.crs) if str(gdf.crs) != str(spec.crs) else gdf
    values = list(frame[field])
    size_result = assign_sizes(values)
    color_list, class_counts = _point_colors(values, size_result.missing_mask, spec)

    # --- 画点 ---
    fig, ax = plt.subplots(figsize=spec.layout.size)
    x = np.asarray(frame.geometry.x, dtype=float)
    y = np.asarray(frame.geometry.y, dtype=float)
    missing_arr = np.asarray(size_result.missing_mask, dtype=bool)
    valid_arr = ~missing_arr
    sizes_arr = np.asarray(size_result.sizes, dtype=float)

    if valid_arr.any():
        ax.scatter(
            x[valid_arr],
            y[valid_arr],
            s=sizes_arr[valid_arr],
            c=np.asarray(color_list)[valid_arr],
            edgecolors=EDGE_COLOR,
            linewidths=0.6,
            zorder=3,
        )
    if missing_arr.any():
        ax.scatter(
            x[missing_arr],
            y[missing_arr],
            s=sizes_arr[missing_arr],
            facecolors="none",
            edgecolors=MISSING_EDGE,
            linewidths=1.0,
            zorder=3,
        )

    ax.set_aspect(_aspect_for(spec.crs, spec.extent.bbox))
    ax.set_axis_off()
    # 取景范围按站点实际分布收窄，避免稀疏站点挤在行政区全幅正中的一小团。
    content_bounds = None if frame.empty else tuple(float(v) for v in frame.total_bounds)
    minx, miny, maxx, maxy = drawing_extent(spec, content_bounds=content_bounds)
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)

    # 取景范围明显小于 extent 时，注记说明站点只覆盖局部（渲染层补充说明，不改 spec.notes）。
    extra_note: str | None = None
    extent_full = _transformed_extent(spec)
    extent_w = extent_full[2] - extent_full[0]
    draw_w = maxx - minx
    if extent_w > 0 and draw_w < extent_w * 0.3:
        draw_m = metric_extent((minx, miny, maxx, maxy), source_crs=str(spec.crs))
        km = (draw_m[2] - draw_m[0]) / 1000.0
        extra_note = f"注记：站点仅覆盖图幅局部，范围约 {km:g} km"

    # --- 标注 ---
    if label_field is not None and spec.annotation.show:
        for xi, yi, text in zip(x, y, frame[label_field].astype(str)):
            ax.annotate(str(text), (xi, yi), textcoords="offset points", xytext=(5, 5), fontsize=8)

    # --- 气泡大小三级图例（先画并 add_artist，让 apply_layout 的断点图例成为主图例）---
    if (
        spec.layout.legend
        and size_result.vmin is not None
        and size_result.vmax is not None
        and size_result.vmin != size_result.vmax
    ):
        mid = (size_result.vmin + size_result.vmax) / 2.0
        level_values = (size_result.vmin, mid, size_result.vmax)
        handles = [
            _size_handle(size_map(v, size_result.vmin, size_result.vmax)) for v in level_values
        ]
        labels = [_fmt(v) for v in level_values]
        title = "气泡大小" + (f"（{unit}）" if unit else "")
        # 气泡大小图例也放图框外右侧、断点图例下方，避免压住右下角的气泡点。
        size_legend = ax.legend(
            handles=handles,
            labels=labels,
            loc="upper left",
            bbox_to_anchor=(1.02, 0.4),
            title=title,
        )
        ax.add_artist(size_legend)

    # --- 版式要素 + 断点图例 ---
    layout = apply_layout(fig, ax, spec, unit=unit, legend_anchor=(1.02, 1.0), extra_note=extra_note)

    # 版式注记下移到图框正下方（与 choropleth 一致的留白处理）。
    fig.canvas.draw()
    ax_bottom = ax.get_position().y0
    for text in fig.texts:
        text.set_va("top")
        text.set_y(ax_bottom - 0.02)

    if out_path is not None:
        fig.savefig(out_path, dpi=spec.layout.dpi, bbox_inches="tight")
    if pdf_path is not None:
        fig.savefig(pdf_path, dpi=spec.layout.dpi, bbox_inches="tight")

    drawn = len(values) - size_result.missing_count
    summary = (
        f"{drawn} 个站点按 {field} 映射气泡面积，缺测 {size_result.missing_count} 个"
        if size_result.missing_count
        else f"{drawn} 个站点按 {field} 映射气泡面积"
    )
    return PointReport(
        layout=layout,
        sizes=size_result.sizes,
        class_counts=class_counts,
        missing_count=size_result.missing_count,
        crs=str(spec.crs),
        summary=summary,
    )