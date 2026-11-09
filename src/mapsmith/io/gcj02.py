"""GCJ-02 与 WGS84 互转。

背景：DataV GeoAtlas 的边界数据来源于高德开放平台，坐标系为 GCJ-02（火星坐标）；
quotsoft 站点坐标是 WGS84。两者直接叠加在城市尺度会产生约数百米的偏移。

约定：
- 本模块只做坐标换算，不改变数据来源与精度声明。
- 换算使用公开的近似算法（非官方发布），精度约 1–2 m；结果写入变换链，
  供 MapSpec 与审查报告留痕。
- 境外坐标（不在中国范围内）不做偏移，原样返回。
"""

from __future__ import annotations

import math

import geopandas as gpd
import numpy as np
import shapely

_A = 6378245.0
_EE = 0.00669342162296594323

# 中国范围粗判；超出范围时 GCJ-02 与 WGS84 视为一致。
_CHINA_LON = (73.66, 135.05)
_CHINA_LAT = (3.86, 53.55)


def out_of_china(lon: float, lat: float) -> bool:
    return not (_CHINA_LON[0] < lon < _CHINA_LON[1] and _CHINA_LAT[0] < lat < _CHINA_LAT[1])


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    """WGS84 → GCJ-02。输入输出均为 (lon, lat)。"""
    if out_of_china(lon, lat):
        return (lon, lat)

    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrtmagic * math.cos(radlat) * math.pi)

    return (lon + dlon, lat + dlat)


def gcj02_to_wgs84(
    lon: float, lat: float, *, iterations: int = 30, tolerance: float = 1e-9
) -> tuple[float, float]:
    """GCJ-02 → WGS84。

    GCJ-02 没有公开的解析逆函数，这里用迭代逼近：以 GCJ-02 作为初值，
    反复用正向公式校正，直到残差小于 `tolerance` 度（约 0.1 mm）。
    """
    if out_of_china(lon, lat):
        return (lon, lat)

    wgs_lon, wgs_lat = lon, lat
    for _ in range(iterations):
        gcj_lon, gcj_lat = wgs84_to_gcj02(wgs_lon, wgs_lat)
        dlon = gcj_lon - lon
        dlat = gcj_lat - lat
        if abs(dlon) < tolerance and abs(dlat) < tolerance:
            break
        wgs_lon -= dlon
        wgs_lat -= dlat

    return (wgs_lon, wgs_lat)


def transform_geodataframe(
    gdf: gpd.GeoDataFrame,
    *,
    direction: str = "gcj02_to_wgs84",
) -> tuple[gpd.GeoDataFrame, dict[str, object]]:
    """按点逐坐标换算整幅矢量数据，不改动 CRS 字段。

    返回新的 GeoDataFrame 与一条变换记录；原对象不变，便于回滚与对比。
    """
    if direction not in ("gcj02_to_wgs84", "wgs84_to_gcj02"):
        raise ValueError(f"不支持的换算方向：{direction}")
    if gdf.crs is None:
        raise ValueError("数据没有坐标系，不能做 GCJ-02 换算")

    converter = gcj02_to_wgs84 if direction == "gcj02_to_wgs84" else wgs84_to_gcj02

    def _shift(coords: "np.ndarray") -> "np.ndarray":
        return np.array([converter(float(x), float(y)) for x, y in coords])

    def _shift_geometry(geom):
        if geom is None or geom.is_empty:
            return geom
        return shapely.transform(geom, _shift)

    converted = gdf.copy()
    converted["geometry"] = converted.geometry.apply(_shift_geometry)
    record: dict[str, object] = {
        "direction": direction,
        "algorithm": "公开近似算法（非官方发布）",
        "accuracy": "约 1–2 m",
        "feature_count": int(len(converted)),
        "crs_unchanged": converted.crs.to_string() if converted.crs else None,
    }
    return converted, record