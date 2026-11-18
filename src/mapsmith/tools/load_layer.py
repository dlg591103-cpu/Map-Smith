"""T06 / T07 `load_layer`：行政边界与空气质量站点数据。

规则来源：
- docs/facts/05-MapSpec与工具契约.md 工具 2：`load_layer(kind, place, time?) -> Layer`。
- docs/facts/06-数据源与离线兜底.md：DataV GeoAtlas 行政边界；quotsoft 单日 CSV。
- docs/facts/02-范围与边界.md：文件未声明 CRS 不静默默认。

两个入口：
- `load_admin(place)`：行政边界，返回面图层。
- `load_air(place, date, field)`：站点空气质量，返回点图层。

离线优先：先找 `demo_data/`，再联网。联网失败时抛出明确错误，不伪造数据。
"""

from __future__ import annotations

import io as text_io
import time
from datetime import date as date_type
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from ..config import get_settings
from ..io.gcj02 import transform_geodataframe
from ..io.models import DataError, DataLayer, FieldMissing
from .resolve_place import PlaceResult, resolve_place

QUOTSOFT_SITES_URL = "https://quotsoft.net/air/data/china_sites_{date}.csv"

# quotsoft 的 type 值 → 标准字段名（MapSpec 用下划线，不含点号）。
FIELD_ALIASES = {
    "PM2.5": "PM2_5",
    "PM2.5_24h": "PM2_5_24h",
    "PM10": "PM10",
    "PM10_24h": "PM10_24h",
    "SO2": "SO2",
    "SO2_24h": "SO2_24h",
    "NO2": "NO2",
    "NO2_24h": "NO2_24h",
    "O3": "O3",
    "O3_8h": "O3_8h",
    "O3_8h_24h": "O3_8h_24h",
    "CO": "CO",
    "CO_24h": "CO_24h",
    "AQI": "AQI",
}
_STANDARD_TO_QUOTSOFT = {value: key for key, value in FIELD_ALIASES.items()}

SITE_COLUMN_ALIASES = {
    "station_code": ("监测点编码", "站点编码", "编码", "code", "station_code"),
    "station_name": ("监测点名称", "站点名称", "站点名", "名称", "name", "station_name"),
    "city": ("城市", "所属城市", "地市", "city"),
    "lon": ("经度", "东经", "lon", "lng", "longitude", "x"),
    "lat": ("纬度", "北纬", "lat", "latitude", "y"),
}


