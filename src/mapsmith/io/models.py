"""数据层模型与数据侧异常。

数据侧对外的统一产物是 `DataLayer`：GeoDataFrame + 自然语言 `summary`。
Agent 读不懂 GeoDataFrame，`summary` 是回灌 LLM 的唯一通道
（见 docs/facts/05-MapSpec与工具契约.md「返回契约」）。

本模块只定义结构与异常，不含任何加载逻辑；加载分别见
`io/uploads.py`、`io/raster.py`、`tools/load_layer.py`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import geopandas as gpd

# 数据层图种：与 docs/facts/05 的 Layer.kind 保持同名，便于直接对照。
LayerKind = Literal["admin", "point", "raster", "table"]

# 上传文件的坐标系来源。`missing` 表示文件未声明，必须由用户确认后才能继续
# （docs/facts/02-范围与边界.md：不静默默认 WGS84）。
CrsStatus = Literal["declared", "missing"]


class DataError(Exception):
    """数据侧可预期的错误基类；消息直接面向用户。"""


class PlaceNotFound(DataError):
    """地名未收录或无法解析，调用方必须反问用户，不得猜一个默认值。"""


class AmbiguousPlace(DataError):
    """地名对应多个候选，调用方必须让用户选择。"""

    def __init__(self, name: str, candidates: list[dict[str, str]]) -> None:
        super().__init__(f"地名「{name}」有 {len(candidates)} 个候选，需要用户确认")
        self.name = name
        self.candidates = candidates


class FieldMissing(DataError):
    """请求的指标字段不在数据里，调用方应换指标并明确告知用户。"""

    def __init__(self, field_name: str, available: list[str]) -> None:
        shown = "、".join(available) if available else "（无可用数值字段）"
        super().__init__(f"字段「{field_name}」不存在；可用字段：{shown}")
        self.field_name = field_name
        self.available = available


class CrsNotDeclared(DataError):
    """上传文件未声明坐标系。携带已解析的数据，确认 CRS 后可继续。

    按 docs/facts/02，缺 CRS 时必须弹窗要求用户确认，不允许静默按 WGS84 处理。
    `suggested_crs` 只是给用户的默认选项，必须显式确认后才生效。
    """

    def __init__(self, file_name: str, suggested_crs: str | None = None) -> None:
        message = f"文件「{file_name}」未声明坐标系，需要用户确认后才能继续"
        if suggested_crs:
            message += f"（可选建议值 {suggested_crs}，未确认不生效）"
        super().__init__(message)
        self.file_name = file_name
        self.suggested_crs = suggested_crs


@dataclass
class DataLayer:
    """一次加载的结果。

    - `gdf`：地理数据；`kind="table"` 时为 None（统计表不带几何）。
    - `source`：数据来源的简短标识，用于 MapSpec 的 data_source_note。
    - `meta`：补充信息（时间、CRS 来源、字段映射、待确认项等），可序列化为 JSON。
    """

    kind: LayerKind
    name: str
    source: str
    summary: str
    gdf: gpd.GeoDataFrame | None = None
    crs: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def count(self) -> int:
        if self.gdf is None:
            return 0
        return int(len(self.gdf))

    def bbox_wgs84(self) -> tuple[float, float, float, float] | None:
        """返回 [minx, miny, maxx, maxy] 的经纬度范围；无几何时返回 None。"""
        if self.gdf is None or self.gdf.empty:
            return None
        gdf = self.gdf
        if gdf.crs is None:
            raise DataError("数据没有坐标系，无法计算范围")
        if gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
        minx, miny, maxx, maxy = gdf.total_bounds
        return (float(minx), float(miny), float(maxx), float(maxy))