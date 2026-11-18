"""用 DataV 的全国区划清单补全地名索引（provinces + cities）。

只跑一次：联网取 `areas_v3/bound/all.json`（约 330 KB），把全国 34 个省级、
363 个地级市合并进 `demo_data/places.json`。已有的条目（含 bbox、徐州区县）
原样保留，只补缺的 adcode。

用法：python tools_extend_places.py
"""

from __future__ import annotations

import json
import pathlib

import requests

ROOT = pathlib.Path(__file__).resolve().parent
PLACES = ROOT / "src" / "mapsmith" / "demo_data" / "places.json"
ALL_URL = "https://geo.datav.aliyun.com/areas_v3/bound/all.json"
SUFFIXES = ("特别行政区", "自治区", "自治州", "地区", "省", "市", "盟", "县", "区")


def _short(name: str) -> str:
    for suffix in SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def main() -> int:
    response = requests.get(ALL_URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    regions = response.json()
    print(f"DataV 区划清单：{len(regions)} 条")

    raw = json.loads(PLACES.read_text(encoding="utf-8"))
    places = raw["places"]
    existing = {str(item.get("adcode")) for item in places}
    before = len(places)

    for item in regions:
        level = str(item.get("level") or "")
        if level not in {"province", "city"}:
            continue
        adcode = str(item.get("adcode") or "")
        if not adcode or adcode in existing:
            continue
        full_name = str(item.get("name") or "").strip()
        if not full_name:
            continue
        parent_code = None
        try:
            number = int(adcode)
            parent_code = f"{str(number)[:2]}0000" if level == "city" else "100000"
        except ValueError:
            parent_code = None
        places.append(
            {
                "name": _short(full_name),
                "full_name": full_name,
                "adcode": adcode,
                "level": level,
                "parent": parent_code,
            }
        )
        existing.add(adcode)

    raw["places"] = places
    raw["version"] = "2026-11-18"
    raw["source"] = (
        "离线索引：全国省级与地级市取自 DataV GeoAtlas areas_v3/bound/all.json"
        "（2026-11-18 抓取）；徐州区县为人工整理。bbox 按需联网补全。"
    )
    PLACES.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"places.json: {before} → {len(places)} 个（新增 {len(places) - before}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
