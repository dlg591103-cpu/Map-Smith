"""MapSpec 模型与校验。

MapSpec 是 LLM 与渲染层之间唯一的接口（见 docs/facts/05-MapSpec与工具契约.md）。
本模块只做结构校验与已确认的硬约束；图名要素、配色语义等审查项由审图员判定
（见 docs/facts/07-制图规范与审查.md），不在这里代填或改写。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pyproj import CRS

MapType = Literal["idw", "choropleth", "point", "buffer", "overlay"]
LayerKind = Literal["admin", "idw", "choropleth", "point", "buffer", "overlay", "raster"]
ClassMethod = Literal["quantile", "jenks", "equal_interval", "custom"]

# docs/facts/07 第 8 条：禁止彩虹色。判定权仍在审图员，这里提前拒绝明显违规值。
FORBIDDEN_PALETTES = {"jet", "rainbow", "hsv", "gist_rainbow", "nipy_spectral"}

# map_type 与数据图层 kind 的对应关系：图种必须有自己的数据层。
_REQUIRED_LAYER_KIND = {
    "idw": "idw",
    "choropleth": "choropleth",
    "point": "point",
    "buffer": "buffer",
    "overlay": "overlay",
}


class Extent(BaseModel):
    """研究区范围。bbox 顺序沿用 GeoJSON 约定：[minx, miny, maxx, maxy]。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adcode: str | None = None
    bbox: tuple[float, float, float, float]

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, value: tuple[float, float, float, float]):
        minx, miny, maxx, maxy = value
        if not (minx < maxx and miny < maxy):
            raise ValueError("bbox 必须是 [minx, miny, maxx, maxy]，且每对最小值小于最大值")
        return value

    @field_validator("adcode")
    @classmethod
    def _check_adcode(cls, value: str | None):
        if value is not None and (not value.isdigit() or len(value) != 6):
            raise ValueError("adcode 必须是 6 位数字字符串")
        return value


class LayerStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fill: str | None = None
    edge: str | None = None


class Layer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    kind: LayerKind
    field: str | None = None
    source: str | None = None
    style: LayerStyle | None = None

    @model_validator(mode="after")
    def _require_field(self):
        if self.kind in {"idw", "choropleth"} and not self.field:
            raise ValueError(f"kind={self.kind} 的图层必须提供 field")
        return self


class Classification(BaseModel):
    """分级结果。breaks 为各级上界，数量等于 n；custom 的末项可为 null 表示无上界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: ClassMethod
    n: int = Field(ge=2, le=9)
    breaks: list[float | None] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_breaks(self):
        if len(self.breaks) != self.n:
            raise ValueError(f"breaks 数量必须等于 n={self.n}，实际为 {len(self.breaks)}")

        if self.method == "custom":
            if any(item is None for item in self.breaks[:-1]):
                raise ValueError("custom 的 breaks 只允许最后一项为 null，表示无上界")
        elif any(item is None for item in self.breaks):
            raise ValueError(f"method={self.method} 的 breaks 不允许 null")

        numeric = [item for item in self.breaks if item is not None]
        if any(a >= b for a, b in zip(numeric, numeric[1:])):
            raise ValueError("breaks 必须严格递增")
        return self


class Palette(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scheme: str = Field(min_length=1)
    reverse: bool = False

    @field_validator("scheme")
    @classmethod
    def _reject_rainbow(cls, value: str):
        if value.strip().lower() in FORBIDDEN_PALETTES:
            raise ValueError(f"禁止使用彩虹色阶 {value!r}（docs/facts/07 第 8 条）")
        return value


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label_field: str | None = None
    show: bool = True


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    size: tuple[float, float] = (10.0, 8.0)
    dpi: int = Field(default=300, gt=0)
    legend: bool = True
    scale_bar: bool = True
    north_arrow: bool = True
    source_note: bool = True
    crs_note: bool = True

    @field_validator("size")
    @classmethod
    def _check_size(cls, value: tuple[float, float]):
        if any(side <= 0 for side in value):
            raise ValueError("size 的宽和高必须大于 0")
        return value


class MapSpec(BaseModel):
    """制图决策产物。字段见 docs/facts/05；额外字段一律拒绝。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1)
    map_type: MapType
    extent: Extent
    layers: list[Layer] = Field(min_length=1)
    classification: Classification | None = None
    palette: Palette
    annotation: Annotation = Field(default_factory=Annotation)
    layout: Layout = Field(default_factory=Layout)
    data_source_note: str = Field(min_length=1)
    crs: str = "EPSG:4490"
    notes: list[str] = Field(default_factory=list)

    @field_validator("crs")
    @classmethod
    def _check_crs(cls, value: str):
        try:
            CRS.from_user_input(value)
        except Exception as exc:  # pyproj 抛出的异常类型较多，统一转为字段错误
            raise ValueError(f"无法识别的坐标系：{value!r}") from exc
        return value

    @model_validator(mode="after")
    def _check_layers(self):
        ids = [layer.id for layer in self.layers]
        if len(ids) != len(set(ids)):
            raise ValueError("layers 的 id 必须唯一")

        kinds = {layer.kind for layer in self.layers}
        required = _REQUIRED_LAYER_KIND[self.map_type]
        if required not in kinds:
            raise ValueError(f"map_type={self.map_type} 需要至少一个 kind={required} 的图层")
        return self

    @classmethod
    def from_json(cls, raw: str | bytes) -> "MapSpec":
        return cls.model_validate_json(raw)

    def to_json(self, *, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)