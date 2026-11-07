"""投影选择、输出白名单与变换链记录。

规则来源：docs/facts/02-范围与边界.md 的「投影边界」一节。
- 输出限白名单：CGCS2000 地理、CGCS2000 3°GK、WGS84 UTM、Web Mercator；默认 CGCS2000。
- 内部量算：单带范围用 CGCS2000 3°GK 自动选带；跨带或省域以上用 CGCS2000 Albers。
- Web Mercator 仅用于显示，禁止量算。
- 选带结果必须回显且可覆盖，涉及基准转换或非默认输出须记入变换链。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from pyproj import CRS, Transformer

EPSG_CGCS2000_GEOGRAPHIC = "EPSG:4490"
EPSG_WEB_MERCATOR = "EPSG:3857"

CGCS2000_ALBERS_PROJ = (
    "+proj=aea +lat_1=25 +lat_2=47 +lat_0=0 +lon_0=105 "
    "+x_0=0 +y_0=0 +ellps=GRS80 +units=m +no_defs"
)

# CGCS2000 3° 高斯-克吕格
GK_ZONE_MIN, GK_ZONE_MAX = 25, 45
GK_CM_MIN, GK_CM_MAX = 75, 135
GK_ZONE_EPSG_MIN = 4513  # zone 25
GK_CM_EPSG_MIN = 4534  # CM 75E

# WGS84 UTM
UTM_NORTH_MIN, UTM_NORTH_MAX = 32601, 32660
UTM_SOUTH_MIN, UTM_SOUTH_MAX = 32701, 32760


def _gk_zone(lon: float) -> int:
    """取 3° 带号；边界值（如 115.5°E）向上归入较高带。"""
    return int(math.floor(lon / 3.0 + 0.5))


def _validate_lon(lon: float) -> float:
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"经度超出范围：{lon}")
    return lon


@dataclass(frozen=True)
class GkBand:
    """一条 CGCS2000 3° 高斯-克吕格投影带。"""

    epsg: str
    zone: int
    central_meridian: int
    with_zone_prefix: bool
    false_easting: float

    def describe(self) -> str:
        prefix = "带号前缀" if self.with_zone_prefix else "无带号前缀"
        return (
            f"CGCS2000 3° 高斯-克吕格：中央经线 {self.central_meridian}°E，"
            f"带号 {self.zone}，{prefix}，假东 {self.false_easting:.0f} m（{self.epsg}）"
        )


def select_gk_band(lon: float, *, with_zone_prefix: bool = False) -> GkBand:
    """按经度自动选带；`with_zone_prefix` 决定用带号版还是无带号版。"""
    _validate_lon(lon)
    zone = _gk_zone(lon)
    central_meridian = zone * 3
    if not GK_CM_MIN <= central_meridian <= GK_CM_MAX:
        raise ValueError(
            f"经度 {lon}°E 超出 CGCS2000 3° 带覆盖范围（CM {GK_CM_MIN}–{GK_CM_MAX}°E）"
        )

    if with_zone_prefix:
        epsg_code = GK_ZONE_EPSG_MIN + (zone - GK_ZONE_MIN)
        false_easting = zone * 1_000_000 + 500_000
    else:
        epsg_code = GK_CM_EPSG_MIN + (central_meridian - GK_CM_MIN) // 3
        false_easting = 500_000.0

    return GkBand(
        epsg=f"EPSG:{epsg_code}",
        zone=zone,
        central_meridian=central_meridian,
        with_zone_prefix=with_zone_prefix,
        false_easting=false_easting,
    )


def gk_band_from_epsg(crs: str) -> GkBand:
    """用户覆盖选带结果时使用；非 3°GK 编码直接拒绝。"""
    parsed = CRS.from_user_input(crs)
    code = parsed.to_epsg()
    if code is None:
        raise ValueError(f"无法识别为 EPSG 编码：{crs!r}")

    if GK_ZONE_EPSG_MIN <= code <= GK_ZONE_EPSG_MIN + (GK_ZONE_MAX - GK_ZONE_MIN):
        zone = GK_ZONE_MIN + (code - GK_ZONE_EPSG_MIN)
        return GkBand(
            epsg=f"EPSG:{code}",
            zone=zone,
            central_meridian=zone * 3,
            with_zone_prefix=True,
            false_easting=zone * 1_000_000 + 500_000,
        )

    if GK_CM_EPSG_MIN <= code <= GK_CM_EPSG_MIN + (GK_CM_MAX - GK_CM_MIN) // 3:
        central_meridian = GK_CM_MIN + (code - GK_CM_EPSG_MIN) * 3
        return GkBand(
            epsg=f"EPSG:{code}",
            zone=central_meridian // 3,
            central_meridian=central_meridian,
            with_zone_prefix=False,
            false_easting=500_000.0,
        )

    raise ValueError(f"{crs!r} 不是 CGCS2000 3° 高斯-克吕格投影")


def is_output_allowed(crs: str) -> bool:
    """输出白名单：CGCS2000 地理、3°GK（带号/无带号）、WGS84 UTM、Web Mercator。"""
    parsed = CRS.from_user_input(crs)
    code = parsed.to_epsg()
    if code is None:
        return False
    if code in (4490, 3857):
        return True
    if GK_ZONE_EPSG_MIN <= code <= GK_ZONE_EPSG_MIN + (GK_ZONE_MAX - GK_ZONE_MIN):
        return True
    if GK_CM_EPSG_MIN <= code <= GK_CM_EPSG_MIN + (GK_CM_MAX - GK_CM_MIN) // 3:
        return True
    if UTM_NORTH_MIN <= code <= UTM_NORTH_MAX:
        return True
    if UTM_SOUTH_MIN <= code <= UTM_SOUTH_MAX:
        return True
    return False


def require_output_allowed(crs: str) -> str:
    if not is_output_allowed(crs):
        raise ValueError(
            f"{crs!r} 不在输出白名单内；允许 CGCS2000 地理（EPSG:4490）、"
            "CGCS2000 3°GK、WGS84 UTM、Web Mercator（EPSG:3857）"
        )
    return crs


def select_utm_band(lon: float, *, northern: bool) -> str:
    _validate_lon(lon)
    zone = int(math.floor((lon + 180.0) / 6.0)) + 1
    zone = min(max(zone, 1), 60)
    base = 32600 if northern else 32700
    return f"EPSG:{base + zone}"


@dataclass(frozen=True)
class ProjectionDecision:
    """一次投影选择的结果，供界面回显与元数据记录。"""

    kind: Literal["gk", "albers", "utm", "geographic", "web_mercator"]
    crs: str
    zone: int | None = None
    central_meridian: int | None = None
    with_zone_prefix: bool | None = None
    false_easting: float | None = None
    reason: str = ""

    def describe(self) -> str:
        if self.kind == "gk":
            prefix = "带号前缀" if self.with_zone_prefix else "无带号前缀"
            return (
                f"按图幅中心经度选择 CGCS2000 3° 高斯-克吕格投影："
                f"中央经线 {self.central_meridian}°E，带号 {self.zone}，"
                f"{prefix}，假东 {self.false_easting:.0f} m（{self.crs}）。{self.reason}"
            )
        if self.kind == "albers":
            return (
                "研究区跨越 3° 带或属省域以上范围，量算使用 CGCS2000 Albers"
                f"（中央经线 105°E，标准纬线 25°N / 47°N）。{self.reason}"
            )
        return f"{self.crs}。{self.reason}"


def choose_measurement_crs(
    bbox: tuple[float, float, float, float],
    *,
    with_zone_prefix: bool = False,
) -> ProjectionDecision:
    """量算投影：单带内用 3°GK 选带，跨带或省域以上用 Albers。"""
    minx, miny, maxx, maxy = bbox
    if not (minx < maxx and miny < maxy):
        raise ValueError("bbox 必须是 [minx, miny, maxx, maxy]，且 min < max")

    center_lon = (minx + maxx) / 2.0
    # 单带判定：图幅经度跨度不超过一个 3° 带宽。徐州示例 116.2–118.6 跨度为 2.4°，
    # 虽略超出 CM 117 带的 115.5–118.5，仍按单带处理，取中心经度选带（EPSG:4548）。
    same_band = (maxx - minx) <= 3.0

    if same_band:
        band = select_gk_band(center_lon, with_zone_prefix=with_zone_prefix)
        return ProjectionDecision(
            kind="gk",
            crs=band.epsg,
            zone=band.zone,
            central_meridian=band.central_meridian,
            with_zone_prefix=band.with_zone_prefix,
            false_easting=band.false_easting,
            reason=f"图幅经度跨度 {maxx - minx:.2f}° 不超过一个 3° 带，按中心经度选带。",
        )

    return ProjectionDecision(
        kind="albers",
        crs=CGCS2000_ALBERS_PROJ,
        reason=f"经度范围 {minx:.2f}–{maxx:.2f}°E 跨带，改用等积 Albers。",
    )


def ensure_measure_allowed(crs: str) -> None:
    """Web Mercator 仅用于显示，禁止量算。"""
    if CRS.from_user_input(crs).to_epsg() == 3857:
        raise ValueError("Web Mercator 仅用于显示，禁止用于量算")


def resolve_output_crs(requested: str | None) -> str:
    """输出坐标系：未指定时用默认 CGCS2000，指定时必须落在白名单内。"""
    if requested is None or not str(requested).strip():
        return EPSG_CGCS2000_GEOGRAPHIC
    return require_output_allowed(str(requested))


@dataclass(frozen=True)
class TransformStep:
    source: str
    target: str
    operation: str
    datum_change: bool
    params: dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        base = f"{self.source} → {self.target}：{self.operation}"
        if self.datum_change:
            base += "（含基准转换）"
        return base


@dataclass
class TransformChain:
    """元数据变换链；凡涉及基准转换或非默认输出都要记录。"""

    steps: list[TransformStep] = field(default_factory=list)

    def add(self, step: TransformStep) -> "TransformChain":
        self.steps.append(step)
        return self

    def describe(self) -> str:
        if not self.steps:
            return "未发生坐标变换。"
        return "；".join(step.describe() for step in self.steps)

    def to_dict(self) -> list[dict[str, object]]:
        return [
            {
                "source": step.source,
                "target": step.target,
                "operation": step.operation,
                "datum_change": step.datum_change,
                "params": dict(step.params),
            }
            for step in self.steps
        ]


def plan_transform(source_crs: str, target_crs: str) -> TransformStep:
    """记录一次 CRS 变换；不执行坐标计算。"""
    source = CRS.from_user_input(source_crs)
    target = CRS.from_user_input(target_crs)
    transformer = Transformer.from_crs(source, target, always_xy=True)

    def label(crs: CRS) -> str:
        code = crs.to_epsg()
        return f"{crs.name} ({'EPSG:' + str(code) if code else 'custom'})"

    source_datum = source.geodetic_crs.datum.name if source.geodetic_crs else None
    target_datum = target.geodetic_crs.datum.name if target.geodetic_crs else None

    return TransformStep(
        source=label(source),
        target=label(target),
        operation=transformer.description or "PROJ pipeline",
        datum_change=source_datum != target_datum,
        params={"always_xy": "true"},
    )