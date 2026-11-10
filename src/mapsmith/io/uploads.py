"""上传文件解析：CSV / GeoJSON / Shapefile(zip)。

规则来源：
- 格式与 CRS 规则：docs/facts/02-范围与边界.md「输入数据格式」。
- 缺 CRS 必须由用户确认，不静默默认 WGS84；本模块只在 `meta["crs_status"]`
  里标记 `missing`，并在 `summary` 中提示，是否继续由调用方决定。

对外只保留一个入口 `parse_upload`，按扩展名分派；所有分支返回 `DataLayer`，
保证 Agent 拿到的是同一种结构与同一种 summary 口径。
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from typing import Literal

import geopandas as gpd
import pandas as pd

from .models import CrsNotDeclared, DataError, DataLayer

# 字段别名：按小写、去空格比较。顺序靠前的优先。
LON_ALIASES = ("经度", "东经", "longitude", "lon", "lng", "long", "x")
LAT_ALIASES = ("纬度", "北纬", "latitude", "lat", "y")
NAME_ALIASES = ("站点名", "站点名称", "监测点名称", "名称", "站名", "station_name", "name")
CODE_ALIASES = ("监测点编码", "编码", "站点编码", "station_code", "code", "id")
CITY_ALIASES = ("城市", "所属城市", "地市", "city")

SHP_REQUIRED = (".shp", ".shx", ".dbf")


def _normalize_key(text: str) -> str:
    return str(text).strip().lower().replace(" ", "").replace("_", "")


def _pick_column(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    normalized = {_normalize_key(col): col for col in columns}
    for alias in aliases:
        hit = normalized.get(_normalize_key(alias))
        if hit is not None:
            return hit
    return None


def _read_csv_text(path: Path) -> tuple[pd.DataFrame, str]:
    """按 UTF-8 → GBK 顺序尝试；返回实际使用的编码，便于在 summary 中留痕。"""
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding), encoding
        except UnicodeDecodeError as exc:  # 换下一个编码
            last_error = exc
    raise DataError(f"CSV 编码无法识别（已尝试 UTF-8/GBK）：{last_error}")


def _csv_to_layer(path: Path, name: str, crs: str | None) -> DataLayer:
    df, encoding = _read_csv_text(path)
    columns = [str(col) for col in df.columns]
    lon_col = _pick_column(columns, LON_ALIASES)
    lat_col = _pick_column(columns, LAT_ALIASES)

    if lon_col is None or lat_col is None:
        # 统计表：无坐标，供分级设色使用；几何关联由 analyze(join) 负责（T14）。
        summary = (
            f"{name}：统计表 {len(df)} 行、{len(columns)} 列，编码 {encoding}。"
            "未发现经纬度列，按统计表处理，需关联行政区后才能成图。"
        )
        return DataLayer(
            kind="table",
            name=name,
            source=f"上传文件 {name}",
            summary=summary,
            crs=None,
            meta={"encoding": encoding, "columns": columns, "crs_status": "not_applicable"},
        )

    lon = pd.to_numeric(df[lon_col], errors="coerce")
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    invalid = int(lon.isna().sum() + lat.isna().sum())
    valid = df.loc[lon.notna() & lat.notna()].copy()
    if valid.empty:
        raise DataError(f"{name}：经纬度列（{lon_col}/{lat_col}）没有可用的数值，无法转成点位")

    geometry = gpd.points_from_xy(pd.to_numeric(valid[lon_col]), pd.to_numeric(valid[lat_col]))
    gdf = gpd.GeoDataFrame(valid, geometry=geometry)
    if crs:
        gdf = gdf.set_crs(crs, allow_override=True)
        crs_status: Literal["declared", "missing"] = "declared"
        crs_note = f"坐标系按用户确认的 {crs} 处理"
    else:
        crs_status = "missing"
        crs_note = "文件未声明坐标系，需用户确认后才能继续（建议先确认是否 WGS84 / EPSG:4326）"

    name_col = _pick_column(columns, NAME_ALIASES)
    code_col = _pick_column(columns, CODE_ALIASES)
    city_col = _pick_column(columns, CITY_ALIASES)
    field_columns = [
        col for col in columns if col not in {lon_col, lat_col, name_col, code_col, city_col}
    ]

    summary = (
        f"{name}：点位 {len(gdf)} 个（原始 {len(df)} 行"
        + (f"，{invalid} 个经纬度缺失已剔除" if invalid else "")
        + f"），编码 {encoding}。"
        f"可用指标列 {len(field_columns)} 个"
        + (f"（{('、'.join(field_columns[:6]))}{'…' if len(field_columns) > 6 else ''}）" if field_columns else "")
        + f"。{crs_note}。"
    )
    return DataLayer(
        kind="point",
        name=name,
        source=f"上传文件 {name}",
        summary=summary,
        gdf=gdf,
        crs=gdf.crs.to_string() if gdf.crs else None,
        meta={
            "encoding": encoding,
            "columns": columns,
            "field_columns": field_columns,
            "name_field": name_col,
            "code_field": code_col,
            "city_field": city_col,
            "crs_status": crs_status,
            "crs_confirmed_by_user": bool(crs),
            "suggested_crs": None if crs else "EPSG:4326",
            "invalid_coordinates": invalid,
        },
    )


def _layer_kind_from_geometry(gdf: gpd.GeoDataFrame) -> Literal["point", "admin"]:
    """点图层标 point，其余（面/线/混合）按 admin 保守处理。

    上传的 GeoJSON 与 Shapefile 可能是点位，也可能是边界；若一律标 admin，
    插值体检会直接拒绝点数据。
    """
    types = {str(value) for value in gdf.geom_type if value}
    if types and types.issubset({"Point", "MultiPoint"}):
        return "point"
    return "admin"


def _geojson_declares_crs(path: Path) -> bool:
    """RFC 7946 的 GeoJSON 没有 crs 成员；旧规范才写 crs。

    这里只判断“文件是否自己声明了坐标系”，不替用户做决定。
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataError(f"GeoJSON 解析失败：{exc}") from exc
    if not isinstance(raw, dict):
        raise DataError("GeoJSON 顶层必须是对象")
    if "crs" in raw:
        return True
    return False


