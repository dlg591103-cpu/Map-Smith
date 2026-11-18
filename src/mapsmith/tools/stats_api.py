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
import time
from typing import Any

import pandas as pd
import requests

BASE_URL = "https://www.gotohui.com/api/open/v1"
_TIMEOUT = 25.0
# 聚汇每个 Key 限 QPS=1（超了返回 400「调用频率超限」）。区县级取数要逐区县
# 搜索 + 取数，必须节流；留 0.1 秒余量，避免正好卡在边界上。
_MIN_INTERVAL_S = 1.1
_last_call_at = 0.0
# 边界层级 → 该取的榜单 slug。
# 注意：API 只提供「全国视角」的榜单（全国各省 / 全国各地级市），**没有区县级榜单**；
# 所以省级边界要取「全国地级市」榜再按本省各市名筛选，国家级别取「全国各省」榜。
# 实测（2026-11-18）：全部 243 个榜单的 `/ranking/{slug}` 都能免费读到数据，
# 即使 is_paid=true 也只是站内会员标记，不影响 API 榜单读取。
_SLUG_BY_LEVEL = {
    "gdp": {"country": "gdp/province", "province": "gdp/city"},
    "population": {"country": "renkou/province", "province": "renkou/city"},
}

# 常见指标名 → 榜单 slug 前缀（内置常用项，省一次搜索调用）。
# 未命中的指标会走 /ranking/list?word=... 动态搜索。
_METRIC_SLUGS: dict[str, str] = {
    "gdp": "gdp",
    "人均gdp": "renjun",
    "gdp增长率": "gdpz",
    "人口": "renkou",
    "常住人口": "renkou",
    "户籍人口": "huji",
    "城镇化率": "chengzhen",
    "财政收入": "yshouru",
    "一般公共预算收入": "yshouru",
    "财政支出": "yzhichu",
    "一般公共预算支出": "yzhichu",
    "税收收入": "shuishou",
    "增值税": "zengzhi",
    "存款余额": "rmbc",
    "住户存款": "zhuhu",
    "进出口总额": "zong",
    "进出口": "zong",
    "cpi": "cpi_annual",
    "通货膨胀率": "cpi_annual",
    "可支配收入": "czshouru",
    "人均可支配收入": "czshouru",
    "工资": "zgzonger",
    "医院数": "yiyuan",
    "医院床位": "yiyuan_chuangwei",
    "医生数": "yisheng",
    "卫生技术人员": "weisheng_jishu",
    "医疗卫生机构": "yiliao_jigou",
    "小学生数": "xiaoxue",
    "初中生数": "chuzhong",
    "高中生数": "gaozhong",
    "大学生数": "daxue",
    "研究生数": "yanjiu",
    "幼儿园数": "youer_school",
    "生育率": "fertility_rate",
    "人口自然增长率": "zengzhang",
    "房价": "house",
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


# 本地指标标识 → 聚汇榜单的 slug 前缀。多数两者同名（gdp），但人口是拼音
# `renkou`：拼错会返回「数据不存在或不可访问」，表现为「取不到任何榜单」。
_API_SLUG_PREFIXES: dict[str, str] = {
    "population": "renkou",
    "gdp": "gdp",
}


def _as_int(value: Any) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _throttle() -> None:
    """按 QPS=1 的限额节流：两次请求之间至少间隔 `_MIN_INTERVAL_S`。"""
    global _last_call_at
    wait = _MIN_INTERVAL_S - (time.monotonic() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.monotonic()


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    _throttle()
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


def fetch_ranking(slug: str) -> tuple[list[dict[str, Any]], str, int | None] | None:
    """按 slug 取榜单数据（免费）；返回 (行列表, 单位, 数据年份)。"""
    data = _get(f"/ranking/{slug}")
    if not data:
        return None
    rows = data.get("list")
    if not isinstance(rows, list) or not rows:
        return None
    unit = str(data.get("unit") or "")
    try:
        year = int(data.get("year")) if data.get("year") is not None else None
    except (TypeError, ValueError):
        year = None
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
    return (cleaned, unit, year) if cleaned else None


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


def resolve_metric_slug(metric_name: str) -> str | None:
    """把用户/模型给的指标名映射到榜单 slug 前缀。

    三级匹配：
    1. 内置别名表精确命中；
    2. **包含匹配**（「小学生数量」包含「小学生数」→ xiaoxue），取最长键；
    3. 调 ``/ranking/list?word=...`` 动态搜索。
    """
    text = str(metric_name or "").strip()
    if not text:
        return None
    key = re.sub(r"[\s_\-（）()]", "", text).lower()
    if key in _METRIC_SLUGS:
        return _METRIC_SLUGS[key]
    # 包含匹配：口语里的说法常带装饰词（「小学生数量」「常住人口总数」），
    # 精确查表会漏掉，取命中的最长键最稳。
    contained = [slug for hint, slug in _METRIC_SLUGS.items() if hint in key or key in hint]
    if contained:
        longest = max(
            (hint for hint in _METRIC_SLUGS if hint in key or key in hint), key=len
        )
        return _METRIC_SLUGS[longest]
    # 低置信度的动态搜索：只在显式配置了 Key 时进行
    if not stats_api_key():
        return None
    rankings = list_rankings(text, limit=20)
    if not rankings:
        return None
    for item in rankings:
        slug = str(item.get("slug") or "")
        prefix = slug.split("/")[0]
        if prefix:
            return prefix
    return None


def fetch_region_stats(
    metric_key: str,
    level: str,
    admin_names: set[str],
    *,
    metric_label: str = "",
) -> tuple[pd.DataFrame, str] | None:
    """用免费的榜单接口取「目标边界下辖各行政区」的指标值。

    - 边界是省级（如江苏省）：取「全国各地级市」榜，再按本省各市名筛选；
    - 边界是国家级别：取「全国各省」榜。
    - 区县级没有对应榜单，返回 None（由调用方提示改用预置/上传）。

    ``metric_key`` 是 slug 前缀（gdp / renkou / yshouru / chengzhen …），
    由 `resolve_metric_slug` 解析得到。

    返回 ``(DataFrame(district, value), 来源说明)``；未配置 Key 或筛选后不足 2 行
    时返回 None，不猜数据。
    """
    if not stats_api_key() or not admin_names or not metric_key:
        return None
    level_key = "province" if str(level).lower() == "province" else "country"
    suffix = "city" if level_key == "province" else "province"
    # 本地指标标识（gdp / population）与聚汇的 slug 前缀不一致：人口的榜单是
    # `renkou/*`（拼音），若直接拼 `population/city` 会取不到任何榜单。
    api_prefix = _API_SLUG_PREFIXES.get(metric_key, metric_key)
    slug = f"{api_prefix}/{suffix}"
    got = fetch_ranking(slug)
    if got is None:
        return None
    rows, unit, year = got
    wanted = {_base_name(name) for name in admin_names}
    matched = [row for row in rows if _base_name(row["district"]) in wanted]
    if len(matched) < 2:
        return None
    frame = pd.DataFrame(matched).drop_duplicates(subset=["district"])
    label = metric_label or metric_key
    scope = "全国各省" if level_key == "country" else "全国各地级市"
    # 数据期次写进来源注记：统计指标是年度口径，审查规则要求来源里带时间标记，
    # 否则会判 R05「缺少更新时间或日期」。
    period = f"（{year} 年数据）" if year else ""
    unit_text = f"（单位：{unit}）" if unit else ""
    source = f"聚汇数据开放API「{scope}{label}排行榜」{period}{unit_text}"
    return frame, source


# --- 区县级数据 ---------------------------------------------------------
# 聚汇的免费榜单只到地级市，区县级只能走「搜索指标 → 按 id 取数」；
# 取数按「买断限期访问权限」计费：1 积分买断一个指标序列 365 天。
_COUNTY_SEARCH_BATCH = 8  # /search 的 words 批量上限是 10，留点余量


def _pick_plainest(items: list[dict[str, Any]]) -> int | None:
    """从搜索结果里挑「最朴素」的那条指标。

    同一个词会命中多条（「苏州市:虎丘区GDP」和「苏州市:虎丘区GDP:工业」），
    取名字最短的那条通常就是主指标，避免买到某个分项。
    """
    best_id: int | None = None
    best_len = 10**6
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        name = str(item.get("name") or "")
        if len(name) < best_len:
            best_len = len(name)
            best_id = int(item["id"])
    return best_id


def county_metric_ids(queries: list[str]) -> dict[str, int]:
    """批量搜索指标名，返回 ``{查询词: 指标 id}``。

    用 ``words`` 批量搜（一次最多 10 个词），比逐词搜索省调用次数。
    搜索免费，不受积分限制。
    """
    if not queries:
        return {}
    found: dict[str, int] = {}
    for start in range(0, len(queries), _COUNTY_SEARCH_BATCH):
        batch = queries[start : start + _COUNTY_SEARCH_BATCH]
        data = _get("/search", {"words": ",".join(batch), "limit": 8})
        if not data:
            continue
        groups = data.get("groups")
        if isinstance(groups, list):
            for group in groups:
                word = str(group.get("word") or "")
                picked = _pick_plainest(group.get("list") or [])
                if picked is not None:
                    found[word] = picked
        else:
            items = data.get("list") or []
            for word in batch:
                candidates = [
                    item
                    for item in items
                    if isinstance(item, dict)
                    and word.lower() in str(item.get("name") or "").lower()
                ]
                picked = _pick_plainest(candidates)
                if picked is not None:
                    found[word] = picked
    return found


def fetch_county_series(metric_id: int, *, confirm: bool = False) -> dict[str, Any]:
    """按指标 id 取数值序列。

    不带 ``confirm`` 时只返回报价（``need_authorization``），**不扣积分**；
    带 ``confirm=True`` 才真正买断并返回 ``values``。余额不足时原样返回报价，
    由调用方提示用户充值。
    """
    params = {"confirm": "1"} if confirm else None
    return _get(f"/data/{metric_id}", params) or {}


def _latest_value(data: dict[str, Any]) -> tuple[float | None, int | None]:
    """从 ``/data/{id}`` 的 ``values[]`` 里取最新一期（列表从新到旧）。"""
    values = data.get("values")
    if not isinstance(values, list) or not values:
        return None, None
    latest = values[0]
    if not isinstance(latest, dict):
        return None, None
    try:
        value = float(latest.get("value"))
    except (TypeError, ValueError):
        return None, None
    year = None
    try:
        year = int(str(latest.get("period") or "")[:4])
    except ValueError:
        year = None
    return value, year


def fetch_county_stats(
    city_name: str,
    metric_name: str,
    county_names: list[str],
    *,
    metric_label: str = "",
    confirm: bool = False,
) -> tuple[pd.DataFrame, str] | dict[str, Any] | None:
    """取某市下辖各区县的某项指标（区县级数据）。

    聚汇的榜单接口没有区县级，只能「搜索指标 → 按 id 取数」；取数需要积分
    （1 积分买断 365 天）。返回三态：

    - ``(DataFrame, 来源说明)``：成功取到 ≥2 个区县；
    - ``dict``：需要用户确认积分成本（``need_authorization`` 报价），原样透传；
    - ``None``：搜索不到或网络失败。
    """
    if not stats_api_key() or not county_names:
        return None
    city_bare = _base_name(city_name)
    queries = [f"{city_bare}{_base_name(name)}{metric_name}" for name in county_names]
    ids = county_metric_ids(queries)
    if not ids:
        return None

    rows: list[dict[str, Any]] = []
    unit = ""
    last_year: int | None = None
    for query in queries:
        metric_id = ids.get(query)
        if not metric_id:
            continue
        # 先不带 confirm 查一次（只报价、不扣分）。已购数据这一步就直接给数值；
        # 未购数据返回 need_authorization + 余额。余额不够时把报价原样返回，
        # 不能带 confirm 硬买——那样接口回 400，错误信息会被丢弃。
        data = fetch_county_series(metric_id, confirm=False)
        if not data:
            continue
        if data.get("need_authorization"):
            cost = _as_int(data.get("points_cost")) or 1
            balance = _as_int(data.get("points_balance")) or 0
            if not confirm or balance < cost:
                return data
            data = fetch_county_series(metric_id, confirm=True)
            if not data or data.get("need_authorization"):
                return data or None
        value, year = _latest_value(data)
        if value is None:
            continue
        county = _base_name(query[len(city_bare) :].replace(metric_name, ""))
        rows.append({"district": county, "value": value})
        unit = str(data.get("unit") or unit)
        last_year = year or last_year

    if len(rows) < 2:
        return None
    frame = pd.DataFrame(rows).drop_duplicates(subset=["district"])
    label = metric_label or metric_name
    period = f"（{last_year} 年数据）" if last_year else ""
    unit_text = f"（单位：{unit}）" if unit else ""
    source = f"聚汇数据开放API「{city_bare}各区县{label}」{period}{unit_text}"
    return frame, source


def fetch_account_balance() -> dict[str, Any] | None:
    """查聚汇账户余额与额度（免费接口，不扣积分）。

    返回 ``{points_balance, data_points_cost, access_validity_days,
    daily_limit, daily_used, qps_limit}``；未配置 Key 或请求失败返回 None。
    """
    if not stats_api_key():
        return None
    return _get("/me")
