"""buffer / overlay 渲染：复用现有渲染器的组件组合出图（A 方案，不新增独立渲染器）。

规则来源：
- docs/facts/02 图种 3「缓冲区分析图（buffer）」与图种 4「空间叠加/裁剪结果图（overlay）」。
- docs/facts/05 工具 5：`render(spec) -> {png, pdf}`。
- docs/facts/07 第 8 条：连续量用单色渐变、禁止彩虹；配色语义只从 MapSpec 读取。

A 方案约定（见任务说明第 2 节）：
- buffer 图层顺序（从下到上）：缓冲面 → 原始要素边界（细线）→ 站点/中心点。
- overlay：底层浅色填充 + 上层半透明填充描边，交叠区可分辨。

本模块只做组合，不复制 layout 逻辑：重投影/取景/配色/版式要素分别复用
`choropleth._transformed_extent` / `choropleth._aspect_for` / `extent.drawing_extent` /
`layout.palette_colors` / `layout.apply_layout`；点样式复用 `point` 的常量。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from ..io.models import DataError
from ..spec import MapSpec
from .choropleth import _aspect_for, _transformed_extent
from .extent import drawing_extent
from .layout import LayoutReport, apply_layout, palette_colors
from .point import DEFAULT_POINT_COLOR, EDGE_COLOR

# buffer：缓冲面描边、原始要素边界描边。
BUFFER_EDGE = "#333333"
ORIGINAL_EDGE = "#444444"
BUFFER_ALPHA = 0.30  # 方案要求半透明填充 0.25~0.35

# overlay：底层浅色填充、上层半透明填充 + 描边。
OVERLAY_ALPHA = 0.50
OVERLAY_EDGE = "#333333"


def _reproject(gdf: Any, spec: MapSpec, name: str) -> Any:
    """校验图层带坐标系，并按 ``spec.crs`` 重投影。"""
    if gdf is None:
        return None
    if getattr(gdf, "crs", None) is None:
        raise DataError(f"{name}缺少坐标系（crs 为空），无法按 spec.crs 重投影")
    return gdf.to_crs(spec.crs) if str(gdf.crs) != str(spec.crs) else gdf


def _resolve_buffer_km(gdf: Any, buffer_km: float | None) -> float | None:
    """缓冲半径读取顺序：函数参数 → 图层属性（gdf.attrs）。不写死。"""
    if buffer_km is not None:
        return float(buffer_km)
    attrs = getattr(gdf, "attrs", {}) or {}
    if "buffer_km" in attrs:
        return float(attrs["buffer_km"])
    return None


def _layer_label(gdf: Any, fallback: str) -> str:
    """图层图例标签。

    - 多要素图层（``len > 1``）：返回 ``fallback`` 通用名，不取单行 ``name``——
      避免「鼓楼区」这种以单行 name 以偏概全代表整层的情况。
    - 单要素图层：优先 ``name`` 列、其次 ``adcode`` 列，否则用 ``fallback``。
    """
    if gdf is None or len(gdf) == 0:
        return fallback
    if len(gdf) > 1:
        return fallback
    for column in ("name", "adcode"):
        if column in getattr(gdf, "columns", []):
            value = gdf.iloc[0][column]
            if value is not None and str(value).strip():
                return str(value)
    return fallback


@dataclass
class BufferReport:
    """一次 buffer 出图的结果，供回显与测试核对。"""

    layout: LayoutReport
    buffer_km: float | None = None
    legend_label: str = ""
    crs: str = ""
    summary: str = ""


@dataclass
class OverlayReport:
    """一次 overlay 出图的结果，供回显与测试核对。"""

    layout: LayoutReport
    base_label: str = ""
    other_label: str = ""
    crs: str = ""
    summary: str = ""


def render_buffer(
    spec: MapSpec,
    gdf: Any,
    *,
    original_gdf: Any = None,
    points_gdf: Any = None,
    buffer_km: float | None = None,
    unit: str | None = None,
    out_path: str | Path | None = None,
    pdf_path: str | Path | None = None,
) -> BufferReport:
    """渲染一张缓冲区分析图（不画坐标轴，版式要素由 `apply_layout` 补齐）。

    - ``gdf``：缓冲面 GeoDataFrame（Polygon，通常来自 `tools.analyze.buffer_layer`）。
    - ``original_gdf``：原始要素（点/线/面），只描边不填充，保留空间关系。
    - ``points_gdf``：站点/中心点，沿用点样式，画在最上层。
    - ``buffer_km``：缓冲半径（公里）；缺省时从 ``gdf.attrs["buffer_km"]`` 读。
    """
    frame = _reproject(gdf, spec, "缓冲面")
    original = _reproject(original_gdf, spec, "原始要素")
    points = _reproject(points_gdf, spec, "站点")

    radius = _resolve_buffer_km(gdf, buffer_km)
    buffer_color = palette_colors(spec, 2)[0]

    fig, ax = plt.subplots(figsize=spec.layout.size)

    # 图层顺序（从下到上）：缓冲面 → 原始要素边界 → 站点/中心点。
    frame.plot(
        ax=ax,
        color=buffer_color,
        alpha=BUFFER_ALPHA,
        edgecolor=BUFFER_EDGE,
        linewidth=1.0,
        zorder=1,
    )
    if original is not None:
        original.plot(
            ax=ax,
            facecolor="none",
            edgecolor=ORIGINAL_EDGE,
            linewidth=0.8,
            zorder=2,
        )
    if points is not None:
        points.plot(
            ax=ax,
            color=DEFAULT_POINT_COLOR,
            edgecolor=EDGE_COLOR,
            markersize=20,
            zorder=3,
        )

    ax.set_aspect(_aspect_for(spec.crs, spec.extent.bbox))
    ax.set_axis_off()
    content_bounds = None if frame.empty else tuple(float(v) for v in frame.total_bounds)
    minx, miny, maxx, maxy = drawing_extent(spec, content_bounds=content_bounds)
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)

    # 自定义图例：说明缓冲半径（不写死，从 buffer_km/图层属性读）。
    legend_label = f"{radius:g} km 缓冲区" if radius is not None else "缓冲区"
    if spec.layout.legend:
        ax.legend(
            handles=[
                Patch(
                    facecolor=buffer_color,
                    alpha=BUFFER_ALPHA,
                    edgecolor=BUFFER_EDGE,
                    label=legend_label,
                )
            ],
            loc="upper left",
            bbox_to_anchor=(1.02, 1.0),
            title="缓冲区",
        )

    layout = apply_layout(fig, ax, spec, unit=unit, legend_anchor=(1.02, 1.0))

    fig.canvas.draw()
    ax_bottom = ax.get_position().y0
    for text in fig.texts:
        text.set_va("top")
        text.set_y(ax_bottom - 0.02)

    if out_path is not None:
        fig.savefig(out_path, dpi=spec.layout.dpi, bbox_inches="tight")
    if pdf_path is not None:
        fig.savefig(pdf_path, dpi=spec.layout.dpi, bbox_inches="tight")

    summary = f"缓冲区分析：{len(frame)} 个缓冲面" + (
        f"，半径 {radius:g} km" if radius is not None else ""
    )
    return BufferReport(
        layout=layout,
        buffer_km=radius,
        legend_label=legend_label,
        crs=str(spec.crs),
        summary=summary,
    )


def render_overlay(
    spec: MapSpec,
    gdf: Any,
    *,
    other_gdf: Any = None,
    labels: tuple[str, str] | None = None,
    unit: str | None = None,
    out_path: str | Path | None = None,
    pdf_path: str | Path | None = None,
) -> OverlayReport:
    """渲染一张空间叠加图（不画坐标轴，版式要素由 `apply_layout` 补齐）。

    - ``gdf``：底层图层（面），浅色填充 alpha 0.5。
    - ``other_gdf``：上层图层（面），半透明填充 + 描边。
    - ``labels``：显式图例标签 ``(底层, 上层)``；缺省自动推断——底层多要素用「行政边界」
      这类通用名、单要素用 name 列；上层优先取 ``other_gdf.attrs["name"]``（如「站点缓冲区」），
      取不到退回 spec 里 kind=overlay 图层的 id。
    """
    if other_gdf is None:
        raise DataError("overlay 需要 other_gdf（上层图层）")
    base = _reproject(gdf, spec, "底层图层")
    other = _reproject(other_gdf, spec, "上层图层")

    colors = palette_colors(spec, 2)
    base_color = colors[0]
    other_color = colors[1]

    fig, ax = plt.subplots(figsize=spec.layout.size)

    base.plot(ax=ax, color=base_color, alpha=OVERLAY_ALPHA, edgecolor="none", zorder=1)
    other.plot(
        ax=ax,
        color=other_color,
        alpha=OVERLAY_ALPHA,
        edgecolor=OVERLAY_EDGE,
        linewidth=0.8,
        zorder=2,
    )

    ax.set_aspect(_aspect_for(spec.crs, spec.extent.bbox))
    ax.set_axis_off()
    minx, miny, maxx, maxy = _transformed_extent(spec)
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)

    overlay_layer_id = next((layer.id for layer in spec.layers if layer.kind == "overlay"), "上层")
    if labels is not None:
        base_label, other_label = labels
    else:
        base_label = _layer_label(gdf, "行政边界")
        attrs = getattr(other_gdf, "attrs", {}) or {}
        other_label = attrs.get("name") or _layer_label(other_gdf, overlay_layer_id)

    if spec.layout.legend:
        ax.legend(
            handles=[
                Patch(facecolor=base_color, alpha=OVERLAY_ALPHA, label=base_label),
                Patch(
                    facecolor=other_color,
                    alpha=OVERLAY_ALPHA,
                    edgecolor=OVERLAY_EDGE,
                    label=other_label,
                ),
            ],
            loc="upper left",
            bbox_to_anchor=(1.02, 1.0),
            title="图层",
        )

    layout = apply_layout(fig, ax, spec, unit=unit, legend_anchor=(1.02, 1.0))

    fig.canvas.draw()
    ax_bottom = ax.get_position().y0
    for text in fig.texts:
        text.set_va("top")
        text.set_y(ax_bottom - 0.02)

    if out_path is not None:
        fig.savefig(out_path, dpi=spec.layout.dpi, bbox_inches="tight")
    if pdf_path is not None:
        fig.savefig(pdf_path, dpi=spec.layout.dpi, bbox_inches="tight")

    summary = f"空间叠加：底层 {base_label}、上层 {other_label}"
    return OverlayReport(
        layout=layout,
        base_label=base_label,
        other_label=other_label,
        crs=str(spec.crs),
        summary=summary,
    )