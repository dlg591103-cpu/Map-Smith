"""T22 界面的纯函数层：无前端依赖，可单测。

职责：
- `build_spec`：把表单值组装成合法 MapSpec；非法组合抛带中文说明的 `DataError`。
- `compute_breaks`：按分级方法与级数计算断点（复用 `tools.classify`）。
- `resolve_inputs`：从 demo_data 载入行政边界与站点空气数据。
- `aggregate_points_to_admin`：把站点值按空间归属聚合到边界面（供 choropleth）。
- `run_render`：分派渲染并落盘 PNG + PDF。

界面在 `web/`（Vue 3 + Vite）；这里只放可单测的计算与渲染分派。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
from pydantic import ValidationError

from .io.models import DataError, DataLayer
from .render import render
from .spec import (
    Annotation,
    Classification,
    Extent,
    Layer,
    MapSpec,
    Palette,
)
from .tools.classify import classify
from .tools.load_layer import load_admin, load_air

# 本段界面支持的图种；buffer / overlay 不在本段范围内（SPEC 契约缺口，待决策）。
SUPPORTED_MAP_TYPES = ("choropleth", "point", "idw")

# 分级方法白名单，与 spec.Classification.method 一致。
SUPPORTED_METHODS = ("quantile", "jenks", "equal_interval", "custom")


@dataclass
class RenderResult:
    """一次渲染的落盘结果，供界面回显与下载。"""

    png_path: Path | None = None
    pdf_path: Path | None = None
    report: Any = None


def build_spec(fields: dict[str, Any]) -> MapSpec:
    """把表单字段组装成合法 `MapSpec`；非法组合抛带中文说明的 `DataError`。

    必填字段：`title`、`map_type`、`adcode`、`bbox`、`field`、`method`、`n`、
    `breaks`、`palette_scheme`、`data_source_note`。`crs` 缺省 EPSG:4490。

    关键校验（在 pydantic 之前先做，保证错误信息面向用户）：
    - `map_type` 只允许 choropleth / point / idw；buffer / overlay 抛 DataError。
    - `breaks` 数量必须等于 `n`，不匹配抛 DataError。
    """
    title = fields.get("title")
    if not title or not str(title).strip():
        raise DataError("图名不能为空：请填写「区域 + 指标 + 时间」的图名")

    map_type = fields.get("map_type")
    if map_type not in SUPPORTED_MAP_TYPES:
        raise DataError(
            f"图种 {map_type!r} 不受支持；本段仅支持 {'、'.join(SUPPORTED_MAP_TYPES)}"
            "（buffer / overlay 尚未实现，待 SPEC 决策）"
        )

    field_name = fields.get("field")
    if not field_name:
        raise DataError("指标字段不能为空")

    method = fields.get("method")
    if method not in SUPPORTED_METHODS:
        raise DataError(
            f"分级方法 {method!r} 不受支持；可用：{'、'.join(SUPPORTED_METHODS)}"
        )

    n = fields.get("n")
    try:
        n = int(n)
    except (TypeError, ValueError) as exc:
        raise DataError(f"级数 n 必须是整数，实际为 {n!r}") from exc

    breaks = fields.get("breaks")
    if breaks is None:
        raise DataError("缺少分级断点 breaks：请先按数据计算断点")
    breaks = list(breaks)
    if len(breaks) != n:
        raise DataError(
            f"分级断点数量 {len(breaks)} 与级数 {n} 不匹配："
            f"分级数 n 必须等于断点数量"
        )

    bbox = fields.get("bbox")
    if bbox is None:
        raise DataError("缺少研究区范围 bbox")

    data_source_note = fields.get("data_source_note")
    if not data_source_note or not str(data_source_note).strip():
        raise DataError("数据来源注记不能为空（制图规范第 5 条：数据来源 + 更新时间）")

    try:
        return MapSpec(
            title=str(title),
            map_type=map_type,  # type: ignore[arg-type]
            extent=Extent(
                adcode=str(fields.get("adcode")) if fields.get("adcode") else None,
                bbox=tuple(float(value) for value in bbox),  # type: ignore[arg-type]
            ),
            layers=[
                Layer(
                    id="data",
                    kind=map_type,  # type: ignore[arg-type]
                    field=str(field_name),
                    source=str(data_source_note),
                )
            ],
            classification=Classification(
                method=method,  # type: ignore[arg-type]
                n=n,
                breaks=breaks,
            ),
            palette=Palette(
                scheme=str(fields.get("palette_scheme", "YlOrRd")),
                reverse=bool(fields.get("palette_reverse", False)),
            ),
            annotation=Annotation(
                label_field=fields.get("label_field"),
                show=bool(fields.get("show_label", False)),
            ),
            data_source_note=str(data_source_note),
            crs=str(fields.get("crs", "EPSG:4490")),
            notes=[str(item) for item in fields.get("notes", [])],
        )
    except ValidationError as exc:
        # pydantic 的校验信息是英文且技术性强，这里转成面向用户的中文说明。
        detail = "；".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise DataError(f"制图参数不合法：{detail}") from exc


def compute_breaks(
    values: list[Any],
    method: str,
    n: int,
    *,
    custom_breaks: list[float | None] | None = None,
) -> list[float | None]:
    """按分级方法与级数计算断点；返回与 `n` 等长的断点列表。"""
    result = classify(values, method, n, custom_breaks=custom_breaks)  # type: ignore[arg-type]
    return list(result.breaks)


def resolve_inputs(
    place: str,
    date: str,
    field: str,
    *,
    online: bool = False,
) -> tuple[DataLayer, DataLayer]:
    """从 demo_data 载入行政边界与站点空气数据，返回 ``(admin_layer, point_layer)``。"""
    admin = load_admin(place, online=online)
    point = load_air(place, date, field=field, online=online)
    return admin, point


def aggregate_points_to_admin(
    admin: gpd.GeoDataFrame,
    points: gpd.GeoDataFrame,
    field: str,
) -> gpd.GeoDataFrame:
    """把站点值按空间归属聚合到边界面（取均值），供 choropleth 设色。

    - 两图层 CRS 不一致时先把站点转成边界坐标系。
    - 无站点落入的边界面，聚合值为 NaN（渲染层按缺失处理）。
    """
    if admin.crs is None or points.crs is None:
        raise DataError("图层缺少坐标系，无法做空间聚合")
    if field not in points.columns:
        raise DataError(f"站点图层没有字段 {field!r}，现有字段：{list(points.columns)}")
    if admin.crs != points.crs:
        points = points.to_crs(admin.crs)

    valid = points.dropna(subset=[field])
    if valid.empty:
        raise DataError(f"字段 {field!r} 没有有效值，无法聚合到面")

    # 给边界加临时序号列，按序号分组求均值，避免依赖 sjoin 的内部索引列名。
    tmp = admin.copy()
    tmp["_admin_id"] = np.arange(len(tmp))
    joined = gpd.sjoin(valid, tmp, how="left", predicate="within")
    grouped = joined.groupby("_admin_id")[field].mean()

    result = admin.copy()
    result[field] = grouped.reindex(np.arange(len(admin)))
    return result


def run_render(
    spec: MapSpec,
    layer: Any,
    out_dir: str | Path,
    *,
    name: str = "map",
) -> RenderResult:
    """按 `spec.map_type` 分派渲染，把 PNG 与 PDF 落盘到 `out_dir`，返回路径与报告。

    `layer` 可以是 `DataLayer`（取 `.gdf`）或直接 GeoDataFrame。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    png_path = out / f"{name}.png"
    pdf_path = out / f"{name}.pdf"

    gdf = layer.gdf if isinstance(layer, DataLayer) else layer
    if gdf is None:
        raise DataError("图层没有几何数据，无法渲染")

    report = render(spec, gdf, out_path=png_path, pdf_path=pdf_path)
    return RenderResult(png_path=png_path, pdf_path=pdf_path, report=report)