def _pick(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    normalized = {str(col).strip().lower().replace(" ", "").replace("_", ""): col for col in columns}
    for alias in aliases:
        hit = normalized.get(alias.strip().lower().replace(" ", "").replace("_", ""))
        if hit is not None:
            return str(hit)
    return None


def _read_csv_utf8(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="gbk")


def _local_admin_paths(adcode: str) -> list[Path]:
    root = get_settings().demo_data_dir / "boundaries"
    return [root / f"{adcode}_full.json", root / f"{adcode}.json"]


# 国内数据源（quotsoft）直连通常比经系统代理更稳，但个别网络只能走代理，
# 所以按「直连 → 直连 → 环境代理」的顺序尝试：两次直连容忍一次瞬时抖动，最后用代理兜底。
_DOWNLOAD_PLAN = (False, False, True)
_RETRY_DELAY_S = 2.0
# 整体预算：quotsoft 单日文件约 1.6 MB、下行可能只有 12 KB/s，一次就可能上百秒，
# 预算耗尽后不再继续重试，避免用户界面长时间无响应。
_DOWNLOAD_BUDGET_S = 240.0
_CONNECT_TIMEOUT_S = 15.0


def _fetch_once(url: str, timeout: float, *, trust_env: bool) -> str:
    import requests

    session = requests.Session()
    session.trust_env = trust_env
    try:
        response = session.get(url, timeout=(_CONNECT_TIMEOUT_S, timeout))
    finally:
        session.close()
    if response.status_code != 200:
        raise DataError(f"数据源返回 HTTP {response.status_code}：{url}")
    return response.text


def _net_hint(requests: Any, exc: BaseException | None) -> str:
    """把 requests 的原始异常翻成用户能看懂的一句话；技术细节只留类型名。"""
    errors = requests.exceptions
    if exc is None:
        return "数据源请求失败"
    if isinstance(exc, errors.SSLError):
        return "数据源连接被中断（TLS 提前断开），通常是网络或代理不稳定"
    if isinstance(exc, errors.ReadTimeout):
        return "数据源响应超时（文件较大或网速过慢）"
    if isinstance(exc, errors.ConnectTimeout):
        return "连接数据源超时"
    if isinstance(exc, errors.ConnectionError):
        return "无法连接数据源（连接被重置或网络不可达）"
    return f"数据源请求失败（{type(exc).__name__}）"


def _download(url: str, timeout: float) -> str:
    try:
        import requests
    except ImportError as exc:
        raise DataError("缺少 requests，无法联网取数据；请按 requirements.lock 安装依赖") from exc

    deadline = time.monotonic() + _DOWNLOAD_BUDGET_S
    last: BaseException | None = None
    attempts = 0
    for index, trust_env in enumerate(_DOWNLOAD_PLAN):
        if index and time.monotonic() > deadline:
            break
        attempts += 1
        try:
            return _fetch_once(url, timeout, trust_env=trust_env)
        except requests.RequestException as exc:
            last = exc
            if time.monotonic() > deadline:
                break
            if index + 1 < len(_DOWNLOAD_PLAN):
                time.sleep(_RETRY_DELAY_S)
    raise DataError(f"{_net_hint(requests, last)}，已尝试 {attempts} 次仍失败：{url}")


def _as_place(place: str | PlaceResult, *, online: bool, timeout: float) -> PlaceResult:
    if isinstance(place, PlaceResult):
        return place
    return resolve_place(place, online=online, timeout=timeout)


def load_admin(
    place: str | PlaceResult,
    *,
    online: bool = True,
    timeout: float = 15.0,
    source_is_gcj02: bool = True,
) -> DataLayer:
    """加载行政边界。

    离线文件优先（`demo_data/boundaries/{adcode}_full.json`），否则取 DataV。
    DataV 数据来源于高德，默认按 GCJ-02 处理并纠偏到 WGS84；若后续实测发现
    来源并非 GCJ-02，只需把 `source_is_gcj02` 关掉，不散落改坐标。
    """
    resolved = _as_place(place, online=online, timeout=timeout)
    adcode = resolved.adcode

    source_note = ""
    gdf: gpd.GeoDataFrame | None = None
    for candidate in _local_admin_paths(adcode):
        if candidate.exists():
            gdf = gpd.read_file(candidate)
            source_note = f"离线边界 {candidate.name}"
            break

    if gdf is None:
        if not online:
            raise DataError(
                f"没有 {resolved.full_name} 的离线边界文件，且已禁用联网；"
                f"请把 {adcode}_full.json 放入 demo_data/boundaries/"
            )
        text = _download(
            f"https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json", timeout
        )
        # 落盘缓存：边界取过一次就够，之后离线也能重画。写的是 DataV 原始返回，
        # 与已入库的 320300_full.json 等同源同格式；纠偏在加载之后做，不污染缓存。
        try:
            cached = get_settings().demo_data_dir / "boundaries" / f"{adcode}_full.json"
            cached.parent.mkdir(parents=True, exist_ok=True)
            if not cached.exists():
                cached.write_text(text, encoding="utf-8")
        except OSError:
            pass  # 缓存失败不影响本次出图
        gdf = gpd.read_file(text_io.StringIO(text))
        source_note = "DataV GeoAtlas 实时边界"

    if gdf.empty:
        raise DataError(f"{resolved.full_name} 的行政边界为空")

    # DataV 是高德源，通常给经纬度但不写 CRS；按 4326 载入并如实标注来源，
    # 是否纠偏由后续产品决策，不在加载阶段偷偷改坐标。
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    name_field = _pick([str(col) for col in gdf.columns], ("name", "名称", "地名"))
    code_field = _pick([str(col) for col in gdf.columns], ("adcode", "编码"))

    transform_record: dict[str, Any] | None = None
    if source_is_gcj02:
        gdf, transform_record = transform_geodataframe(gdf, direction="gcj02_to_wgs84")

    shift_note = (
        "已按 GCJ-02→WGS84 纠偏（公开近似算法，约 1–2 m）"
        if transform_record
        else "未做坐标系纠偏"
    )
    summary = (
        f"{resolved.full_name}行政边界：{len(gdf)} 个面要素，几何 "
        f"{'、'.join(sorted({str(g) for g in gdf.geom_type if g}))}，"
        f"坐标系 {gdf.crs.to_string()}，来源 {source_note}；{shift_note}。"
    )

    return DataLayer(
        kind="admin",
        name=f"{resolved.full_name}行政边界",
        source=source_note,
        summary=summary,
        gdf=gdf,
        crs=gdf.crs.to_string(),
        meta={
            "adcode": adcode,
            "level": resolved.level,
            "bbox": list(resolved.bbox),
            "name_field": name_field,
            "code_field": code_field,
            "source_crs": "GCJ-02（高德源，未实测）" if source_is_gcj02 else "WGS84",
            "transform": transform_record,
            "crs_note": "DataV 边界按 GCJ-02 纠偏到 WGS84；偏移量尚未实测",
        },
    )


def _standardize_sites(df: pd.DataFrame, source: str) -> pd.DataFrame:
    columns = [str(col) for col in df.columns]
    mapping = {key: _pick(columns, aliases) for key, aliases in SITE_COLUMN_ALIASES.items()}
    missing = [key for key, value in mapping.items() if value is None]
    if missing:
        raise DataError(f"站点列表缺少必需字段：{'、'.join(missing)}（来源 {source}）")

    sites = pd.DataFrame(
        {
            "station_code": df[mapping["station_code"]].astype(str).str.strip(),
            "station_name": df[mapping["station_name"]].astype(str).str.strip(),
            "city": df[mapping["city"]].astype(str).str.strip(),
            "lon": pd.to_numeric(df[mapping["lon"]], errors="coerce"),
            "lat": pd.to_numeric(df[mapping["lat"]], errors="coerce"),
        }
    )
    sites = sites.dropna(subset=["lon", "lat"])
    sites = sites.drop_duplicates(subset=["station_code"])
    if sites.empty:
        raise DataError(f"站点列表没有可用的经纬度（来源 {source}）")
    return sites


def _load_sites(path: Path | None, *, online: bool, timeout: float) -> tuple[pd.DataFrame, str]:
    settings = get_settings()
    candidates = [path] if path else [
        settings.demo_data_dir / "sites" / "sites.csv",
        settings.demo_data_dir / "sites.csv",
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return _standardize_sites(_read_csv_utf8(candidate), str(candidate)), str(candidate)
    raise DataError(
        "没有站点列表（含监测点编码、名称、城市、经纬度）；"
        "请提供站点列表文件或放入 demo_data/sites/sites.csv"
    )


def _extract_field_series(air: pd.DataFrame, field_name: str, day: str) -> pd.DataFrame:
    if "type" not in air.columns:
        raise DataError("空气质量文件缺少 type 列，不符合 quotsoft 格式")
    quotsoft_type = _STANDARD_TO_QUOTSOFT.get(field_name)
    if quotsoft_type is None:
        raise FieldMissing(field_name, sorted(_STANDARD_TO_QUOTSOFT))

    subset = air[air["type"].astype(str).str.strip() == quotsoft_type]
    if subset.empty:
        available = sorted({str(value) for value in air["type"].dropna().unique()})
        raise FieldMissing(field_name, available)

    if "date" in air.columns:
        subset = subset[subset["date"].astype(str).str.strip() == day]

    # 小时必须按数值升序，否则 ffill 会沿文件行序而不是时间顺序推进。
    if "hour" in air.columns and not subset.empty:
        subset = subset.assign(_hour=pd.to_numeric(subset["hour"], errors="coerce")).sort_values("_hour")
        subset = subset.drop(columns=["_hour"])

    id_columns = {"date", "hour", "type"}
    station_columns = [str(col) for col in subset.columns if str(col) not in id_columns]
    if not station_columns:
        raise DataError("空气质量文件中没有站点列")

    values = subset[station_columns].apply(pd.to_numeric, errors="coerce")
    # _24h 字段本身已是滚动 24 小时值，取当日最后一个有效观测；
    # 1 小时字段按当日有效小时取均值。两种口径都写进 summary。
    if quotsoft_type.endswith("_24h") or quotsoft_type == "AQI":
        latest = values.ffill().iloc[-1] if not values.empty else pd.Series(dtype=float)
        series = latest
        method = "取当日最后一个有效观测"
    else:
        series = values.mean(skipna=True)
        method = "取当日有效小时均值"

    result = series.rename("value").reset_index()
    result.columns = ["station_code", "value"]
    result["station_code"] = result["station_code"].astype(str).str.strip()
    return result.assign(aggregate=method)


def load_air(
    place: str | PlaceResult,
    day: str | date_type,
    *,
    field: str = "PM2_5_24h",
    sites_path: str | Path | None = None,
    data_path: str | Path | None = None,
    online: bool = True,
    # 省级取数时传入省内各市名：quotsoft 的站点按「地级市」归属，
    # 直接用省名（「浙江省」）匹配一个站都匹配不到。
    city_names: list[str] | None = None,
    # 单日全国站点 CSV 约 1.5 MB，quotsoft 实测下行约 12 KB/s，20 秒太紧；
    # 这里是「无数据到达」的读取超时，正常下载不会反复触发。
    timeout: float = 120.0,
) -> DataLayer:
    """加载某城市（或某省内各市）某日的站点空气质量。`day` 支持 `YYYYMMDD`/`YYYY-MM-DD`。"""
    day_text = str(day).replace("-", "")
    if len(day_text) != 8 or not day_text.isdigit():
        raise DataError(f"日期格式应为 YYYYMMDD，实际为 {day!r}")

    resolved = _as_place(place, online=online, timeout=timeout)
    city_bare = resolved.full_name.removesuffix("市")

    sites, sites_source = _load_sites(Path(sites_path) if sites_path else None, online=online, timeout=timeout)

    settings = get_settings()
    air: pd.DataFrame | None = None
    data_source = ""
    if data_path:
        candidate = Path(data_path)
        if not candidate.exists():
            raise DataError(f"空气质量文件不存在：{candidate}")
        air = _read_csv_utf8(candidate)
        data_source = str(candidate)
    else:
        local = settings.demo_data_dir / "air" / f"china_sites_{day_text}.csv"
        if local.exists():
            air = _read_csv_utf8(local)
            data_source = str(local)
        elif online:
            text = _download(QUOTSOFT_SITES_URL.format(date=day_text), timeout)
            air = pd.read_csv(text_io.StringIO(text))
            data_source = f"quotsoft china_sites_{day_text}.csv"
            # 落盘缓存：同一日期下次即使断网也能直接用（现场演示只需联网一次）。
            # 写盘失败不影响本次出图，只是下次仍需联网。
            try:
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_text(text, encoding="utf-8")
            except OSError:
                pass
        else:
            raise DataError(
                f"没有 {day_text} 的离线空气质量数据，且已禁用联网；"
                "请把 china_sites_YYYYMMDD.csv 放入 demo_data/air/"
            )

    series = _extract_field_series(air, field, day_text)
    method = str(series["aggregate"].iloc[0]) if not series.empty else "无"
    # 指标列直接用标准字段名，渲染层与体检按 field 取列，不再出现含糊的 value。
    series = series.drop(columns=["aggregate"]).rename(columns={"value": field})
    merged = sites.merge(series, on="station_code", how="inner")

    if city_names:
        # 省级取数：quotsoft 的站点按地级市归属，用省内各市名逐个匹配。
        # 市名去掉「市」后缀后与站点表里的写法对齐（「杭州市」→「杭州」）。
        bare_names = [str(name).strip().removesuffix("市") for name in city_names if str(name).strip()]
        city_matched = merged[
            merged["city"].astype(str).apply(
                lambda city: any(name and name in city for name in bare_names)
            )
        ]
        label = f"{resolved.full_name}下辖 {len(bare_names)} 个市"
    else:
        city_matched = merged[merged["city"].str.contains(city_bare, na=False)]
        label = f"「{city_bare}」"
    if city_matched.empty:
        raise DataError(
            f"{resolved.full_name}：站点列表中没有匹配{label}的站点；"
            "请确认站点列表是否包含该城市"
        )

    valid = city_matched.dropna(subset=[field]).copy()
    total = len(city_matched)
    n_valid = len(valid)
    completeness = n_valid / total if total else 0.0
    if n_valid:
        vmin, vmax = float(valid[field].min()), float(valid[field].max())
        mean = float(valid[field].mean())
    else:
        vmin = vmax = mean = float("nan")

    # 保留全部匹配站点，缺测值以 NaN 留在指标列里：体检要据此算出完整度，
    # 渲染层可按 `meta["valid_count"]` 自行过滤，数据层不预先丢行。
    geometry = gpd.points_from_xy(city_matched["lon"], city_matched["lat"])
    gdf = gpd.GeoDataFrame(city_matched, geometry=geometry, crs="EPSG:4326")
    summary = (
        f"{resolved.full_name} {day_text} {field}：站点 {total} 个，有效值 {n_valid} 个"
        + (f"，最高 {vmax:.1f}、最低 {vmin:.1f}、均值 {mean:.1f}" if n_valid else "，全部缺测")
        + f"，完整度 {completeness:.0%}（{method}）。"
        f"数据来源：quotsoft.net；站点坐标 WGS84。"
    )

    return DataLayer(
        kind="point",
        name=f"{resolved.full_name}{day_text}{field}",
        source=f"quotsoft china_sites_{day_text}.csv",
        summary=summary,
        gdf=gdf,
        crs="EPSG:4326",
        meta={
            "adcode": resolved.adcode,
            "date": day_text,
            "field": field,
            "quotsoft_type": _STANDARD_TO_QUOTSOFT.get(field),
            "aggregate": method,
            "station_total": total,
            "station_valid": n_valid,
            "completeness": round(completeness, 4),
            "value_min": None if pd.isna(vmin) else vmin,
            "value_max": None if pd.isna(vmax) else vmax,
            "value_mean": None if pd.isna(mean) else mean,
            "sites_source": sites_source,
            "data_source_file": data_source,
            "station_crs": "EPSG:4326",
        },
    )

# --- 预置社会经济统计数据（GDP / 人口等）----------------------------------
# demo_data/stats/ 下按 `{adcode}_{指标}[_期次].csv` 命名，例如：
#   320000_gdp_2025q3.csv   江苏省 13 个设区市 2025 年前三季度 GDP（亿元）
# 数据须为真实公开统计（统计年鉴 / 统计公报），不生成示意值。
PRESET_STATS_METRICS: dict[str, str] = {
    "GDP": "gdp",
    "gdp": "gdp",
    "人口": "population",
    "population": "population",
}


def preset_stat_key(metric: str) -> str | None:
    """指标名 → 预置统计数据标识（gdp / population）；不是这类指标返回 None。"""
    text = str(metric or "").strip()
    if not text:
        return None
    return PRESET_STATS_METRICS.get(text) or PRESET_STATS_METRICS.get(text.lower())


def load_preset_stats(adcode: str, metric_key: str) -> tuple[pd.DataFrame, str] | None:
    """加载 `demo_data/stats/` 下的预置统计数据；没有则返回 None。

    文件名约定 `{adcode}_{metric_key}[_期次].csv`，同期次取字典序最后一个（即最新）。
    """
    if not adcode or not metric_key:
        return None
    root = get_settings().demo_data_dir / "stats"
    if not root.is_dir():
        return None
    candidates: list[Path] = []
    for pattern in (f"{adcode}_{metric_key}_*.csv", f"{adcode}_{metric_key}.csv"):
        candidates.extend(sorted(root.glob(pattern)))
    if not candidates:
        return None
    path = candidates[-1]
    try:
        frame = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001 - 预置文件损坏时如实报错
        raise DataError(f"预置统计数据读取失败：{path.name}（{exc}）") from exc
    if frame.empty:
        return None
    return frame, path.name
