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

import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

from ..io.models import DataError
from ..spec import MapSpec
from .choropleth import MISSING_COLOR, _aspect_for, _transformed_extent, class_index
from .fonts import load_chinese_font
from .layout import (
    _POINT_NORTH_ARROW_CANDIDATES,
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

# 标注避让：依次尝试 8 个方向，取与气泡、已放置标签重叠最小且在坐标区内的位置。
_LABEL_OFFSETS = (
    (1.0, 0.0),
    (1.0, 1.0),
    (0.0, 1.0),
    (-1.0, 1.0),
    (-1.0, 0.0),
    (-1.0, -1.0),
    (0.0, -1.0),
    (1.0, -1.0),
)
_LABEL_FONT_PT = 8.0
_LABEL_PAD_PT = 3.0
_LABEL_HALO_PT = 2.5
_LABEL_HALO_COLOR = "#ffffff"


def _rect(bbox: Any) -> tuple[float, float, float, float]:
    """matplotlib Bbox → (x0, y0, x1, y1)，便于做重叠面积计算。"""
    return (float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1))


def _rect_area(rect: tuple[float, float, float, float]) -> float:
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


def _rect_overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0.0 or height <= 0.0:
        return 0.0
    return width * height


def _label_score(
    rect: tuple[float, float, float, float],
    obstacles: list[tuple[float, float, float, float]],
    placed: list[tuple[float, float, float, float]],
    frame: tuple[float, float, float, float],
) -> float:
    """分数越低越好：压气泡、压已放置标签、越出坐标区分别按权重累计。"""
    score = sum(_rect_overlap(rect, item) for item in obstacles)
    score += 2.0 * sum(_rect_overlap(rect, item) for item in placed)
    score += 3.0 * (_rect_area(rect) - _rect_overlap(rect, frame))
    return score


def _place_labels(
    fig: Any,
    ax: Any,
    xs: Any,
    ys: Any,
    labels: Any,
    sizes: Any,
) -> None:
    """逐点放置标注：优先选不压气泡、不压已放置标签、不出坐标区的方向。

    8 个方向都无法避免碰撞时，取重叠面积最小的方向，并给文字加白色描边，
    保证压在气泡上仍然可读。字体在此显式加载，避免在 `apply_layout` 之前
    用默认西文字体测量中文宽度。
    """
    font = load_chinese_font()
    try:
        renderer = fig.canvas.get_renderer()
    except AttributeError:  # 部分交互后端在首次绘制前没有 renderer
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()

    display = ax.transData.transform(np.column_stack([xs, ys]))
    dpi = float(fig.dpi)
    radii = np.sqrt(np.clip(np.asarray(sizes, dtype=float), 0.0, None)) / 2.0 * dpi / 72.0
    obstacles = [
        (float(px - r), float(py - r), float(px + r), float(py + r))
        for (px, py), r in zip(display, radii)
    ]
    frame = (float(ax.bbox.x0), float(ax.bbox.y0), float(ax.bbox.x1), float(ax.bbox.y1))
    placed: list[tuple[float, float, float, float]] = []
    halo = [path_effects.withStroke(linewidth=_LABEL_HALO_PT, foreground=_LABEL_HALO_COLOR)]

    for xi, yi, radius, text in zip(xs, ys, radii, labels):
        offset = radius * 72.0 / dpi + _LABEL_PAD_PT
        best: tuple[float, float] | None = None
        best_score: float | None = None
        for ux, uy in _LABEL_OFFSETS:
            dx, dy = ux * offset, uy * offset
            probe = ax.annotate(
                str(text),
                (xi, yi),
                textcoords="offset points",
                xytext=(dx, dy),
                fontsize=_LABEL_FONT_PT,
                fontfamily=font,
            )
            score = _label_score(
                _rect(probe.get_window_extent(renderer)), obstacles, placed, frame
            )
            probe.remove()
            if best_score is None or score < best_score:
                best_score = score
                best = (dx, dy)
            if score == 0.0:
                break
        if best is None:
            continue
        dx, dy = best
        artist = ax.annotate(
            str(text),
            (xi, yi),
            textcoords="offset points",
            xytext=(dx, dy),
            fontsize=_LABEL_FONT_PT,
            fontfamily=font,
            zorder=6,
        )
        artist.set_path_effects(halo)
        placed.append(_rect(artist.get_window_extent(renderer)))


