"""T13 analyze：缓冲区。

契约来源：
- docs/facts/05-MapSpec与工具契约.md 工具 3：`analyze(op, params) -> Layer`（buffer / clip / overlay / join）。
- docs/Spec/V0.1-专题制图智能体.md T13：5 km 缓冲在度量投影下成立。
- docs/facts/02-范围与边界.md「内部量算」：度量由内部自动选带（`projection.choose_measurement_crs`）。

关键点：经纬度下直接 buffer 会以「度」为单位，5 km 会被错当成 5°。必须在米制度量投影下
缓冲，再转回 WGS84；选带结果回显并记入 meta。

本任务实现 `buffer`；`clip` / `overlay` / `join` 见 T14。
"""

from __future__ import annotations

from typing import Any, Mapping

import geopandas as gpd

from ..io.models import DataError, DataLayer
from ..projection import choose_measurement_crs

WGS84 = "EPSG:4326"


def _require_gdf(layer: DataLayer) -> gpd.GeoDataFrame:
    if layer.gdf is None:
        raise DataError(f"{layer.name} 没有几何，无法做缓冲")
    if layer.gdf.empty:
        raise DataError(f"{layer.name} 为空，无法做缓冲")
    if layer.gdf.crs is None:
        raise DataError(f"{layer.name} 没有坐标系，无法做缓冲")
    return layer.gdf


def _measurement_crs_for(layer: DataLayer) -> str:
    bbox = layer.bbox_wgs84()
    if bbox is None:
        raise DataError(f"{layer.name} 无法计算范围，不能选择度量投影")
    minx, miny, maxx, maxy = bbox
    # 单点 / 单线等零跨度范围：微扩后再选带，避免 choose_measurement_crs 的最小范围校验。
    if not (minx < maxx):
        minx, maxx = minx - 1e-6, maxx + 1e-6
    if not (miny < maxy):
        miny, maxy = miny - 1e-6, maxy + 1e-6
    return choose_measurement_crs((minx, miny, maxx, maxy)).crs


def _kind_from_geometry(gdf: gpd.GeoDataFrame) -> str:
    """点（含多点）标 point，其余（面/线/混合）按面保守处理为 admin（与 uploads.py 一致）。"""
    types = {str(value) for value in gdf.geom_type if value}
    if types and types.issubset({"Point", "MultiPoint"}):
        return "point"
    return "admin"


def buffer_layer(
    layer: DataLayer,
    distance_km: float,
    *,
    quad_segs: int = 16,
) -> DataLayer:
    """在度量投影下按公里缓冲，结果转回 WGS84。

    - 度量投影由 `choose_measurement_crs(bbox)` 自动选带并回显。
    - 返回面图层（点缓冲为面），`meta` 记录缓冲距离、度量投影与总面积。
    - `quad_segs` 为每四分之一圆的线段数（shapely 2.x 参数，默认 16）。
    """
    distance = float(distance_km)
    if distance <= 0:
        raise DataError(f"缓冲距离必须为正数（公里），实际为 {distance_km}")

    gdf = _require_gdf(layer)
    measurement_crs = _measurement_crs_for(layer)

    distance_m = distance * 1000.0
    projected = gdf.to_crs(measurement_crs)
    buffered_geom = projected.geometry.buffer(distance_m, quad_segs=quad_segs)
    if bool(buffered_geom.is_empty.all()):
        raise DataError(f"{layer.name} 的缓冲结果为空，请检查图层几何")

    buffered = projected.set_geometry(buffered_geom)
    area_km2 = float(buffered.geometry.area.sum()) / 1e6

    out = buffered.to_crs(WGS84)
    kind = _kind_from_geometry(out)
    summary = (
        f"{layer.name} 缓冲 {distance:g} km：生成 {len(out)} 个缓冲面，"
        f"在度量投影 {measurement_crs} 下按米缓冲后转回 WGS84；缓冲总面积 {area_km2:.2f} km²。"
    )

    return DataLayer(
        kind=kind,  # type: ignore[arg-type]
        name=f"{layer.name}缓冲区",
        source=layer.source,
        summary=summary,
        gdf=out,
        crs=WGS84,
        meta={
            "op": "buffer",
            "buffer_km": distance,
            "measurement_crs": measurement_crs,
            "buffered_area_km2": round(area_km2, 4),
            "source_layer": layer.name,
            "feature_count": int(len(out)),
        },
    )


def analyze(
    layer: DataLayer,
    op: str,
    params: Mapping[str, Any] | None = None,
) -> DataLayer:
    """`analyze` 分发入口。当前实现 `buffer`；`clip` / `overlay` / `join` 见 T14。"""
    data = dict(params or {})
    if op == "buffer":
        if "distance_km" not in data:
            raise DataError("buffer 需要参数 distance_km（公里）")
        return buffer_layer(
            layer,
            float(data["distance_km"]),
            quad_segs=int(data.get("quad_segs", 16)),
        )
    raise DataError(f"暂不支持 op={op!r}；当前实现 buffer，clip / overlay / join 见 T14")