"""T05 `resolve_place`：地名 → adcode + bbox。

规则来源：docs/facts/05-MapSpec与工具契约.md 工具 1；docs/facts/06-数据源与离线兜底.md。

数据来源与限制：
- adcode 优先取离线索引 `demo_data/places.json`，联网时以 DataV GeoAtlas 为准
  （沙箱出站被拦截，本机尚未复核真实可用性）。
- bbox 顺序沿用 GeoJSON：[minx, miny, maxx, maxy]。
- DataV 数据来源于高德开放平台，坐标系疑为 GCJ-02，本模块只如实标注，不纠偏。

不做的事：地名歧义或未收录时抛 `AmbiguousPlace` / `PlaceNotFound`，由 Agent 反问用户，
不猜一个默认值（docs/facts/04 数据管家约束）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..io.models import AmbiguousPlace, DataError, PlaceNotFound

DATAV_BOUND_URL = "https://geo.datav.aliyun.com/areas_v3/bound/{adcode}.json"
DATAV_BOUND_FULL_URL = "https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json"

# 区划名称的常见后缀；只用于比较，不改变展示用全名。
_SUFFIXES = ("特别行政区", "自治区", "自治州", "地区", "省", "市", "盟", "县", "区")


@dataclass(frozen=True)
class PlaceResult:
    """一次地名解析结果，`bbox` 已按 [minx, miny, maxx, maxy] 排列。"""

    name: str
    full_name: str
    adcode: str
    level: str
    parent: str | None
    bbox: tuple[float, float, float, float]
    bbox_source: str
    source: str
    summary: str
    meta: dict[str, Any] = field(default_factory=dict)


def _default_index_path() -> Path:
    return get_settings().demo_data_dir / "places.json"


def _load_index(index_path: Path | None = None) -> list[dict[str, Any]]:
    path = Path(index_path) if index_path else _default_index_path()
    if not path.exists():
        raise DataError(f"离线地名索引不存在：{path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataError(f"离线地名索引不是合法 JSON：{path}（{exc}）") from exc
    places = raw.get("places") if isinstance(raw, dict) else raw
    if not isinstance(places, list):
        raise DataError(f"离线地名索引缺少 places 列表：{path}")
    return places


def _strip_suffix(text: str) -> str:
    for suffix in _SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def _match(query: str, places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按「全名精确 → 去后缀精确 → 尾部匹配 → 包含匹配」四级，取最具体的候选。

    例如「徐州市铜山区」同时包含「徐州市」与「铜山区」，按尾部匹配只会命中
    铜山区；只有同级候选并列时才交给调用方反问用户。
    """
    query = query.strip()
    if not query:
        return []

    exact = [p for p in places if query in (p.get("name"), p.get("full_name"))]
    if exact:
        return exact

    bare = _strip_suffix(query)
    normalized = [p for p in places if _strip_suffix(str(p.get("full_name", ""))) == bare]
    if normalized:
        return normalized

    def display(item: dict[str, Any]) -> str:
        return str(item.get("full_name") or item.get("name") or "")

    tail = [
        p
        for p in places
        if display(p) and (query.endswith(display(p)) or query.endswith(str(p.get("name") or "")))
    ]
    if tail:
        longest = max(len(display(p)) for p in tail)
        return [p for p in tail if len(display(p)) == longest]

    contained = [p for p in places if display(p) and display(p) in query]
    if contained:
        longest = max(len(display(p)) for p in contained)
        return [p for p in contained if len(display(p)) == longest]
    return []


def _local_boundary_paths(adcode: str) -> list[Path]:
    root = get_settings().demo_data_dir / "boundaries"
    return [root / f"{adcode}_full.json", root / f"{adcode}.json"]


