"""T18 IDW 渲染：仅在站点凸包内做 IDW 插值，图例标注示意。

规则来源：
- docs/facts/04：只在站点凸包内插值，凸包外不着色，图例注明「无站点覆盖区域未插值」，不做外推。
- docs/facts/07 第 8 条：连续量用单色渐变、禁止彩虹。
- docs/facts/05 工具 5：`render(spec) -> {png, pdf}`。
- docs/Spec T18：仅凸包内插值，图例标注示意。

数据契约：只接收已带坐标的点 GeoDataFrame（geometry 为 Point）与数值字段；渲染层
不读 CSV、不做空间聚合（属于 T07 / T14）。IDW 插值在度量投影下进行（保证距离以米
为单位），插值栅格转回输出 CRS 显示。缺测点（NaN）不参与插值。

渲染层不得代填：分级方法、配色语义、缺失值说明只从 MapSpec 读取（facts/07 失败路径）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch
from scipy.interpolate import griddata
from scipy.spatial import ConvexHull

from ..io.models import DataError
from ..spec import MapSpec
from .choropleth import _aspect_for, _transformed_extent
from .layout import (
    LayoutReport,
    _place_labels_avoiding_overlap,
    apply_layout,
    legend_labels,
    palette_colors,
)

EDGE_COLOR = "#666666"
MISSING_EDGE = "#999999"
DEFAULT_POINT_COLOR = "#1f77b4"
# IDW 幂参数：p=2 是最常用值，控制距离衰减速率。
IDW_POWER = 2.0
# 栅格分辨率（像元数）：在度量投影下按 bbox 长边取 N 个像元。
GRID_N = 200


def _idw(
    points: np.ndarray,
    values: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    *,
    power: float = IDW_POWER,
) -> np.ndarray:
    """简单 IDW 插值：对每个栅格像元，按距离倒数加权平均站点值。

    ``points`` 形状 (n, 2)，``values`` 形状 (n,)，``grid_x`` / ``grid_y`` 形状 (h, w)。
    返回 ``(h, w)`` 的插值结果；像元到所有站点距离为零时直接取该站值。
    """
    h, w = grid_x.shape
    result = np.full((h, w), np.nan, dtype=float)
    flat_x = grid_x.ravel()
    flat_y = grid_y.ravel()

    for i in range(flat_x.size):
        gx, gy = flat_x[i], flat_y[i]
        dx = points[:, 0] - gx
        dy = points[:, 1] - gy
        dist_sq = dx * dx + dy * dy
        zero_mask = dist_sq == 0.0
        if zero_mask.any():
            result.ravel()[i] = values[zero_mask].mean()
            continue
        dist = np.sqrt(dist_sq)
        weights = 1.0 / np.power(dist, power)
        result.ravel()[i] = np.sum(weights * values) / np.sum(weights)

    return result


def _hull_mask(
    points_xy: np.ndarray,
    grid_x: np.ndarray,
    grid_y: np.ndarray,
) -> np.ndarray:
    """返回凸包内像元为 True 的布尔掩码；站点少于 3 个时全 False。"""
    if len(points_xy) < 3:
        return np.zeros_like(grid_x, dtype=bool)
    hull = ConvexHull(points_xy)
    hull_pts = points_xy[hull.vertices]
    h, w = grid_x.shape
    flat_x = grid_x.ravel()
    flat_y = grid_y.ravel()
    mask = np.zeros(flat_x.size, dtype=bool)
    for i in range(flat_x.size):
        if _point_in_polygon(flat_x[i], flat_y[i], hull_pts):
            mask[i] = True
    return mask.reshape(h, w)


def _point_in_polygon(x: float, y: float, polygon: np.ndarray) -> bool:
    """射线法判断点是否在凸多边形内。"""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi
        ):
            inside = not inside
        j = i
    return inside


@dataclass
class IDWReport:
    """一次 IDW 出图的结果，供回显与测试核对。"""

    layout: LayoutReport
    grid_shape: tuple[int, int] = (0, 0)
    hull_area_km2: float = 0.0
    valid_points: int = 0
    missing_points: int = 0
    crs: str = ""
    summary: str = ""


def render_idw(
    spec: MapSpec,
    gdf: Any,
    *,
    field: str | None = None,
    label_field: str | None = None,
    unit: str | None = None,
    out_path: str | Path | None = None,
    pdf_path: str | Path | None = None,
) -> IDWReport:
    """渲染一张 IDW 空间插值面图（不画坐标轴，版式要素由 `apply_layout` 补齐）。

    - ``gdf`` 需带坐标系，几何为 Point。
    - ``field`` 缺省取 spec 里 kind=idw 图层的 field。
    - IDW 在度量投影下计算，插值栅格转回输出 CRS 显示。
    - 只在站点凸包内插值，凸包外不着色。
    - 缺测点（None / NaN）不参与插值，画灰色空心点。
    """
    if getattr(gdf, "crs", None) is None:
        raise DataError("图层缺少坐标系（crs 为空），无法做 IDW 插值")
    geom_types = {str(t) for t in getattr(gdf, "geom_type", [])}
    if not geom_types or not geom_types.issubset({"Point", "MultiPoint"}):
        raise DataError(f"IDW 插值只接收点几何，实际为：{'、'.join(sorted(geom_types))}")

    field = field or next(
        (layer.field for layer in spec.layers if layer.kind == "idw" and layer.field),
        None,
    )
    if not field:
        raise DataError("IDW 渲染缺少数值字段：请传 field 或让图层提供 field")
    if field not in getattr(gdf, "columns", []):
        raise DataError(f"图层中没有字段 {field!r}，现有字段：{list(getattr(gdf, 'columns', []))}")

    label_field = label_field or spec.annotation.label_field
    if label_field is not None and label_field not in getattr(gdf, "columns", []):
        raise DataError(
            f"图层中没有标注字段 {label_field!r}，现有字段：{list(getattr(gdf, 'columns', []))}"
        )

    # --- 分离有效点与缺测点 ---
    frame = gdf.to_crs(spec.crs) if str(gdf.crs) != str(spec.crs) else gdf
    raw_values = list(frame[field])
    all_x = np.asarray(frame.geometry.x, dtype=float)
    all_y = np.asarray(frame.geometry.y, dtype=float)

    valid_mask = np.ones(len(raw_values), dtype=bool)
    parsed_values: list[float] = []
    for idx, value in enumerate(raw_values):
        if value is None:
            valid_mask[idx] = False
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise DataError(f"IDW 数值不是数字：{value!r}") from exc
        if math.isnan(number):
            valid_mask[idx] = False
            continue
        parsed_values.append(number)

    valid_count = len(parsed_values)
    missing_count = int(len(raw_values) - valid_count)

    if valid_count < 3:
        raise DataError(
            f"IDW 插值至少需要 3 个有效站点，当前只有 {valid_count} 个"
            + (f"（{missing_count} 个缺测）" if missing_count else "")
        )

    valid_x = all_x[valid_mask]
    valid_y = all_y[valid_mask]
    valid_vals = np.asarray(parsed_values, dtype=float)

    # --- 在度量投影下做 IDW 插值 ---
    from ..projection import choose_measurement_crs

    bbox_wgs84 = spec.extent.bbox
    measurement = choose_measurement_crs(bbox_wgs84).crs

    frame_meas = frame.to_crs(measurement)
    meas_x = np.asarray(frame_meas.geometry.x, dtype=float)[valid_mask]
    meas_y = np.asarray(frame_meas.geometry.y, dtype=float)[valid_mask]
    points_meas = np.column_stack([meas_x, meas_y])

    minx_m, miny_m = meas_x.min(), meas_y.min()
    maxx_m, maxy_m = meas_x.max(), meas_y.max()
    # 微扩边界避免边缘像元刚好落在凸包外。
    pad = (maxx_m - minx_m) * 0.02
    minx_m -= pad
    miny_m -= pad
    maxx_m += pad
    maxy_m += pad

    gx = np.linspace(minx_m, maxx_m, GRID_N)
    gy = np.linspace(miny_m, maxy_m, GRID_N)
    grid_x, grid_y = np.meshgrid(gx, gy)

    grid_z = _idw(points_meas, valid_vals, grid_x, grid_y, power=IDW_POWER)
    hull = _hull_mask(points_meas, grid_x, grid_y)
    grid_z[~hull] = np.nan

    hull_area_m2 = float(
        (hull.sum()) * ((maxx_m - minx_m) / GRID_N) * ((maxy_m - miny_m) / GRID_N)
    )
    hull_area_km2 = hull_area_m2 / 1e6

    # --- 把栅格坐标从度量投影转回输出 CRS，用 imshow 显示 ---
    from pyproj import Transformer

    transformer = Transformer.from_crs(measurement, spec.crs, always_xy=True)
    grid_x_out, grid_y_out = transformer.transform(grid_x, grid_y)

    # imshow 需要规则网格的 extent；用输出 CRS 的 bbox。
    extent_out = _transformed_extent(spec)
    minx_o, miny_o, maxx_o, maxy_o = extent_out

    fig, ax = plt.subplots(figsize=spec.layout.size)

    # IDW 是连续插值面，用连续色阶渲染；图例用分级断点 Patch 做示意性标注。
    cmap = plt.get_cmap(spec.palette.scheme)
    vmin = float(np.nanmin(grid_z))
    vmax = float(np.nanmax(grid_z))
    ax.imshow(
        grid_z,
        extent=(minx_o, maxx_o, miny_o, maxy_o),
        origin="lower",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        aspect=_aspect_for(spec.crs, spec.extent.bbox),
        zorder=1,
    )

    # --- 站点叠加 ---
    if missing_count > 0:
        ax.scatter(
            all_x[~valid_mask],
            all_y[~valid_mask],
            s=30,
            facecolors="none",
            edgecolors=MISSING_EDGE,
            linewidths=1.0,
            zorder=3,
        )
    ax.scatter(
        valid_x,
        valid_y,
        s=25,
        c=DEFAULT_POINT_COLOR,
        edgecolors=EDGE_COLOR,
        linewidths=0.5,
        zorder=3,
    )

    # --- 标注 ---
    if label_field is not None and spec.annotation.show:
        label_coords = [(float(xi), float(yi)) for xi, yi in zip(all_x, all_y)]
        label_texts = [str(t) for t in frame[label_field].astype(str)]
        _place_labels_avoiding_overlap(ax, label_coords, label_texts, fontsize=6)

    ax.set_axis_off()
    ax.set_xlim(minx_o, maxx_o)
    ax.set_ylim(miny_o, maxy_o)

    # --- 版式要素（含断点图例，由 apply_layout 统一画） ---
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

    summary = (
        f"IDW 插值：{valid_count} 个有效站点，凸包面积 {hull_area_km2:.1f} km²，"
        f"栅格 {GRID_N}×{GRID_N}，度量投影 {measurement}"
    )
    if missing_count:
        summary += f"，缺测 {missing_count} 个站点未参与插值"

    return IDWReport(
        layout=layout,
        grid_shape=(GRID_N, GRID_N),
        hull_area_km2=round(hull_area_km2, 2),
        valid_points=valid_count,
        missing_points=missing_count,
        crs=str(spec.crs),
        summary=summary,
    )