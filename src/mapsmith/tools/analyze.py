"""T13–T14 analyze：缓冲区、裁剪、叠加、属性关联。

契约来源：
- docs/facts/05-MapSpec与工具契约.md 工具 3：`analyze(op, params) -> Layer`（buffer / clip / overlay / join）。
- docs/Spec/V0.1-专题制图智能体.md T13：5 km 缓冲在度量投影下成立；T14：裁剪与叠加结果可渲染。
- docs/facts/02-范围与边界.md「内部量算」：度量由内部自动选带（`projection.choose_measurement_crs`）。

关键点：经纬度下直接 buffer 会以「度」为单位，5 km 会被错当成 5°。必须在米制度量投影下
缓冲，再转回 WGS84；选带结果回显并记入 meta。

op 一览：
- `buffer`：度量投影下按公里缓冲（T13）。
- `clip`：用边界面裁剪目标图层（T14）。`params["by"]` 传边界 DataLayer。
- `overlay`：两图层空间叠加（T14）。`params["other"]` 传另一 DataLayer，`params["how"]` 给叠加方式。
- `join`：把统计表（无几何，但必须携带数据行）按 key 关联到边界，产出带统计值的面图层（T14）。
  `params["to"]` 传边界 DataLayer，`params["key"]` 传关联键。

第二图层统一通过 params 传 DataLayer 对象，`analyze(layer, op, params)` 的第一参数始终是被操作图层。

契约前提（重要）：`join` 的统计表必须「携带真实数据行」。当前 `io/uploads.py` 解析无坐标 CSV
时返回的 `kind="table"` 图层 `gdf=None`，数据行未保存——这是已确认的契约缺口，待数据管家补上
（见 docs/自检/T14 契约缺口报告）。本实现按正确契约读取 `table.gdf`，缺数据时明确报错而不静默。
"""

from __future__ import annotations

from typing import Any, Mapping

import geopandas as gpd

from ..io.models import DataError, DataLayer
from ..projection import choose_measurement_crs

WGS84 = "EPSG:4326"

_OVERLAY_HOW = ("intersection", "union", "difference", "symmetric_difference", "identity")


def _require_gdf(layer: DataLayer) -> gpd.GeoDataFrame:
    if layer.gdf is None:
        raise DataError(f"{layer.name} 没有几何，无法做缓冲")
    if layer.gdf.empty:
        raise DataError(f"{layer.name} 为空，无法做缓冲")
    if layer.gdf.crs is None:
        raise DataError(f"{layer.name} 没有坐标系，无法做缓冲")
    return layer.gdf


def _require_geometry(layer: DataLayer, action: str) -> gpd.GeoDataFrame:
    if layer.gdf is None:
        raise DataError(f"{layer.name} 没有几何，无法{action}")
    if layer.gdf.empty:
        raise DataError(f"{layer.name} 为空，无法{action}")
    if layer.gdf.crs is None:
        raise DataError(f"{layer.name} 没有坐标系，无法{action}")
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


def _to_wgs84(gdf: gpd.GeoDataFrame, name: str) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        raise DataError(f"{name} 没有坐标系，无法对齐到 WGS84")
    if gdf.crs.to_epsg() == 4326:
        return gdf
    return gdf.to_crs(WGS84)


def _as_layer(value: Any, param: str) -> DataLayer:
    if not isinstance(value, DataLayer):
        raise DataError(f"{param} 必须是 DataLayer，实际为 {type(value).__name__}")
    return value


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


def clip_layer(layer: DataLayer, by: DataLayer) -> DataLayer:
    """用边界图层裁剪目标图层，返回落在边界内的部分。

    - `layer` 是被裁剪对象（点/线/面），`by` 是裁剪边界（面）。
    - 两图层统一转 WGS84 后做拓扑裁剪，结果即 WGS84，可渲染。
    """
    target = _require_geometry(layer, "裁剪")
    boundary = _require_geometry(by, "作为裁剪边界")

    target_wgs = _to_wgs84(target, layer.name)
    boundary_wgs = _to_wgs84(boundary, by.name)

    clipped = gpd.clip(target_wgs, boundary_wgs)
    if clipped.empty:
        raise DataError(f"{layer.name} 裁剪后为空：与 {by.name} 无交集")

    kind = _kind_from_geometry(clipped)
    summary = (
        f"{layer.name} 按 {by.name} 裁剪：保留 {len(clipped)} 个要素，"
        f"几何 {'、'.join(sorted({str(g) for g in clipped.geom_type if g}))}，坐标系 WGS84。"
    )
    return DataLayer(
        kind=kind,  # type: ignore[arg-type]
        name=f"{layer.name}裁剪",
        source=layer.source,
        summary=summary,
        gdf=clipped,
        crs=WGS84,
        meta={
            "op": "clip",
            "clip_layer": by.name,
            "source_layer": layer.name,
            "feature_count": int(len(clipped)),
        },
    )