def _bbox_from_geojson(text: str) -> tuple[float, float, float, float]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DataError(f"边界 GeoJSON 解析失败：{exc}") from exc
    if not isinstance(raw, dict):
        raise DataError("边界 GeoJSON 顶层必须是对象")

    coords: list[tuple[float, float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list) and len(node) >= 2 and all(
            isinstance(item, (int, float)) for item in node[:2]
        ):
            coords.append((float(node[0]), float(node[1])))
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            walk(node.get("coordinates"))
            for feature in node.get("features") or []:
                walk(feature)

    walk(raw)
    if not coords:
        raise DataError("边界 GeoJSON 没有坐标")
    xs = [x for x, _ in coords]
    ys = [y for _, y in coords]
    return (min(xs), min(ys), max(xs), max(ys))


def _fetch_boundary_bbox(adcode: str, timeout: float) -> tuple[float, float, float, float] | None:
    """联网取边界并算 bbox；网络不可用时返回 None，由调用方给出明确提示。"""
    try:
        import requests
    except ImportError:  # requests 是锁定依赖，缺失说明环境未按 lock 安装
        return None

    for template in (DATAV_BOUND_FULL_URL, DATAV_BOUND_URL):
        url = template.format(adcode=adcode)
        try:
            response = requests.get(url, timeout=timeout)
        except requests.RequestException:
            continue
        if response.status_code != 200 or not response.text.strip():
            continue
        try:
            return _bbox_from_geojson(response.text)
        except DataError:
            continue
    return None


def resolve_place(
    name: str,
    *,
    index_path: str | Path | None = None,
    online: bool = True,
    timeout: float = 10.0,
) -> PlaceResult:
    """把地名解析为 adcode 与 bbox。

    缺区域时调用方应直接用抛出的异常发起反问，不要把异常吞掉后填默认值。
    """
    places = _load_index(Path(index_path) if index_path else None)
    matched = _match(name, places)
    if not matched:
        raise PlaceNotFound(
            f"离线索引中找不到地名「{name}」，也未确认联网可取；请补充上级行政区或直接提供 adcode"
        )
    if len(matched) > 1:
        candidates = [
            {"full_name": str(p.get("full_name")), "adcode": str(p.get("adcode")), "level": str(p.get("level"))}
            for p in matched
        ]
        raise AmbiguousPlace(name, candidates)

    entry = matched[0]
    adcode = str(entry["adcode"])
    full_name = str(entry.get("full_name") or entry.get("name"))

    bbox: tuple[float, float, float, float] | None = None
    bbox_source = ""

    if entry.get("bbox"):
        raw_bbox = entry["bbox"]
        if len(raw_bbox) != 4:
            raise DataError(f"索引中的 bbox 不是 4 个数：{raw_bbox}")
        bbox = (float(raw_bbox[0]), float(raw_bbox[1]), float(raw_bbox[2]), float(raw_bbox[3]))
        bbox_source = str(entry.get("bbox_source") or "离线索引")

    if bbox is None:
        for candidate in _local_boundary_paths(adcode):
            if candidate.exists():
                bbox = _bbox_from_geojson(candidate.read_text(encoding="utf-8-sig"))
                bbox_source = f"本地边界 {candidate.name}"
                break

    if bbox is None and online:
        fetched = _fetch_boundary_bbox(adcode, timeout)
        if fetched is not None:
            bbox = fetched
            bbox_source = "DataV GeoAtlas 实时边界"

    if bbox is None:
        raise DataError(
            f"已定位「{full_name}」（adcode {adcode}），但无法取得区域范围："
            "本地没有边界文件，联网取边界也失败。请提供边界文件或确认联网后重试"
        )

    minx, miny, maxx, maxy = bbox
    if not (minx < maxx and miny < maxy):
        raise DataError(f"区域范围不合法：{bbox}")

    summary = (
        f"{full_name}：adcode {adcode}，级别 {entry.get('level')}，"
        f"范围 [{minx:.2f}, {miny:.2f}, {maxx:.2f}, {maxy:.2f}]（来源：{bbox_source}）。"
    )
    if entry.get("bbox") and "示意" in bbox_source:
        summary += "范围为索引内的示意值，正式出图前应以边界数据复核。"

    return PlaceResult(
        name=str(entry.get("name") or full_name),
        full_name=full_name,
        adcode=adcode,
        level=str(entry.get("level") or "unknown"),
        parent=entry.get("parent"),
        bbox=bbox,
        bbox_source=bbox_source,
        source="离线索引 + DataV 兜底",
        summary=summary,
        meta={
            "index_version": json.loads(
                (_default_index_path() if index_path is None else Path(index_path)).read_text(encoding="utf-8")
            ).get("version"),
            "crs_note": "DataV 边界疑为 GCJ-02（高德源），未做纠偏，尚未实测",
            "online": online,
        },
    )