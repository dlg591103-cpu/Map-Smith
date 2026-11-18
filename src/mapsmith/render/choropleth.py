"""T16 choropleth 渲染：按分级断点给面要素设色，并与 T15 版式要素组合。

规则来源：
- docs/facts/07 第 2 条（图例有分级断点与单位）、第 6 条（分级方法 + 级数）、
  第 8 条（连续量用单色渐变、禁止彩虹）、第 10 条（缺失值处理说明）。
- docs/facts/05 工具 5：`render(spec) -> {png, pdf}`。

数据契约：面要素与「逐面数值」由调用方准备好——站点→面的归属判断与聚合属于 T14
`analyze` 的 join，不在渲染层做。本模块只负责重投影、分级设色、与版式组合。

渲染层不得代填：分级方法、配色语义、缺失值说明只从 MapSpec 读取（facts/07 失败路径）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from pyproj import CRS, Transformer

from ..io.models import DataError
from ..spec import MapSpec
from .layout import (
    LayoutReport,
    apply_layout,
    legend_labels,
    palette_colors,
)

# 缺失值统一用中性灰，不参与配色方案（第 10 条要求在图外说明，说明文字仍来自 spec.notes）。
MISSING_COLOR = "#d9d9d9"
EDGE_COLOR = "#666666"


def class_index(value: Any, breaks: list[float | None]) -> int | None:
    """把数值落到 ``breaks`` 定义的级，返回 0 起的级序号；缺失返回 ``None``。

    区间按「≤ 上界」判定，与 `legend_labels` 的标签口径一致（同一函数生成的标签与设色
    必须对得上）。超出末级上界的值并入末级，避免整幅图因个别离群值被整体判为缺失。
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DataError(f"分级数值不是数字：{value!r}")
    if math.isnan(number):
        return None
    for index, upper in enumerate(breaks):
        if upper is None or number <= upper:
            return index
    return len(breaks) - 1


def assign_colors(
    values: list[Any],
    spec: MapSpec,
) -> tuple[list[str], list[int], int]:
    """按 spec 的分级断点与配色方案给每个面分配颜色。

    返回 ``(每个面的颜色, 各级面数, 缺失面数)``。配色与图例共用
    `palette_colors` / `legend_labels`，保证「图的颜色」与「图例的色块」逐级对应。
    """
    classification = spec.classification
    if classification is None:
        raise DataError("choropleth 渲染需要 spec.classification：分级断点缺失，无法设色")
    if not classification.breaks:
        raise DataError("spec.classification.breaks 为空，无法分级设色")

    colors = palette_colors(spec, classification.n)
    counts = [0] * classification.n
    missing = 0
    assigned: list[str] = []
    for value in values:
        index = class_index(value, classification.breaks)
        if index is None:
            missing += 1
            assigned.append(MISSING_COLOR)
            continue
        counts[index] += 1
        assigned.append(colors[index])
    return assigned, counts, missing


@dataclass
class ChoroplethReport:
    """一次 choropleth 出图的结果，供回显与测试核对。"""

    layout: LayoutReport
    colors: list[str] = field(default_factory=list)
    class_counts: list[int] = field(default_factory=list)
    missing_count: int = 0
    crs: str = ""
    summary: str = ""


def _transformed_extent(spec: MapSpec) -> tuple[float, float, float, float]:
    """把 spec.extent.bbox（GeoJSON 约定，输入侧 WGS84）换到输出坐标系。"""
    minx, miny, maxx, maxy = spec.extent.bbox
    if str(spec.crs).upper() in {"EPSG:4326", "EPSG:4490", "WGS84", "CGCS2000"}:
        return (minx, miny, maxx, maxy)
    transformer = Transformer.from_crs("EPSG:4326", spec.crs, always_xy=True)
    xs, ys = transformer.transform([minx, maxx], [miny, maxy])
    return (min(xs), min(ys), max(xs), max(ys))


def _aspect_for(crs_text: str, bbox: tuple[float, float, float, float]) -> float:
    """返回 matplotlib 的宽高比：投影坐标系恒为 1，地理坐标系按中心纬度修正。

    地理坐标系里 1° 经度的地面长度约为 1° 纬度的 cos(纬度) 倍；aspect 取 1/cos(纬度)
    才能让徐州（约 34.5°N）这类中纬度区域不被横向拉宽。
    """
    if not CRS.from_user_input(crs_text).is_geographic:
        return 1.0
    mid_lat = (bbox[1] + bbox[3]) / 2.0
    return 1.0 / math.cos(math.radians(mid_lat))