def _geojson_to_layer(path: Path, name: str, crs: str | None) -> DataLayer:
    declares = _geojson_declares_crs(path)
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise DataError(f"{name}：GeoJSON 没有要素")

    if crs:
        gdf = gdf.set_crs(crs, allow_override=True)
        crs_status: Literal["declared", "missing"] = "declared"
        crs_note = f"坐标系按用户确认的 {crs} 处理"
    elif declares:
        crs_status = "declared"
        crs_note = f"文件自带坐标系声明（{gdf.crs.to_string() if gdf.crs else '未知'}）"
    else:
        crs_status = "missing"
        crs_note = "文件未声明坐标系（RFC 7946 默认 WGS84），需用户确认后才能继续"

    field_columns = [
        col
        for col in gdf.columns
        if col != gdf.geometry.name and pd.api.types.is_numeric_dtype(gdf[col])
    ]
    summary = (
        f"{name}：要素 {len(gdf)} 个，几何类型 "
        f"{'、'.join(sorted({str(g) for g in gdf.geom_type if g}))}。"
        f"可用数值字段 {len(field_columns)} 个"
        + (f"（{('、'.join(map(str, field_columns[:6])))}{'…' if len(field_columns) > 6 else ''}）" if field_columns else "")
        + f"。{crs_note}。"
    )
    return DataLayer(
        kind=_layer_kind_from_geometry(gdf),
        name=name,
        source=f"上传文件 {name}",
        summary=summary,
        gdf=gdf,
        crs=gdf.crs.to_string() if gdf.crs else None,
        meta={
            "columns": list(map(str, gdf.columns)),
            "field_columns": list(map(str, field_columns)),
            "crs_status": crs_status,
            "crs_confirmed_by_user": bool(crs),
            "suggested_crs": None if (crs or declares) else "EPSG:4326",
            "crs_declared_in_file": declares,
        },
    )


def _find_shapefile(root: Path) -> Path:
    matches = sorted(root.rglob("*.shp"))
    if not matches:
        raise DataError("zip 内没有 .shp 文件；Shapefile 必须整体打包上传")
    if len(matches) > 1:
        names = "、".join(p.name for p in matches)
        raise DataError(f"zip 内有多个 .shp（{names}），一次只能解析一个图层")
    return matches[0]


