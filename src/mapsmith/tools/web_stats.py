"""联网搜索统计数据（GDP / 人口等）：搜索 → 抓取 → LLM 抽取 → 校验。

背景：区县/地市级 GDP、人口这类数据**没有统一的免费开放 API**（国家统计局接口
以省市为主且有反爬，区县数据分散在各地统计年鉴与新闻稿里）。因此这里走一条
「搜索引擎 + 网页解析 + LLM 抽取 + 地区名校验」的兜底链路：

1. 用 Bing 的 HTML 结果页搜索（无需 API key）；
2. 收集结果链接，按 URL 关键词（gdp / stat / 统计 / 数据 / 排名）打分排序；
3. 依次抓取，清洗成纯文本（保留表格单元格分隔）；
4. 用 LLM 抽取 ``{"rows": [{"district": "苏州市", "value": 19930.21}]}``；
5. 与边界里的行政区名交叉校验，**匹配率 ≥ 50% 才采用**；
6. 命中后由调用方缓存到 ``demo_data/stats/``。

任何一步失败都返回 None（由调用方给明确提示），不猜数据、不编数字。
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Callable, Mapping

import pandas as pd
import requests

_BING_URL = "https://www.bing.com/search?q={query}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
# 网页链接里出现这些片段，说明更可能是数据页而不是百科/政府首页。
_URL_HINT_WORDS = ("gdp", "stat", "data", "rank", "tongji", "jingji")
_URL_HINT_CN = ("统计", "数据", "排名", "经济", "公报", "年鉴")
_MAX_CANDIDATES = 6
_MAX_TEXT_CHARS = 12000


def _search_links(query: str, *, timeout: float) -> list[str]:
    """Bing HTML 搜索，返回去重后的结果链接（按 URL 线索打分排序）。"""
    url = _BING_URL.format(query=urllib.parse.quote(query))
    try:
        response = requests.get(url, headers=_HEADERS, timeout=timeout)
    except requests.RequestException:
        return []
    if response.status_code != 200:
        return []
    pairs = re.findall(
        r'<h2><a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a></h2>', response.text, re.S
    )
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for href, title_html in pairs:
        href = href.strip()
        if href in seen or "bing.com" in href:
            continue
        seen.add(href)
        haystack = (href + " " + re.sub(r"<[^>]+>", "", title_html)).lower()
        score = sum(1 for word in _URL_HINT_WORDS if word in haystack)
        score += sum(1 for word in _URL_HINT_CN if word in haystack)
        scored.append((score, href))
    scored.sort(key=lambda item: -item[0])
    return [href for _, href in scored[:_MAX_CANDIDATES]]


def _fetch_text(url: str, *, timeout: float) -> str | None:
    """抓取网页并清洗为纯文本；表格单元格用 ` | ` 连接，便于模型识别。"""
    try:
        response = requests.get(url, headers=_HEADERS, timeout=timeout)
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    # 编码：优先按响应头/内容判断，requests 对中文站点常猜错
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    html = response.text
    html = re.sub(r"<script[\s\S]*?</script>", " ", html)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html)
    html = re.sub(r"</t[dh]>", " | ", html, flags=re.I)
    html = re.sub(r"</tr>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    kept: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if len(line) < 6:
            continue
        has_place = ("市" in line or "区" in line or "县" in line or "省" in line)
        has_number = bool(re.search(r"\d{2,}", line))
        if has_place and has_number:
            kept.append(line)
    joined = "\n".join(kept)
    return joined[:_MAX_TEXT_CHARS] or None


_EXTRACT_PROMPT = """你是数据提取助手。用户想画一张「{place}的{metric_label}」专题地图。

下面是从网页抓到的文本，可能包含某地区各市/区县的 {metric_label} 数据（表格或新闻段落）。
请抽取成严格 JSON：

{{"rows": [{{"district": "地区名", "value": 数值}}]}}

要求：
1. district 用原文的地名，保留「市 / 区 / 县」后缀，不要改写；
2. value 只保留数字（亿元或万人等单位去掉），不要百分比、增速、排名数字；
3. 只抽取 {place} 下辖的行政区，别的省份/城市的数字不要；
4. 抽不到有效数据就返回 {{"rows": []}}；
5. 只返回 JSON，不要任何解释文字。
"""


def _extract_rows(
    text: str,
    place: str,
    metric_label: str,
    caller: Callable[[str, Mapping[str, Any]], Any],
) -> list[dict[str, Any]]:
    prompt = _EXTRACT_PROMPT.format(place=place, metric_label=metric_label)
    try:
        raw = caller(prompt, {"text": text})
    except Exception:  # noqa: BLE001 - 单页抽取失败继续试下一个候选
        return []
    rows = raw.get("rows") if isinstance(raw, Mapping) else None
    if not isinstance(rows, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        district = str(row.get("district") or "").strip()
        value = row.get("value")
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if district and number > 0:
            cleaned.append({"district": district, "value": number})
    return cleaned


def _match_rate(rows: list[dict[str, Any]], admin_names: set[str]) -> float:
    """提取出的地区名有多少能对上边界里的行政区名。"""
    if not rows or not admin_names:
        return 0.0
    normalized = {name.strip() for name in admin_names}
    hits = sum(1 for row in rows if str(row["district"]).strip() in normalized)
    return hits / len(rows)


def fetch_online_stats(
    place: str,
    metric_key: str,
    metric_label: str,
    admin_names: set[str],
    *,
    caller: Callable[[str, Mapping[str, Any]], Any],
    timeout: float = 25.0,
    min_match_rate: float = 0.5,
) -> tuple[pd.DataFrame, str] | None:
    """联网找「地区 → 指标值」表；失败返回 None（调用方负责给出明确提示）。

    返回 ``(DataFrame(district, value), 来源说明)``。
    """
    queries = [
        f"{place} 各市 {metric_label} 2025 排名 统计",
        f"{place} 各区县 {metric_label} 统计公报",
        f"{place} {metric_label} 排名",
    ]
    candidates: list[str] = []
    for query in queries:
        for href in _search_links(query, timeout=timeout):
            if href not in candidates:
                candidates.append(href)
        if len(candidates) >= _MAX_CANDIDATES:
            break

    for url in candidates[:_MAX_CANDIDATES]:
        text = _fetch_text(url, timeout=timeout)
        if not text:
            continue
        rows = _extract_rows(text, place, metric_label, caller)
        if len(rows) < 3:
            continue
        if _match_rate(rows, admin_names) < min_match_rate:
            # 抓到的不是目标地区的数据，继续找
            continue
        frame = pd.DataFrame(
            [{"district": row["district"], "value": row["value"]} for row in rows]
        ).drop_duplicates(subset=["district"])
        host = urllib.parse.urlparse(url).netloc
        return frame, f"联网检索 {host}（{len(frame)} 个地区）"
    return None
