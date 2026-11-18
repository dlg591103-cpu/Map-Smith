"""聚汇数据开放 API 接入（可选的统计数据源）。

文档：https://www.gotohui.com/open-api/docs

为什么用它：GDP / 人口这类社会经济数据没有免费的统一开放接口（国家统计局接口
有反爬、区县数据散落在年鉴里）。聚汇数据提供了「宏观数据」开放 API：

- ``GET /search?word=北京GDP``          免费，找指标 id
- ``GET /ranking/list?word=GDP``        免费，列出榜单（拿到 slug）
- ``GET /ranking/{slug}``               免费，直接返回「地区 → 数值」列表
- ``GET /data/{id}``                    取数，消耗积分（1 积分买断一条数据）

本模块**只用免费的榜单接口**（``/ranking/list`` + ``/ranking/{slug}``），
不调用扣积分的 ``/data/{id}``，所以不会产生费用。

需要 API Key：注册后在会员中心创建，填到环境变量 ``MAPSMITH_STATS_API_KEY``。
"""

from __future__ import annotations

import os
import re
from typing import Any

import pandas as pd
import requests

BASE_URL = "https://www.gotohui.com/api/open/v1"
_TIMEOUT = 25.0
# 指标标识 → 榜单标题里的关键词（/ranking/list 搜索用）
_RANKING_WORDS = {"gdp": "GDP", "population": "人口"}
# 边界层级 → 该取的榜单 slug。
# 注意：API 只提供「全国视角」的榜单（全国各省 / 全国各地级市），**没有区县级榜单**；
# 所以省级边界要取「全国地级市」榜再按本省各市名筛选，国家级别取「全国各省」榜。
_SLUG_BY_LEVEL = {
    "gdp": {"country": "gdp/province", "province": "gdp/city"},
    "population": {"country": "renkou/province", "province": "renkou/city"},
}
_SUFFIXES = ("市", "区", "县", "自治州", "盟", "地区")


def stats_api_key() -> str:
    """读取聚汇数据 API Key；未配置返回空串。"""
    return os.environ.get("MAPSMITH_STATS_API_KEY", "").strip()


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {stats_api_key()}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (MapSmith; stats-api)",
    }


def _base_name(name: str) -> str:
    """去掉行政区后缀，便于不同数据源之间对齐（「杭州市」↔「杭州」）。"""
    text = str(name or "").strip()
    for suffix in _SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    try:
        response = requests.get(
            f"{BASE_URL}{path}", params=params, headers=_headers(), timeout=_TIMEOUT
        )
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if payload.get("status") != 200:
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def list_rankings(word: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """拉榜单列表（免费）；返回 [{slug, title, unit, region_level}]。"""
    data = _get("/ranking/list", {"word": word, "limit": limit})
    if not data:
        return []
    items = data.get("list")
    return [item for item in items or [] if isinstance(item, dict)]


def fetch_ranking(slug: str) -> tuple[list[dict[str, Any]], str] | None:
    """按 slug 取榜单数据（免费）；返回 (行列表, 单位)。"""
    data = _get(f"/ranking/{slug}")
    if not data:
        return None
    rows = data.get("list")
    if not isinstance(rows, list) or not rows:
        return None
    unit = str(data.get("unit") or "")
    cleaned: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = str(item.get("region_name") or "").strip()
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        if name and value > 0:
            cleaned.append({"district": name, "value": value})
    return (cleaned, unit) if cleaned else None


def _pick_slug(
    rankings: list[dict[str, Any]], adcode: str, admin_names: set[str]
) -> str | None:
    """在榜单列表里挑出「该 adcode 下辖各市/区县」的那一条。

    优先看 slug 里的 adcode（形如 ``gdp/city/320000``），其次看标题是否包含
    边界里的行政区名。
    """
    adcode = str(adcode or "").strip()
    for item in rankings:
        slug = str(item.get("slug") or "")
        if adcode and slug.endswith(f"/{adcode}"):
            return slug
    base_names = {_base_name(name) for name in admin_names}
    for item in rankings:
        title = str(item.get("title") or "")
        title_bases = {_base_name(token) for token in re.findall(r"[\u4e00-\u9fa5]{2,}", title)}
        if len(title_bases & base_names) >= 2:
            return str(item.get("slug") or "") or None
    return None


def fetch_region_stats(
    metric_key: str,
    level: str,
    admin_names: set[str],
) -> tuple[pd.DataFrame, str] | None:
    """用免费的榜单接口取「目标边界下辖各行政区」的指标值。

    - 边界是省级（如江苏省）：取「全国各地级市」榜，再按本省各市名筛选；
    - 边界是国家级别：取「全国各省」榜。
    - 区县级没有对应榜单，返回 None（由调用方提示改用预置/上传）。

    返回 ``(DataFrame(district, value), 来源说明)``；未配置 Key 或筛选后不足 2 行
    时返回 None，不猜数据。
    """
    if not stats_api_key() or not admin_names:
        return None
    normal_level = "province" if str(level).lower() == "province" else "country"
    slug = _SLUG_BY_LEVEL.get(metric_key, {}).get(normal_level)
    if slug is None:
        return None
    got = fetch_ranking(slug)
    if got is None:
        return None
    rows, unit = got
    wanted = {_base_name(name) for name in admin_names}
    matched = [row for row in rows if _base_name(row["district"]) in wanted]
    if len(matched) < 2:
        return None
    frame = pd.DataFrame(matched).drop_duplicates(subset=["district"])
    title = "全国各省" if normal_level == "country" else "全国各地级市"
    label = "GDP" if metric_key == "gdp" else "常住人口"
    source = f"聚汇数据开放API「{title}{label}排行榜」{('（单位：' + unit + '）') if unit else ''}"
    return frame, source
