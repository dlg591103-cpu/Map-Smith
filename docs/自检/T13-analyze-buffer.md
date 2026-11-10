# T13 自检记录：analyze 缓冲区

| 项目 | 内容 |
| --- | --- |
| 任务 | T13 `analyze`：5 km 缓冲在度量投影下成立 |
| SPEC | [../Spec/V0.1-专题制图智能体.md](../Spec/V0.1-专题制图智能体.md)（第 6 节 T13、第 7 节验收） |
| 事实依据 | [../facts/05-MapSpec与工具契约.md](../facts/05-MapSpec与工具契约.md) 工具 3；[../facts/02-范围与边界.md](../facts/02-范围与边界.md)「内部量算」 |
| 分支 | `feat/cartographer` |
| 基线 | `main` @ `6e96f6b`（含 T01–T11） |
| 执行者 | CodeArts（AI 会话）。开发与自检为同一执行者；独立验收、Git 合并尚未进行 |
| 日期 | 2026-11-09 |

## 1. 交付物

- `src/mapsmith/tools/analyze.py`：`buffer_layer(layer, distance_km, *, quad_segs=16)` 与 `analyze(layer, op, params)` 分发入口（当前实现 `buffer`）。
- `src/tests/test_analyze.py`：8 个用例。

## 2. 完成判定核对

| 判定 | 结果 | 证据 |
| --- | --- | --- |
| 5 km 缓冲在度量投影下成立 | 通过 | 单点缓冲 5 km 面积 ≈ 78.5 km²（π·r²，误差 <5%），证明按米计算而非按度 |
| 选带回显 | 通过 | 徐州附近中心经度 117.18°E → 度量投影 `EPSG:4548`（CGCS2000 3°GK，无带号版） |
| 输出坐标系 | 通过 | 缓冲后转回 `EPSG:4326` |
| 非法输入被拒绝 | 通过 | 距离 ≤0、无几何、未知 op 均抛 `DataError` |
| 单测 | 通过 | `test_analyze.py` 8 passed；全量 `121 passed in 5.73s` |

## 3. 关键设计

- 契约签名来自 facts/05 工具 3 `analyze(op, params) -> Layer`；本任务实现 `buffer`，`clip` / `overlay` / `join` 见 T14。
- **关键正确性**：经纬度下直接 `buffer(5)` 会以「度」为单位，5 km 被错当成 5°。因此先用
  `projection.choose_measurement_crs(bbox)` 自动选带，在米制度量投影下缓冲，再转回 WGS84。
- 单点 / 单线等零跨度范围：微扩 bbox 后再选带，规避 `choose_measurement_crs` 的最小范围校验。
- 输出 `kind` 按输出几何判断（面 → `admin`），与 `io/uploads.py` 的 `_layer_kind_from_geometry` 约定一致，
  避免 `DataLayer.kind` 枚举（admin/point/raster/table）里没有「面」导致不一致。
- `meta` 记录 `op` / `buffer_km` / `measurement_crs` / `buffered_area_km2` / `feature_count`，
  summary 回灌 LLM（facts/05「返回契约」）。
- shapely 2.x 缓冲用 `quad_segs`（旧 `resolution` 参数已弃用）。

## 4. 未做

- 缓冲逐要素进行，未做 dissolve / 合并相邻缓冲面。
- 未实现 `clip` / `overlay` / `join`（T14）。
- 未接入 Agent、渲染层与 `loop.py`。
- 未推送分支、未合并回 `main`、未执行独立验收。