def _draw_inset_if_needed(
    fig: Figure,
    frame: Any,
    colors: list[str],
    spec: MapSpec,
) -> Axes | None:
    """主图范围外的要素画成右下角附图（如海南的南海诸岛）。

    主图取景会聚焦主体（见 `flow._core_bounds`），像三沙这种远离主体的面会落到
    图外。中国地图惯例要求这些区域以附图呈现，不能直接丢掉。

    返回附图 axes；没有图外要素时返回 None。
    """
    try:
        bounds = frame.geometry.bounds
    except Exception:  # noqa: BLE001 - 几何异常就不画附图
        return None
    if bounds is None or len(bounds) == 0:
        return None
    minx, miny, maxx, maxy = _transformed_extent(spec)
    eps = 1e-6
    inside = (
        (bounds["minx"] >= minx - eps)
        & (bounds["maxx"] <= maxx + eps)
        & (bounds["miny"] >= miny - eps)
        & (bounds["maxy"] <= maxy + eps)
    )
    outlier_mask = [not bool(value) for value in inside]
    if not any(outlier_mask):
        return None
    outliers = frame[outlier_mask]
    outlier_colors = [color for color, keep in zip(colors, outlier_mask) if keep]
    if len(outliers) == 0:
        return None

    inset = fig.add_axes([0.705, 0.035, 0.165, 0.22])
    outliers.plot(ax=inset, color=outlier_colors, edgecolor=EDGE_COLOR, linewidth=0.3)
    ob = outliers.total_bounds
    pad_x = max((ob[2] - ob[0]) * 0.06, eps)
    pad_y = max((ob[3] - ob[1]) * 0.06, eps)
    inset.set_xlim(ob[0] - pad_x, ob[2] + pad_x)
    inset.set_ylim(ob[1] - pad_y, ob[3] + pad_y)
    # 与主图用同一套 aspect 规则：地理坐标系按纬度修正，投影坐标系保持等距。
    inset.set_aspect(_aspect_for(spec.crs, spec.extent.bbox))
    inset.set_axis_off()
    inset.add_patch(
        Rectangle(
            (0, 0),
            1,
            1,
            transform=inset.transAxes,
            fill=False,
            edgecolor="#888888",
            linewidth=0.6,
            zorder=10,
        )
    )
    names = " ".join(str(name) for name in outliers.get("name", [])) if "name" in outliers.columns else ""
    label = "南海诸岛" if ("三沙" in names or "南海" in names) else "图外区域"
    inset.text(
        0.03,
        0.97,
        label,
        transform=inset.transAxes,
        fontsize=7,
        va="top",
        ha="left",
        color="#555555",
    )
    return inset


def render_choropleth(
    spec: MapSpec,
    gdf: Any,
    *,
    field: str | None = None,
    unit: str | None = None,
    out_path: str | Path | None = None,
    pdf_path: str | Path | None = None,
) -> ChoroplethReport:
    """渲染一张分级设色地图（不画坐标轴，版式要素由 `apply_layout` 补齐）。

    ``gdf`` 需带坐标系（GeoDataFrame）；``field`` 缺省取 spec 里 kind=choropleth 图层的
    ``field``。数值缺失的面用 `MISSING_COLOR` 填充并计入 `missing_count`。
    """
    field = field or next(
        (layer.field for layer in spec.layers if layer.kind == "choropleth" and layer.field),
        None,
    )
    if not field:
        raise DataError("choropleth 渲染缺少数值字段：请传 field 或让图层提供 field")
    if field not in getattr(gdf, "columns", []):
        raise DataError(f"图层中没有字段 {field!r}，现有字段：{list(getattr(gdf, 'columns', []))}")
    if getattr(gdf, "crs", None) is None:
        raise DataError("图层缺少坐标系（crs 为空），无法按 spec.crs 重投影")

    frame = gdf.to_crs(spec.crs) if str(gdf.crs) != str(spec.crs) else gdf
    values = list(frame[field])
    colors, counts, missing = assign_colors(values, spec)

    fig, ax = plt.subplots(figsize=spec.layout.size)
    frame.plot(ax=ax, color=colors, edgecolor=EDGE_COLOR, linewidth=0.6)
    ax.set_aspect(_aspect_for(spec.crs, spec.extent.bbox))
    ax.set_axis_off()

    minx, miny, maxx, maxy = _transformed_extent(spec)
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)

    # 主图范围外的面（如海南的三沙远海岛礁）画成右下角附图，避免「只收束就丢区域」。
    _draw_inset_if_needed(fig, frame, colors, spec)

    # 主体占满图幅，图例放到图框外右侧，避免压住面要素。
    # buffer 图按 SPEC 3.1 把半径与参与站点数写进图例副标题；文字取自 spec.notes，
    # 渲染层不改写内容，也不据此推断任何数据结论。
    legend_note = None
    if spec.map_type == "buffer":
        buffer_note = next((note for note in spec.notes if note.startswith("缓冲距离")), None)
        if buffer_note:
            # 图例框宽度由色块标签决定，长句会溢出边框；这里只取前两段并拆成两行，
            # 完整的缺失值说明仍保留在底部注记。
            parts = [part.strip() for part in buffer_note.split("；") if part.strip()]
            if len(parts) >= 2:
                # 第二段形如「9/10 个缓冲面含站点，无站点缓冲面按缺失处理」，逗号后的说明留在底部注记。
                second = parts[1].split("，")[0].replace("个缓冲面含站点", "面含站点")
                legend_note = f"{parts[0]}\n{second}"
            else:
                legend_note = parts[0] if parts else None
    layout = apply_layout(
        fig,
        ax,
        spec,
        unit=unit,
        legend_anchor=(1.02, 1.0),
        legend_note=legend_note,
    )

    # 地理坐标系下 1° 纬度和 1° 经度的实际长度不同，aspect 已按纬度修正；此时地图在
    # 图幅内上下留白，把底部注记挪到图框正下方，避免图名与注记之间出现大片空白。
    fig.canvas.draw()
    ax_bottom = ax.get_position().y0
    for text in fig.texts:
        text.set_va("top")
        text.set_y(ax_bottom - 0.02)

    if out_path is not None:
        fig.savefig(out_path, dpi=spec.layout.dpi, bbox_inches="tight")
    if pdf_path is not None:
        fig.savefig(pdf_path, dpi=spec.layout.dpi, bbox_inches="tight")

    drawn = sum(counts)
    summary = (
        f"{drawn} 个面已分级设色，缺失 {missing} 个"
        if missing
        else f"{drawn} 个面已分级设色"
    )
    return ChoroplethReport(
        layout=layout,
        colors=colors,
        class_counts=counts,
        missing_count=missing,
        crs=str(spec.crs),
        summary=summary,
    )