def _shapefile_to_layer(path: Path, name: str, crs: str | None) -> DataLayer:
    if not zipfile.is_zipfile(path):
        raise DataError(f"{name}：不是有效的 zip 文件")
    with tempfile.TemporaryDirectory(prefix="mapsmith_shp_") as tmp:
        with zipfile.ZipFile(path) as archive:
            archive.extractall(tmp)
        shp_path = _find_shapefile(Path(tmp))
        base = shp_path.with_suffix("")
        missing = [suffix for suffix in SHP_REQUIRED if not base.with_suffix(suffix).exists()]
        if missing:
            raise DataError(
                f"{name}：Shapefile 缺少 {'、'.join(missing)}；"
                "必须整体打包 .shp/.shx/.dbf，不能只传 .shp"
            )
        has_prj = base.with_suffix(".prj").exists()

        gdf = _read_shapefile_with_encoding_fallback(shp_path)

    if crs:
        gdf = gdf.set_crs(crs, allow_override=True)
        crs_status: Literal["declared", "missing"] = "declared"
        crs_note = f"坐标系按用户确认的 {crs} 处理"
    elif has_prj and gdf.crs is not None:
        crs_status = "declared"
        crs_note = f"文件自带 .prj（{gdf.crs.to_string()}）"
    else:
        crs_status = "missing"
        crs_note = "缺少 .prj 且无用户确认，需确认坐标系后才能继续"

    field_columns = [
        str(col)
        for col in gdf.columns
        if col != gdf.geometry.name and pd.api.types.is_numeric_dtype(gdf[col])
    ]
    summary = (
        f"{name}：要素 {len(gdf)} 个，几何类型 "
        f"{'、'.join(sorted({str(g) for g in gdf.geom_type if g}))}。"
        f"可用数值字段 {len(field_columns)} 个"
        + (f"（{('、'.join(field_columns[:6]))}{'…' if len(field_columns) > 6 else ''}）" if field_columns else "")
        + f"。{crs_note}。"
    )
    return DataLayer(
        kind=_layer_kind_from_geometry(gdf),
        name=name,
        source=f"上传文件 {name}",
        summary=summary,
        gdf=gdf,
        crs=gdf.crs.to_string() if gdf.crs else None,
        meta={
            "columns": list(map(str, gdf.columns)),
            "field_columns": field_columns,
            "has_prj": has_prj,
            "crs_status": crs_status,
            "crs_confirmed_by_user": bool(crs),
            "suggested_crs": None if (crs or has_prj) else None,
        },
    )


def _read_shapefile_with_encoding_fallback(shp_path: Path) -> gpd.GeoDataFrame:
    """.dbf 字段编码在国内数据里常见 GBK；失败时回退并在 summary 之外留痕。"""
    last_error: Exception | None = None
    for encoding in ("utf-8", "gbk"):
        try:
            return gpd.read_file(shp_path, encoding=encoding)
        except (UnicodeDecodeError, ValueError) as exc:
            last_error = exc
    raise DataError(f"Shapefile 属性表编码无法识别（已尝试 UTF-8/GBK）：{last_error}")


def parse_upload(path: str | Path, *, crs: str | None = None) -> DataLayer:
    """解析一个上传文件。

    `crs` 只在用户已确认坐标系时传入；未确认且文件本身没声明时，
    返回的 `meta["crs_status"]` 为 `missing`，调用方必须拦截并弹窗确认。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise DataError(f"文件不存在：{file_path}")
    name = file_path.name
    suffix = file_path.suffix.lower()

    if suffix in (".csv", ".txt"):
        return _csv_to_layer(file_path, name, crs)
    if suffix in (".geojson", ".json"):
        return _geojson_to_layer(file_path, name, crs)
    if suffix == ".zip":
        return _shapefile_to_layer(file_path, name, crs)
    if suffix in (".tif", ".tiff"):
        raise DataError("GeoTIFF 是底图，不是矢量图层；请用 io.raster.load_geotiff")
    raise DataError(f"不支持的文件类型：{suffix or '（无扩展名）'}；支持 CSV / GeoJSON / Shapefile(zip)")


def ensure_crs(layer: DataLayer, *, confirmed_crs: str | None = None) -> DataLayer:
    """进入分析前的闸门：未确认坐标系就抛出 `CrsNotDeclared`。

    调用方（Agent / 界面）拿到异常后发起一次确认，用户选定后再用
    `parse_upload(..., crs=...)` 重新解析，不在这里替用户选默认值。
    """
    status = layer.meta.get("crs_status")
    if status in (None, "not_applicable"):
        return layer
    if status == "declared":
        return layer
    if confirmed_crs:
        return layer
    raise CrsNotDeclared(layer.name, layer.meta.get("suggested_crs"))