def _fmt(value: float) -> str:
    if float(value) == int(value):
        return str(int(value))
    return f"{value:g}"


def _is_crowded(frame: Any, view_width: float) -> bool:
    """站点在视野内是否过密：任意两站最小间距 < 视野宽度的 2%。

    2% 约等于「两个气泡在图幅上必然互相重叠」的尺度。过密时继续画气泡会糊成
    一团，改用底图面域聚合表达数值。
    """
    if frame is None or len(frame) < 2 or view_width <= 0:
        return False
    try:
        xs = np.asarray(frame.geometry.x, dtype=float)
        ys = np.asarray(frame.geometry.y, dtype=float)
    except Exception:  # noqa: BLE001 - 几何缺失时按不拥挤处理
        return False
    min_d = float("inf")
    n = len(xs)
    for i in range(n):
        for j in range(i + 1, n):
            d = math.hypot(xs[i] - xs[j], ys[i] - ys[j])
            if d < min_d:
                min_d = d
    return min_d / view_width < 0.02


def _draw_aggregated_background(
    ax: Any, spec: MapSpec, points: Any, background: Any, field: str
) -> bool:
    """站点过密时：把站点值按行政区聚合，给底图分级着色。成功返回 True。

    聚合口径为「区县内站点该字段的算术平均」（缺测不参与）；无站点的区县用
    `MISSING_COLOR`。站点位置另以小号空心圆标注，保留真实空间位置。
    """
    classification = spec.classification
    if classification is None or not classification.breaks:
        return False
    try:
        import geopandas as gpd  # 局部导入：只有拥挤分支用得到
        import pandas as pd
    except ImportError:  # pragma: no cover - 运行环境已锁依赖
        return False

    try:
        admin = background.copy()
        joined = gpd.sjoin(points, admin[["geometry"]], how="inner", predicate="within")
    except Exception:  # noqa: BLE001 - 空间关联失败则退回普通底图
        return False
    if joined is None or len(joined) == 0:
        return False

    agg = joined.groupby("index_right")[field].mean()
    admin["_agg_value"] = agg.reindex(admin.index)
    if int(admin["_agg_value"].notna().sum()) < 2:
        return False

    palette = palette_colors(spec, classification.n)
    colors = []
    for value in admin["_agg_value"]:
        idx = None if pd.isna(value) else class_index(value, classification.breaks)
        colors.append(MISSING_COLOR if idx is None else palette[idx])
    admin.plot(ax=ax, color=colors, edgecolor="#8f9aa6", linewidth=0.6, zorder=0)
    return True


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
    background: bool = False


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
    background_gdf: Any = None,
    out_path: str | Path | None = None,
    pdf_path: str | Path | None = None,
) -> PointReport:
    """渲染一张点图 / 气泡图（不画坐标轴，版式要素由 `apply_layout` 补齐）。

    - ``gdf`` 需带坐标系，几何为 Point。
    - ``background_gdf`` 可选面图层（如行政边界），画成浅灰底色，避免点图落在空白图上。
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

    # --- 取景与画布版式 ---
    # 点图要表达「站点在行政区中的位置」，因此取景用完整行政区范围
    # （spec.extent.bbox），底图 10 个区县全显示；不再按站点分布收窄——收窄会让
    # 底图只剩城区几个区，观感上像「底图不全」。
    content_bounds = None if frame.empty else tuple(float(v) for v in frame.total_bounds)
    aspect = _aspect_for(spec.crs, spec.extent.bbox)
    eminx, eminy, emaxx, emaxy = _transformed_extent(spec)
    minx, miny, maxx, maxy = eminx, eminy, emaxx, emaxy

    # 边距（英寸）：右侧单独留出图例区，图例画在轴外，不再叠在地图上压住站点名；
    # 画布高度按地图真实宽高比反推，地图正好铺满图框，避免上下留大片空白。
    left_pad, right_pad = 0.18, 0.18
    legend_pad = 2.60
    top_pad, bottom_pad = 0.45, 1.15
    map_w_in = max(spec.layout.size[0] - left_pad - right_pad, 2.0)

    dw = maxx - minx
    dh = maxy - miny
    map_ratio = (dw / (dh * aspect)) if (dw > 0 and dh > 0) else 1.25
    ax_w_in = map_w_in
    ax_h_in = max(ax_w_in / max(map_ratio, 0.05), 2.0)

    fig_w = left_pad + ax_w_in + legend_pad + right_pad
    fig_h = top_pad + ax_h_in + bottom_pad
    target_ratio = ax_w_in / ax_h_in  # 与地图像素宽高比一致，下面的扩展逻辑只作兜底

    eminx, eminy, emaxx, emaxy = _transformed_extent(spec)
    dw = maxx - minx
    dh = maxy - miny
    if dw > 0 and dh > 0:
        cur_ratio = dw / (dh * aspect)
        if cur_ratio < target_ratio:
            # 取景偏竖：横向扩展（受 extent 约束，不会画出图幅之外）
            need = target_ratio * dh * aspect
            extra = (need - dw) / 2.0
            minx = max(minx - extra, eminx)
            maxx = min(maxx + extra, emaxx)
        elif cur_ratio > target_ratio:
            # 取景偏扁：纵向扩展
            need = dw / (target_ratio * aspect)
            extra = (need - dh) / 2.0
            miny = max(miny - extra, eminy)
            maxy = min(maxy + extra, emaxy)

    # --- 画点 ---
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    # 轴框按英寸比例精确落位，且不用 bbox_inches="tight"（它会把标题与框外图例裁掉）。
    fig.subplots_adjust(
        left=left_pad / fig_w,
        right=(left_pad + ax_w_in) / fig_w,
        bottom=bottom_pad / fig_h,
        top=(bottom_pad + ax_h_in) / fig_h,
    )
    background_drawn = False
    # 站点在视野里过于密集时，气泡会叠成一团、读不出内容。此时改为「底图按站点
    # 聚合值分级着色 + 站点以小空心圆标位置」，既保留点图的真实位置，又能读出数值。
    crowded = _is_crowded(frame, maxx - minx)
    aggregated = False
    if background_gdf is not None and getattr(background_gdf, "empty", True) is False:
        if getattr(background_gdf, "crs", None) is not None:
            background = (
                background_gdf.to_crs(spec.crs)
                if str(background_gdf.crs) != str(spec.crs)
                else background_gdf
            )
            if crowded:
                aggregated = _draw_aggregated_background(ax, spec, frame, background, field)
            if not aggregated:
                background.plot(
                    ax=ax,
                    facecolor="#e9eef4",
                    edgecolor="#b9c3cf",
                    linewidth=0.7,
                    zorder=0,
                )
            background_drawn = True
    x = np.asarray(frame.geometry.x, dtype=float)
    y = np.asarray(frame.geometry.y, dtype=float)
    missing_arr = np.asarray(size_result.missing_mask, dtype=bool)
    valid_arr = ~missing_arr
    sizes_arr = np.asarray(size_result.sizes, dtype=float)

    # 视野比站点分布大得多时放大气泡：完整行政区（2.3°）对照城区站点（0.3°）时，
    # 原始尺寸会让站点缩成小点。按面积开方缩放（≈半径线性），上限 3 倍。
    size_scale = 1.0
    if content_bounds is not None:
        content_w = float(content_bounds[2] - content_bounds[0])
        view_w = maxx - minx
        if content_w > 0 and view_w > 0:
            size_scale = min(max((view_w / content_w) ** 0.5, 1.0), 3.0)
    display_sizes = sizes_arr * size_scale

    if aggregated:
        # 拥挤模式：数值已由底图面域表达，站点只画小号空心圆定位，避免叠成一团。
        ax.scatter(
            x,
            y,
            s=40.0,
            facecolors="none",
            edgecolors="#333333",
            linewidths=1.1,
            zorder=4,
        )
    else:
        if valid_arr.any():
            ax.scatter(
                x[valid_arr],
                y[valid_arr],
                s=display_sizes[valid_arr],
                c=np.asarray(color_list)[valid_arr],
                edgecolors=EDGE_COLOR,
                linewidths=0.6,
                zorder=3,
            )
        if missing_arr.any():
            ax.scatter(
                x[missing_arr],
                y[missing_arr],
                s=display_sizes[missing_arr],
                facecolors="none",
                edgecolors=MISSING_EDGE,
                linewidths=1.0,
                zorder=3,
            )

    ax.set_aspect(aspect)
    ax.set_axis_off()
    # 取景范围已在创建 figure 前算好（完整行政区），这里直接应用。
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)

    # 站点只覆盖视野一小部分时，在图外说明覆盖范围（渲染层补充，不改 spec.notes）。
    extra_note: str | None = None
    draw_w = maxx - minx
    if content_bounds is not None and draw_w > 0:
        content_w = float(content_bounds[2] - content_bounds[0])
        if content_w / draw_w < 0.5:
            content_m = metric_extent(
                tuple(content_bounds), source_crs=str(spec.crs)  # type: ignore[arg-type]
            )
            km = (content_m[2] - content_m[0]) / 1000.0
            extra_note = f"注记：站点仅覆盖图幅局部，分布范围约 {km:g} km"
    if aggregated:
        agg_note = "站点较密，数值已按区县聚合为面域分级；空心圆为监测站位置"
        if extra_note:
            extra_note = "注记：" + extra_note.replace("注记：", "") + "；" + agg_note
        else:
            extra_note = "注记：" + agg_note

    # --- 标注 ---
    if label_field is not None and spec.annotation.show:
        _place_labels(fig, ax, x, y, frame[label_field].astype(str).tolist(), display_sizes)

    # --- 气泡大小三级图例（先画并 add_artist，让 apply_layout 的断点图例成为主图例）---
    # 分档口径与颜色分级图例对齐：取 classification 断点的下界/中值/上界，
    # 避免「断裂点 47.6-58」与「气泡 45/51.5/58」两套数字并存造成误读。
    if (
        not aggregated  # 聚合模式下站点是固定大小定位标记，没有大小映射，不画大小图例
        and spec.layout.legend
        and size_result.vmin is not None
        and size_result.vmax is not None
        and size_result.vmin != size_result.vmax
    ):
        breaks = [b for b in (spec.classification.breaks if spec.classification else []) if b is not None]
        if len(breaks) >= 3:
            level_values = (breaks[0], breaks[len(breaks) // 2], breaks[-1])
        else:
            mid = (size_result.vmin + size_result.vmax) / 2.0
            level_values = (size_result.vmin, mid, size_result.vmax)
        handles = [
            _size_handle(size_map(v, size_result.vmin, size_result.vmax)) for v in level_values
        ]
        labels = [_fmt(v) for v in level_values]
        title = "气泡大小" + (f"（{unit}）" if unit else "")
        # 图例画在轴外右侧的专用留白里：内嵌到图内会压住站点名（杭州这类站点
        # 集中在东北城区时尤其明显），移到框外后地图与图例互不遮挡。
        size_legend = ax.legend(
            handles=handles,
            labels=labels,
            loc="upper left",
            bbox_to_anchor=(1.02, 0.62),
            title=title,
            framealpha=0.92,
        )
        ax.add_artist(size_legend)

    # --- 版式要素 + 断点图例 ---
    # 断点图例同样画在轴外右侧留白区，与气泡大小图例上下排布，不压地图。
    layout = apply_layout(
        fig,
        ax,
        spec,
        unit=unit,
        legend_anchor=(1.02, 1.0),
        north_arrow_candidates=_POINT_NORTH_ARROW_CANDIDATES,
        extra_note=extra_note,
        # 保留颜色分级图例：点仍按分级着色，没有图例解释颜色会让读者看不懂；
        # 与气泡大小图例并存（口径已在上方对齐到同一组断点）。
        class_legend=True,
    )

    # 版式注记下移到图框正下方（与 choropleth 一致的留白处理）。
    fig.canvas.draw()
    ax_bottom = ax.get_position().y0
    for text in fig.texts:
        text.set_va("top")
        text.set_y(ax_bottom - 0.02)

    # 版式已在 subplots_adjust 里留好空间，直接按 figure 尺寸出图，
    # 不用 bbox_inches="tight"：实测它会把标题与右侧图例一起裁掉。
    if out_path is not None:
        fig.savefig(out_path, dpi=spec.layout.dpi)
    if pdf_path is not None:
        fig.savefig(pdf_path, dpi=spec.layout.dpi)

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
        background=background_drawn,
    )