"""T11 数据体检与两档插值判定。

判定规则（docs/facts/04-三Agent与协作协议.md「数据降级规则」）：
- 只看两项：有效站数 `n`（剔除缺测后）与空间覆盖度 `cover`（站点凸包面积 / 研究区面积）。
- 通过：`n >= 10` 且 `cover >= 0.5` → IDW 成面。
- 不通过：降级为点图 / 气泡图 + 城市面底色。
- 硬下限：`n < 3` → 放弃该指标，反问用户换指标或换区域。
- 字段缺失：换指标并明确告知用户。

面积在度量投影下计算，投影由 `projection.choose_measurement_crs` 选择并回显
（docs/facts/02「内部量算」）。判定理由固定三行：站数、覆盖度、结论。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPoint

from ..io.models import DataError, DataLayer, FieldMissing
from ..projection import choose_measurement_crs

Decision = Literal["idw", "degrade", "reject"]

MIN_STATIONS_FOR_SURFACE = 10
MIN_COVERAGE_FOR_SURFACE = 0.5
HARD_MIN_STATIONS = 3

# 体检时不算指标的列：坐标与站点属性。缺了这条，未指定字段时会把 lon/lat 当成候选。
_NON_INDICATOR_COLUMNS = {"lon", "lat", "station_code", "station_name", "city"}


@dataclass(frozen=True)
class DataProfile:
    """一次数据体检结果；`reason_lines` 正好三行，可直接写进 MapSpec.notes。"""

    n_valid: int
    total: int
    completeness: float
    decision: Decision
    cover: float | None
    reason_lines: tuple[str, str, str]
    summary: str
    value_min: float | None = None
    value_max: float | None = None
    value_mean: float | None = None
    measurement_crs: str | None = None
    hull_area_km2: float | None = None
    study_area_km2: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def _study_area_frame(study_area: DataLayer | gpd.GeoDataFrame | None) -> gpd.GeoDataFrame | None:
    if study_area is None:
        return None
    if isinstance(study_area, DataLayer):
        if study_area.gdf is None:
            raise DataError(f"{study_area.name} 没有几何，不能作为研究区")
        frame = study_area.gdf
    else:
        frame = study_area
    if frame.empty:
        raise DataError("研究区边界为空")
    if frame.crs is None:
        raise DataError("研究区边界没有坐标系，无法计算覆盖度")
    return frame


def _coverage(
    points: gpd.GeoDataFrame,
    study_area: gpd.GeoDataFrame | None,
    measurement_crs: str,
) -> tuple[float | None, float | None, float | None]:
    """返回 (cover, hull_area_km2, study_area_km2)。

    站点少于 3 个或共线时凸包面积可能为 0，此时 cover 记为 0.0，不能通过。
    """
    if study_area is None:
        return (None, None, None)

    points_proj = points.to_crs(measurement_crs)
    area_proj = study_area.to_crs(measurement_crs)

    coords = [(geom.x, geom.y) for geom in points_proj.geometry if geom is not None]
    if not coords:
        return (0.0, 0.0, None)
    hull = MultiPoint(coords).convex_hull

    study_union = area_proj.union_all()
    study_area_m2 = float(study_union.area)
    if study_area_m2 <= 0:
        raise DataError("研究区面积为 0，无法计算覆盖度")

    # 凸包可能部分超出研究区，按不超出处理，避免 cover > 1 误导结论。
    clipped = hull.intersection(study_union)
    cover = float(clipped.area) / study_area_m2 if clipped.area > 0 else 0.0
    cover = max(0.0, min(1.0, cover))

    return (cover, float(hull.area) / 1e6, study_area_m2 / 1e6)


def _decision(n_valid: int, cover: float | None) -> Decision:
    if n_valid < HARD_MIN_STATIONS:
        return "reject"
    if n_valid < MIN_STATIONS_FOR_SURFACE:
        return "degrade"
    if cover is None or cover < MIN_COVERAGE_FOR_SURFACE:
        return "degrade"
    return "idw"


def _reason_lines(n_valid: int, cover: float | None, decision: Decision) -> tuple[str, str, str]:
    line1 = f"站数：有效 {n_valid} 个（成面阈值 ≥{MIN_STATIONS_FOR_SURFACE}）"
    if cover is None:
        line2 = "覆盖度：无法计算（缺少研究区边界）"
    else:
        line2 = f"覆盖度：{cover:.0%}（成面阈值 ≥{MIN_COVERAGE_FOR_SURFACE:.0%}）"

    if decision == "idw":
        line3 = "结论：站数与覆盖度均达标，使用 IDW 插值成面（仅凸包内）"
    elif decision == "degrade":
        line3 = "结论：降级为点图 / 气泡图 + 城市面底色，不做插值"
    else:
        line3 = f"结论：有效站数少于 {HARD_MIN_STATIONS} 个，放弃该指标，需换指标或换区域"
    return (line1, line2, line3)


def _pick_field(layer: DataLayer, field_name: str | None) -> str:
    if field_name:
        if layer.gdf is None or field_name not in layer.gdf.columns:
            available = (
                [str(col) for col in layer.gdf.columns if pd.api.types.is_numeric_dtype(layer.gdf[col])]
                if layer.gdf is not None
                else []
            )
            raise FieldMissing(field_name, available)
        return field_name
    if layer.gdf is None:
        raise DataError(f"{layer.name} 没有几何，无法体检")
    numeric = [
        str(col)
        for col in layer.gdf.columns
        if col != layer.gdf.geometry.name
        and col not in _NON_INDICATOR_COLUMNS
        and pd.api.types.is_numeric_dtype(layer.gdf[col])
    ]
    if len(numeric) != 1:
        raise DataError(
            f"{layer.name} 有 {len(numeric)} 个数值字段，无法推断用哪个做体检；请明确指标字段"
        )
    return numeric[0]


def profile_points(
    layer: DataLayer,
    *,
    field_name: str | None = None,
    study_area: DataLayer | gpd.GeoDataFrame | None = None,
) -> DataProfile:
    """对点图层做体检并给出两档判定。

    `study_area` 缺省时无法计算覆盖度：按规则保守降级，并在理由中说明，
    不把「算不出覆盖度」当成通过。
    """
    if layer.gdf is None:
        raise DataError(f"{layer.name} 不是点图层，无法做插值体检")
    if layer.kind not in ("point",):
        raise DataError(f"{layer.name} 的图层类型是 {layer.kind}，插值体检只接受点图层")

    field = _pick_field(layer, field_name)
    values = pd.to_numeric(layer.gdf[field], errors="coerce")
    total = int(len(layer.gdf))
    valid_mask = values.notna()
    n_valid = int(valid_mask.sum())
    completeness = n_valid / total if total else 0.0

    vmin = float(values[valid_mask].min()) if n_valid else None
    vmax = float(values[valid_mask].max()) if n_valid else None
    vmean = float(values[valid_mask].mean()) if n_valid else None

    measurement_crs: str | None = None
    cover: float | None = None
    hull_km2: float | None = None
    study_km2: float | None = None

    if n_valid >= HARD_MIN_STATIONS:
        bbox = layer.bbox_wgs84()
        if bbox is not None:
            decision_crs = choose_measurement_crs(bbox)
            measurement_crs = decision_crs.crs
            area_frame = _study_area_frame(study_area)
            cover, hull_km2, study_km2 = _coverage(
                layer.gdf.loc[valid_mask], area_frame, measurement_crs
            )

    decision = _decision(n_valid, cover)
    reasons = _reason_lines(n_valid, cover, decision)

    if n_valid == 0:
        head = f"{layer.name}：{field} 全部缺测（{total} 个站点）"
    else:
        head = (
            f"{layer.name}：{field} 有效值 {n_valid} 个（共 {total} 个站点，"
            f"完整度 {completeness:.0%}），最高 {vmax:.1f}、最低 {vmin:.1f}"
        )
    summary = f"{head}。" + reasons[2].replace("结论：", "")

    return DataProfile(
        n_valid=n_valid,
        total=total,
        completeness=completeness,
        decision=decision,
        cover=cover,
        reason_lines=reasons,
        summary=summary,
        value_min=vmin,
        value_max=vmax,
        value_mean=vmean,
        measurement_crs=measurement_crs,
        hull_area_km2=hull_km2,
        study_area_km2=study_km2,
        meta={
            "field": field,
            "thresholds": {
                "min_stations_for_surface": MIN_STATIONS_FOR_SURFACE,
                "min_coverage_for_surface": MIN_COVERAGE_FOR_SURFACE,
                "hard_min_stations": HARD_MIN_STATIONS,
            },
        },
    )