def overlay_layer(layer: DataLayer, other: DataLayer, how: str = "intersection") -> DataLayer:
    """两图层空间叠加。

    - `how` 支持 intersection / union / difference / symmetric_difference / identity。
    - 统一转 WGS84 后叠加，结果可渲染。
    """
    if how not in _OVERLAY_HOW:
        raise DataError(f"不支持的叠加方式 {how!r}；可用：{'、'.join(_OVERLAY_HOW)}")

    left = _require_geometry(layer, "叠加")
    right = _require_geometry(other, "叠加")

    left_wgs = _to_wgs84(left, layer.name)
    right_wgs = _to_wgs84(right, other.name)

    result = left_wgs.overlay(right_wgs, how=how)
    if result.empty:
        raise DataError(f"{layer.name} 与 {other.name} 按 {how} 叠加结果为空")

    kind = _kind_from_geometry(result)
    summary = (
        f"{layer.name} 与 {other.name} 按 {how} 叠加：得到 {len(result)} 个要素，"
        f"几何 {'、'.join(sorted({str(g) for g in result.geom_type if g}))}，坐标系 WGS84。"
    )
    return DataLayer(
        kind=kind,  # type: ignore[arg-type]
        name=f"{layer.name}叠加",
        source=layer.source,
        summary=summary,
        gdf=result,
        crs=WGS84,
        meta={
            "op": "overlay",
            "how": how,
            "other_layer": other.name,
            "source_layer": layer.name,
            "feature_count": int(len(result)),
        },
    )


def _parse_join_key(key: Any) -> tuple[str, str]:
    """join 关联键：字符串表示两边同名列；(表键, 边界键) 二元组表示不同名列。"""
    if isinstance(key, str):
        return key, key
    if isinstance(key, (list, tuple)) and len(key) == 2:
        return str(key[0]), str(key[1])
    raise DataError(f"join 的 key 应为字符串或 (表键, 边界键) 二元组，实际为 {key!r}")


def _stats_columns(stats: gpd.GeoDataFrame, table_key: str) -> list[str]:
    """统计表里除关联键与几何列外的列，作为待关联的统计字段。"""
    geom_name: str | None = None
    geometry = getattr(stats, "geometry", None)
    if geometry is not None and getattr(geometry, "name", None) is not None:
        geom_name = geometry.name
    return [str(col) for col in stats.columns if str(col) != table_key and str(col) != geom_name]


def join_table(table: DataLayer, to: DataLayer, key: Any) -> DataLayer:
    """把统计表按 key 关联到边界，产出带统计值的面图层。

    - 第一参数 `table` 是无几何统计表，数据行必须保存在 `gdf` 里（正确契约前提）。
    - `to` 是带几何的边界图层；结果保留边界几何与统计字段，供分级设色渲染。
    """
    if table.gdf is None:
        raise DataError(
            f"{table.name} 没有携带数据行，无法关联；"
            "契约缺口：table 图层应把统计表数据保存在 gdf 中（待数据管家补上）"
        )

    boundary = _require_geometry(to, "作为关联边界")
    table_key, boundary_key = _parse_join_key(key)

    stats = table.gdf
    if table_key not in stats.columns:
        raise DataError(
            f"{table.name} 缺少关联键列 {table_key!r}；可用列：{list(map(str, stats.columns))}"
        )
    if boundary_key not in boundary.columns:
        raise DataError(
            f"{to.name} 缺少关联键列 {boundary_key!r}；可用列：{list(map(str, boundary.columns))}"
        )

    value_columns = _stats_columns(stats, table_key)
    if not value_columns:
        raise DataError(f"{table.name} 除关联键 {table_key!r} 外没有可关联的统计字段")

    boundary_wgs = _to_wgs84(boundary, to.name)
    right = stats[[table_key, *value_columns]]

    merged = boundary_wgs.merge(
        right,
        left_on=boundary_key,
        right_on=table_key,
        how="left",
        suffixes=("", "_表"),
    )

    # 以第一个统计字段是否为空判断「该边界是否匹配到统计值」。
    matched = int(merged[value_columns[0]].notna().sum())
    total = int(len(merged))
    unmatched = total - matched

    summary = (
        f"{table.name} 按 {table_key}↔{boundary_key} 关联到 {to.name}："
        f"共 {total} 个边界要素，匹配到统计值 {matched} 个"
        + (f"，未匹配 {unmatched} 个" if unmatched else "")
        + f"；统计字段 {'、'.join(value_columns)}；坐标系 WGS84。"
    )
    return DataLayer(
        kind="admin",
        name=f"{table.name}关联结果",
        source=table.source,
        summary=summary,
        gdf=merged,
        crs=WGS84,
        meta={
            "op": "join",
            "table_key": table_key,
            "boundary_key": boundary_key,
            "to_layer": to.name,
            "value_fields": value_columns,
            "feature_count": total,
            "matched_count": matched,
            "unmatched_count": unmatched,
        },
    )


def analyze(
    layer: DataLayer,
    op: str,
    params: Mapping[str, Any] | None = None,
) -> DataLayer:
    """`analyze` 分发入口：buffer / clip / overlay / join。"""
    data = dict(params or {})

    if op == "buffer":
        if "distance_km" not in data:
            raise DataError("buffer 需要参数 distance_km（公里）")
        return buffer_layer(
            layer,
            float(data["distance_km"]),
            quad_segs=int(data.get("quad_segs", 16)),
        )

    if op == "clip":
        if "by" not in data:
            raise DataError("clip 需要参数 by（裁剪边界 DataLayer）")
        return clip_layer(layer, _as_layer(data["by"], "by"))

    if op == "overlay":
        if "other" not in data:
            raise DataError("overlay 需要参数 other（叠加对象 DataLayer）")
        return overlay_layer(layer, _as_layer(data["other"], "other"), how=str(data.get("how", "intersection")))

    if op == "join":
        if "to" not in data:
            raise DataError("join 需要参数 to（关联边界 DataLayer）")
        if "key" not in data:
            raise DataError("join 需要参数 key（关联键）")
        return join_table(layer, _as_layer(data["to"], "to"), data["key"])

    raise DataError(f"暂不支持 op={op!r}；可用：buffer / clip / overlay / join")