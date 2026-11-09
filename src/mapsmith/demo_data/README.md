# demo_data 离线数据

断网演示用的内置数据。三份真实文件已于 2026-11-09 补齐，来源与版本如下。

## 目录与来源

```
demo_data/
├── places.json                       离线地名索引（徐州 bbox 已换为实测值）
├── boundaries/
│   └── 320300_full.json              徐州下辖区县边界，DataV GeoAtlas
├── sites/
│   └── sites.csv                     站点列表，quotsoft「站点列表-2025.02.25起」
└── air/
    └── china_sites_20261101.csv      单日空气质量，quotsoft 2026-11-01
```

| 文件 | 版本 / 获取方式 | 内容 |
| --- | --- | --- |
| `boundaries/320300_full.json` | `https://geo.datav.aliyun.com/areas_v3/bound/320300_full.json` | 10 个区县；GCJ-02，加载时纠偏到 WGS84 |
| `sites/sites.csv` | quotsoft 网盘「站点列表-2025.02.25起.xlsx」，Excel 另存为 CSV UTF-8 | 2127 个站点，字段 6 列；徐州 11 站 |
| `air/china_sites_20261101.csv` | `https://quotsoft.net/air/data/china_sites_20261101.csv` | 2026 个站点列、15 种 type × 24 小时 |

## 实测结论（2026-11-01，徐州，PM2.5_24h）

- 站点列表 11 站；空气数据列里有 10 站（`4186A` 解放南路202号 不在当日文件中）
- 其中 `1177A`、`1178A`、`1179A`、`1181A`、`1183A` 五个站整日缺测
- 有效站数 `n = 5`，完整度 50%，极值 45–58 μg/m³
- 站点凸包 217.3 km²，研究区 11134.5 km²，覆盖度 1.95%
- 判定：**降级为点图 / 气泡图**；度量投影 `EPSG:4548`（CM 117°E）

## 注意

- 站点列表与空气数据的版本年份不同会有编码差：换数据时同时核对这两份。
- 不要把未经核实的数值放进来冒充实测数据；演示数据必须在文件名与界面同时标注。
- `places.json` 的徐州 bbox 取自本地边界纠偏后实测，换边界文件后需重算。