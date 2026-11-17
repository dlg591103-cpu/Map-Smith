"""从徐州市生态环境局官方发布数据生成「区县 PM2.5」演示数据。

数据来源（真实，非构造）：
  徐州市生态环境局《徐州市各县（市）区空气质量情况（2026 年 1 月 1 日—1 月 15 日）》
  https://xz.gov.cn/xz_main/9ef4423a-0139-4648-9999-6ba943247f1c/
  374ccb54-63fc-47e5-9fd4-3eaca9e7d940/徐州市环境空气质量情况（2026年1月1日-1月15日）.pdf

口径说明：PM2.5 为「2026 年 1 月 1 日—1 月 15 日」累计浓度（μg/m³），不是单日值；
官方表中的「经开区」是功能区、不是行政区，demo 边界里没有对应面，故不纳入。

产出：
  demo_data/choropleth/xuzhou_district_pm25_20260115.csv
       district,adcode,pm2_5      原始数值（可追溯）
  demo_data/choropleth/xuzhou_district_pm25_20260115.geojson
       10 个区县面 + PM2_5_24h 属性，可直接在「高级表单 → 上传」作为面图层出分级设色图
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEMO = ROOT / "src" / "mapsmith" / "demo_data"
BOUNDARY = DEMO / "boundaries" / "320300_full.json"
OUT_DIR = DEMO / "choropleth"

# 官方发布值（μg/m³，2026-01-01 至 2026-01-15 累计）
PM25 = {
    "丰县": 66.7,
    "沛县": 71.7,
    "睢宁县": 64.3,
    "邳州市": 69.9,
    "新沂市": 65.7,
    "铜山区": 65.9,
    "贾汪区": 65.3,
    "鼓楼区": 62.0,
    "云龙区": 65.3,
    "泉山区": 73.9,
}

SOURCE = "徐州市生态环境局《徐州市各县（市）区空气质量情况（2026年1月1日-1月15日）》"


def main() -> int:
    boundary = json.loads(BOUNDARY.read_text(encoding="utf-8"))
    features = boundary.get("features", [])
    if not features:
        raise SystemExit(f"边界文件没有要素：{BOUNDARY}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    matched = 0
    for feat in features:
        props = feat.setdefault("properties", {})
        name = str(props.get("name", "")).strip()
        value = PM25.get(name)
        if value is not None:
            matched += 1
        props["PM2_5_24h"] = value
        props["data_source"] = SOURCE
        rows.append(
            {"district": name, "adcode": props.get("adcode", ""), "PM2_5_24h": "" if value is None else value}
        )

    if matched != len(PM25):
        missing = sorted(set(PM25) - {r["district"] for r in rows if r["PM2_5_24h"] != ""})
        raise SystemExit(f"有区县没匹配上边界：{missing}（边界里的名称：{[r['district'] for r in rows]}）")

    csv_path = OUT_DIR / "xuzhou_district_pm25_20260115.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["district", "adcode", "PM2_5_24h"])
        writer.writeheader()
        writer.writerows(rows)

    geo_path = OUT_DIR / "xuzhou_district_pm25_20260115.geojson"
    geo = {
        "type": "FeatureCollection",
        "name": "徐州市各区县PM2.5浓度(2026-01-01至01-15累计)",
        "crs": boundary.get("crs"),
        "features": features,
    }
    geo_path.write_text(json.dumps(geo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"已生成 {csv_path.name}（{len(rows)} 行）")
    print(f"已生成 {geo_path.name}（{len(features)} 个面，{matched} 个有值）")
    print(f"数据来源：{SOURCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
